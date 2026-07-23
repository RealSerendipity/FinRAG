import { beforeEach, expect, test, vi } from "vitest";

const { forwardToFinrag } = vi.hoisted(() => ({
  forwardToFinrag: vi.fn().mockResolvedValue(new Response("ok")),
}));

vi.mock("@/lib/server/finrag", () => ({ forwardToFinrag }));

import {
  dynamic as agentDynamic,
  maxDuration as agentMaxDuration,
  POST as agentPost,
} from "./agent/route";
import {
  dynamic as askDynamic,
  maxDuration as askMaxDuration,
  POST as askPost,
} from "./ask/route";
import {
  dynamic as healthDynamic,
  GET as healthGet,
  maxDuration as healthMaxDuration,
} from "./health/route";
import {
  dynamic as statusDynamic,
  GET as statusGet,
  maxDuration as statusMaxDuration,
} from "./ingest/[jobId]/route";
import {
  dynamic as ingestDynamic,
  maxDuration as ingestMaxDuration,
  POST as ingestPost,
} from "./ingest/route";

beforeEach(() => {
  forwardToFinrag.mockClear();
});

test("all fixed route handlers use Vercel's long dynamic function settings", () => {
  expect([
    agentMaxDuration,
    askMaxDuration,
    healthMaxDuration,
    ingestMaxDuration,
    statusMaxDuration,
  ]).toEqual([300, 300, 300, 300, 300]);
  expect([
    agentDynamic,
    askDynamic,
    healthDynamic,
    ingestDynamic,
    statusDynamic,
  ]).toEqual([
    "force-dynamic",
    "force-dynamic",
    "force-dynamic",
    "force-dynamic",
    "force-dynamic",
  ]);
});

test.each([
  ["ask", askPost, "/ask"],
  ["agent", agentPost, "/agent"],
] as const)(
  "%s POST forwards its request to its fixed upstream path",
  async (_, handler, path) => {
    const request = new Request(`http://localhost/api${path}`, {
      method: "POST",
      headers: { "Idempotency-Key": "request-123" },
      body: "{}",
    });

    await handler(request);

    expect(forwardToFinrag).toHaveBeenCalledWith(request, path);
  },
);

test("health GET forwards its request to the fixed health path", async () => {
  const request = new Request("http://localhost/api/health", {
    headers: { "Idempotency-Key": "request-123" },
  });

  await healthGet(request);

  expect(forwardToFinrag).toHaveBeenCalledWith(request, "/health");
});

test("ingest POST preserves the request carrying the idempotency key", async () => {
  const request = new Request("http://localhost/api/ingest", {
    method: "POST",
    headers: { "Idempotency-Key": "request-123" },
    body: "{}",
  });

  await ingestPost(request);

  expect(request.headers.get("Idempotency-Key")).toBe("request-123");
  expect(forwardToFinrag).toHaveBeenCalledWith(request, "/ingest");
});

test("status GET resolves Next 16 async params and forwards a validated id", async () => {
  const request = new Request("http://localhost/api/ingest/job-123", {
    headers: { "Idempotency-Key": "request-123" },
  });

  await statusGet(request, { params: Promise.resolve({ jobId: "job-123" }) });

  expect(forwardToFinrag).toHaveBeenCalledWith(request, "/ingest/job-123");
});

test.each([
  "",
  "../health",
  "job/other",
  "job%2Fother",
  "job?admin=true",
  "a".repeat(65),
])("status GET rejects unsafe job id %s without forwarding", async (jobId) => {
  const response = await statusGet(
    new Request("http://localhost/api/ingest/status"),
    { params: Promise.resolve({ jobId }) },
  );

  expect(response.status).toBe(400);
  await expect(response.json()).resolves.toEqual({
    code: "invalid_job_id",
    error: "invalid job id",
  });
  expect(forwardToFinrag).not.toHaveBeenCalled();
});
