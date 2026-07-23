/** One decoded Server-Sent Event without application-level JSON parsing. */
export interface SseEvent {
  event: string;
  data: string;
}

type EventState = {
  event: string;
  data: string[];
};

function consumeLine(line: string, state: EventState): void {
  if (line.startsWith(":")) {
    return;
  }

  const colon = line.indexOf(":");
  const field = colon < 0 ? line : line.slice(0, colon);
  let value = colon < 0 ? "" : line.slice(colon + 1);
  if (value.startsWith(" ")) {
    value = value.slice(1);
  }

  if (field === "event") {
    state.event = value;
  } else if (field === "data") {
    state.data.push(value);
  }
}

function dispatch(state: EventState): SseEvent | null {
  const event =
    state.data.length > 0
      ? { event: state.event || "message", data: state.data.join("\n") }
      : null;
  state.event = "message";
  state.data = [];
  return event;
}

/**
 * Incrementally decode an SSE byte stream.
 *
 * The parser handles every SSE newline form and preserves data text, but leaves
 * JSON decoding and application-level event validation to its caller.
 */
export async function* parseSse(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<SseEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  const state: EventState = { event: "message", data: [] };
  let buffer = "";
  let completed = false;

  function processBuffer(flush: boolean): SseEvent[] {
    const events: SseEvent[] = [];
    let offset = 0;

    while (offset < buffer.length) {
      let lineEnd = offset;
      while (
        lineEnd < buffer.length &&
        buffer[lineEnd] !== "\r" &&
        buffer[lineEnd] !== "\n"
      ) {
        lineEnd += 1;
      }

      if (lineEnd === buffer.length) {
        break;
      }
      if (
        buffer[lineEnd] === "\r" &&
        lineEnd + 1 === buffer.length &&
        !flush
      ) {
        break;
      }

      const line = buffer.slice(offset, lineEnd);
      const newlineLength =
        buffer[lineEnd] === "\r" && buffer[lineEnd + 1] === "\n" ? 2 : 1;
      offset = lineEnd + newlineLength;

      if (line === "") {
        const event = dispatch(state);
        if (event) {
          events.push(event);
        }
      } else {
        consumeLine(line, state);
      }
    }

    buffer = buffer.slice(offset);
    if (flush) {
      // The event stream format dispatches only on an empty line. At EOF,
      // discard any event that was not terminated by that delimiter.
      buffer = "";
    }
    return events;
  }

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        completed = true;
        for (const event of processBuffer(true)) {
          yield event;
        }
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      for (const event of processBuffer(false)) {
        yield event;
      }
    }
  } finally {
    if (!completed) {
      try {
        await reader.cancel();
      } catch {
        // The original stream error remains the useful failure for the caller.
      }
    }
    reader.releaseLock();
  }
}
