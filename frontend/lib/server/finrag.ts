const MAX_BODY_BYTES = 16 * 1024;
const IDEMPOTENCY_KEY = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$/;
const HOSTLESS_ABSOLUTE_PATH = /^\/(?!\/)[A-Za-z0-9/_-]*$/;
const SAFE_RESPONSE_HEADERS = ["content-type"] as const;
const BODY_TOO_LARGE = Symbol("body-too-large");

function backendConfig() {
  const baseUrl = process.env.FINRAG_API_URL?.trim().replace(/\/+$/, "");
  const token = process.env.FINRAG_API_TOKEN?.trim();
  if (!baseUrl || !token) {
    throw new Error("finrag backend is not configured");
  }
  return { baseUrl, token };
}

function payloadTooLarge() {
  return Response.json(
    { code: "payload_too_large", error: "request body is too large" },
    { status: 413 },
  );
}

async function readBoundedBody(request: Request) {
  if (request.method === "GET" || request.method === "HEAD") {
    return undefined;
  }
  if (!request.body) {
    return "";
  }

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let totalBytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      totalBytes += value.byteLength;
      if (totalBytes > MAX_BODY_BYTES) {
        try {
          await reader.cancel();
        } catch {
          // Cancellation is best-effort after the request has already been rejected.
        }
        return BODY_TOO_LARGE;
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const bytes = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(bytes);
}

/**
 * Forwards a fixed server-side route to FinRAG without exposing credentials.
 */
export async function forwardToFinrag(
  request: Request,
  path: string,
): Promise<Response> {
  if (!HOSTLESS_ABSOLUTE_PATH.test(path)) {
    throw new Error("upstream path must be absolute and hostless");
  }

  const declaredLength = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(declaredLength) && declaredLength > MAX_BODY_BYTES) {
    return payloadTooLarge();
  }

  const body = await readBoundedBody(request);
  if (body === BODY_TOO_LARGE) {
    return payloadTooLarge();
  }

  const idempotencyKey =
    path === "/ingest" && request.method === "POST"
      ? request.headers.get("Idempotency-Key")
      : null;
  if (path === "/ingest" && request.method === "POST") {
    if (!idempotencyKey) {
      return Response.json(
        { code: "missing_idempotency_key", error: "missing Idempotency-Key" },
        { status: 400 },
      );
    }
    if (!IDEMPOTENCY_KEY.test(idempotencyKey)) {
      return Response.json(
        { code: "invalid_idempotency_key", error: "invalid Idempotency-Key" },
        { status: 400 },
      );
    }
  }

  const { baseUrl, token } = backendConfig();
  const requestHeaders: Record<string, string> = {
    Accept: path === "/ask" ? "text/event-stream" : "application/json",
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
  if (idempotencyKey) {
    requestHeaders["Idempotency-Key"] = idempotencyKey;
  }

  try {
    const upstream = await fetch(`${baseUrl}${path}`, {
      method: request.method,
      headers: requestHeaders,
      body,
      cache: "no-store",
      signal: AbortSignal.any([
        request.signal,
        AbortSignal.timeout(295_000),
      ]),
    });
    const responseHeaders = new Headers({ "cache-control": "no-store" });
    for (const name of SAFE_RESPONSE_HEADERS) {
      const value = upstream.headers.get(name);
      if (value) {
        responseHeaders.set(name, value);
      }
    }
    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch {
    console.error("finrag upstream request failed");
    return Response.json(
      { code: "backend_unavailable", error: "backend unavailable" },
      { status: 502 },
    );
  }
}
