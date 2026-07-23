import { describe, expect, test } from "vitest";

import { parseSse } from "./sse";

function streamFromChunks(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(chunk);
      }
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>) {
  return Array.fromAsync(parseSse(stream));
}

describe("parseSse", () => {
  test("parses status, answer, and done when JSON spans transport chunks", async () => {
    const encoder = new TextEncoder();
    const events = await collect(
      streamFromChunks([
        encoder.encode('event: status\ndata: {"stage":"processing"}\n\n'),
        encoder.encode('event: answer\ndata: {"text":"$391'),
        encoder.encode('B","citations":[]}\n\nevent: done\ndata: {}\n\n'),
      ]),
    );

    expect(events.map((event) => event.event)).toEqual([
      "status",
      "answer",
      "done",
    ]);
    expect(JSON.parse(events[1].data).text).toBe("$391B");
  });

  test("accepts CRLF, standalone CR, and a CRLF pair split across chunks", async () => {
    const encoder = new TextEncoder();
    const events = await collect(
      streamFromChunks([
        encoder.encode("event: first\rdata: one\r\r"),
        encoder.encode("event: second\r"),
        encoder.encode("\ndata: two\r"),
        encoder.encode("\r"),
        encoder.encode("\nevent: third\ndata: three\n\n"),
      ]),
    );

    expect(events).toEqual([
      { event: "first", data: "one" },
      { event: "second", data: "two" },
      { event: "third", data: "three" },
    ]);
  });

  test("decodes a Unicode code point split across byte chunks", async () => {
    const encoded = new TextEncoder().encode("event: answer\ndata: 收入增长📈\n\n");
    const emojiStart = encoded.findIndex((byte) => byte === 0xf0);
    const events = await collect(
      streamFromChunks([
        encoded.slice(0, emojiStart + 2),
        encoded.slice(emojiStart + 2),
      ]),
    );

    expect(events).toEqual([{ event: "answer", data: "收入增长📈" }]);
  });

  test("ignores heartbeat comments and comment-only events", async () => {
    const encoder = new TextEncoder();
    const events = await collect(
      streamFromChunks([
        encoder.encode(
          ": ping\n\n: keepalive\nevent: answer\ndata: ok\n\n: trailing",
        ),
      ]),
    );

    expect(events).toEqual([{ event: "answer", data: "ok" }]);
  });

  test("joins multi-line data and removes at most one leading space", async () => {
    const encoder = new TextEncoder();
    const events = await collect(
      streamFromChunks([
        encoder.encode("data:first\ndata: second\ndata:  third\n\n"),
      ]),
    );

    expect(events).toEqual([
      { event: "message", data: "first\nsecond\n third" },
    ]);
  });

  test("flushes a final data event without a trailing blank line", async () => {
    const encoder = new TextEncoder();
    const events = await collect(
      streamFromChunks([encoder.encode("event: error\ndata: transport failed")]),
    );

    expect(events).toEqual([
      { event: "error", data: "transport failed" },
    ]);
  });

  test("ends normally without inventing an answer when the stream closes early", async () => {
    const encoder = new TextEncoder();
    const events = await collect(
      streamFromChunks([
        encoder.encode('event: status\ndata: {"stage":"processing"}\n\n'),
      ]),
    );

    expect(events).toEqual([
      { event: "status", data: '{"stage":"processing"}' },
    ]);
    expect(events.some((event) => event.event === "answer")).toBe(false);
  });

  test("cancels and unlocks the stream when a consumer stops early", async () => {
    const encoder = new TextEncoder();
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode("data: first\n\ndata: second\n\n"));
      },
      cancel() {
        cancelled = true;
      },
    });

    for await (const event of parseSse(stream)) {
      expect(event.data).toBe("first");
      break;
    }

    expect(cancelled).toBe(true);
    expect(stream.locked).toBe(false);
  });

  test("releases the reader lock when the source stream errors", async () => {
    const failure = new Error("socket closed");
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.error(failure);
      },
    });

    await expect(collect(stream)).rejects.toThrow("socket closed");
    expect(stream.locked).toBe(false);
  });
});
