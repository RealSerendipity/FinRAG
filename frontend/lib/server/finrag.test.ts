import { afterEach, describe, expect, test, vi } from "vitest";
import { forwardToFinrag } from "./finrag";

const API_URL = "https://api.example.com/";
const API_TOKEN = "secret-token";
const VALID_KEY = "request-123";

function configureBackend() {
  process.env.FINRAG_API_URL = API_URL;
  process.env.FINRAG_API_TOKEN = API_TOKEN;
}

function successfulUpstream(body = "ok", contentType = "application/json") {
  return new Response(body, {
    status: 200,
    headers: {
      authorization: "Bearer leaked",
      "content-type": contentType,
      "set-cookie": "private=1",
    },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete process.env.FINRAG_API_URL;
  delete process.env.FINRAG_API_TOKEN;
});

describe("forwardToFinrag", () => {
  test("adds server credentials and forwards only the three safe request headers", async () => {
    configureBackend();
    const upstream = vi.fn().mockResolvedValue(successfulUpstream());
    vi.stubGlobal("fetch", upstream);
    const request = new Request("http://localhost/api/agent", {
      method: "POST",
      headers: {
        Authorization: "Bearer attacker",
        Cookie: "session=private",
        "Idempotency-Key": VALID_KEY,
        "X-Forwarded-Host": "evil.example",
      },
      body: JSON.stringify({ question: "q" }),
    });

    await forwardToFinrag(request, "/agent");

    expect(upstream).toHaveBeenCalledOnce();
    const [url, init] = upstream.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.example.com/agent");
    expect(init.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${API_TOKEN}`,
      "Content-Type": "application/json",
    });
    expect(init.cache).toBe("no-store");
  });

  test("returns only content type and no-store headers from upstream", async () => {
    configureBackend();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(successfulUpstream()));

    const response = await forwardToFinrag(
      new Request("http://localhost/api/health"),
      "/health",
    );

    expect(response.headers.get("content-type")).toBe("application/json");
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.get("authorization")).toBeNull();
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  test("passes the upstream stream through without buffering", async () => {
    configureBackend();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("data: hello\n\n"));
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(stream, {
          headers: { "content-type": "text/event-stream" },
        }),
      ),
    );

    const response = await forwardToFinrag(
      new Request("http://localhost/api/ask", {
        method: "POST",
        body: JSON.stringify({ question: "q" }),
      }),
      "/ask",
    );

    expect(response.body).toBe(stream);
    expect(response.headers.get("content-type")).toBe("text/event-stream");
  });

  test("rejects an oversized declared content length without fetching", async () => {
    configureBackend();
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    const request = new Request("http://localhost/api/agent", {
      method: "POST",
      headers: { "content-length": String(16 * 1024 + 1) },
      body: "{}",
    });

    const response = await forwardToFinrag(request, "/agent");

    expect(response.status).toBe(413);
    await expect(response.json()).resolves.toEqual({
      code: "payload_too_large",
      error: "request body is too large",
    });
    expect(upstream).not.toHaveBeenCalled();
  });

  test("rejects an actual UTF-8 request body larger than 16 KiB", async () => {
    configureBackend();
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    const request = new Request("http://localhost/api/agent", {
      method: "POST",
      body: "é".repeat(8193),
    });

    const response = await forwardToFinrag(request, "/agent");

    expect(response.status).toBe(413);
    expect(upstream).not.toHaveBeenCalled();
  });

  test.each(["https://evil.example/agent", "//evil.example/agent", "agent"])(
    "rejects a non-hostless absolute upstream path: %s",
    async (path) => {
      configureBackend();
      await expect(
        forwardToFinrag(new Request("http://localhost/api/agent"), path),
      ).rejects.toThrow("upstream path must be absolute and hostless");
    },
  );

  test.each([
    ["FINRAG_API_URL", "FINRAG_API_TOKEN"],
    ["FINRAG_API_TOKEN", "FINRAG_API_URL"],
  ])("throws a safe configuration error when %s is blank", async (blank, set) => {
    process.env[blank] = " ";
    process.env[set] = set === "FINRAG_API_URL" ? API_URL : API_TOKEN;

    await expect(
      forwardToFinrag(new Request("http://localhost/api/health"), "/health"),
    ).rejects.toThrow("finrag backend is not configured");
  });

  test("uses a 295 second abort signal", async () => {
    configureBackend();
    const signal = new AbortController().signal;
    const timeout = vi.spyOn(AbortSignal, "timeout").mockReturnValue(signal);
    const upstream = vi.fn().mockResolvedValue(successfulUpstream());
    vi.stubGlobal("fetch", upstream);

    await forwardToFinrag(
      new Request("http://localhost/api/health"),
      "/health",
    );

    expect(timeout).toHaveBeenCalledWith(295_000);
    expect(upstream.mock.calls[0][1].signal).toBe(signal);
  });

  test("returns a stable redacted 502 and logs no request data on fetch failure", async () => {
    configureBackend();
    const privateBody = "private-question";
    const privateKey = "request-private";
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error(privateBody)));
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    const response = await forwardToFinrag(
      new Request("http://localhost/api/agent", {
        method: "POST",
        headers: { "Idempotency-Key": privateKey },
        body: privateBody,
      }),
      "/agent",
    );

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toEqual({
      code: "backend_unavailable",
      error: "backend unavailable",
    });
    const logged = JSON.stringify(consoleError.mock.calls);
    expect(logged).not.toContain(privateBody);
    expect(logged).not.toContain(privateKey);
    expect(logged).not.toContain(API_TOKEN);
    expect(consoleError).toHaveBeenCalledWith("finrag upstream request failed");
  });

  test("forwards a valid ingest idempotency key unchanged", async () => {
    configureBackend();
    const upstream = vi.fn().mockResolvedValue(successfulUpstream());
    vi.stubGlobal("fetch", upstream);

    await forwardToFinrag(
      new Request("http://localhost/api/ingest", {
        method: "POST",
        headers: { "Idempotency-Key": VALID_KEY },
        body: "{}",
      }),
      "/ingest",
    );

    expect(upstream.mock.calls[0][1].headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${API_TOKEN}`,
      "Content-Type": "application/json",
      "Idempotency-Key": VALID_KEY,
    });
  });

  test("rejects a missing ingest idempotency key without fetching", async () => {
    configureBackend();
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);

    const response = await forwardToFinrag(
      new Request("http://localhost/api/ingest", {
        method: "POST",
        body: "{}",
      }),
      "/ingest",
    );

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      code: "missing_idempotency_key",
      error: "missing Idempotency-Key",
    });
    expect(upstream).not.toHaveBeenCalled();
  });

  test.each([
    "short",
    "-starts-wrong",
    "contains space",
    "a".repeat(129),
    "request/slash",
  ])("rejects invalid ingest idempotency key %s", async (key) => {
    configureBackend();
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);

    const response = await forwardToFinrag(
      new Request("http://localhost/api/ingest", {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: "{}",
      }),
      "/ingest",
    );

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      code: "invalid_idempotency_key",
      error: "invalid Idempotency-Key",
    });
    expect(upstream).not.toHaveBeenCalled();
  });

  test.each([
    ["POST", "/ask"],
    ["POST", "/agent"],
    ["GET", "/health"],
    ["GET", "/ingest/job-123"],
  ])("drops idempotency keys for %s %s", async (method, path) => {
    configureBackend();
    const upstream = vi.fn().mockResolvedValue(successfulUpstream());
    vi.stubGlobal("fetch", upstream);

    await forwardToFinrag(
      new Request(`http://localhost/api${path}`, {
        method,
        headers: { "Idempotency-Key": VALID_KEY },
        body: method === "POST" ? "{}" : undefined,
      }),
      path,
    );

    expect(upstream.mock.calls[0][1].headers).not.toHaveProperty(
      "Idempotency-Key",
    );
  });
});
