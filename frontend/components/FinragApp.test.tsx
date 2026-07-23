import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import type { AgentAnswer, RagAnswer } from "@/lib/types";
import { FinragApp } from "./FinragApp";

const encoder = new TextEncoder();

const ragAnswer: RagAnswer = {
  text: "Net sales were $391 billion.",
  citations: [
    { chunk_id: 7, quote: "Net sales $391,035 million.", verified: true },
  ],
  usage: { input_tokens: 100, output_tokens: 20, calls: 1 },
  cost_usd: 0.001,
  cost_estimated: true,
  latency_ms: 1200,
  trace_url: null,
};

const agentAnswer: AgentAnswer = {
  answer: "R&D intensity increased.",
  steps: [
    {
      thought: "Compare the two ratios.",
      action: "calculator",
      action_input: { expression: "8.2 - 7.8" },
      observation: "0.4",
    },
  ],
  tools_used: ["calculator"],
  stopped: "final_answer",
  usage: { input_tokens: 200, output_tokens: 40, calls: 2 },
  cost_usd: 0.002,
  cost_estimated: true,
  latency_ms: 1800,
  trace_url: null,
};

function healthResponse(): Response {
  return Response.json({ status: "ok", tracing: true });
}

function sseResponse(events: Array<[string, unknown]>): Response {
  const body = events
    .map(
      ([event, data]) =>
        `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`,
    )
    .join("");
  return new Response(body, {
    headers: { "content-type": "text/event-stream" },
  });
}

function mockFetch(
  handler: (url: string, init?: RequestInit) => Response | Promise<Response>,
) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation((input, init) =>
      handler(typeof input === "string" ? input : input.toString(), init),
    );
}

beforeEach(() => {
  mockFetch((url) => {
    if (url === "/api/health") {
      return healthResponse();
    }
    throw new Error(`Unexpected request: ${url}`);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("FinragApp", () => {
  test("defaults to English RAG mode with scope controls", async () => {
    render(<FinragApp />);

    expect(
      screen.getByRole("heading", { name: /finrag/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "RAG" })).toBeChecked();
    expect(screen.getByRole("heading", { name: "Scope" })).toBeInTheDocument();
    expect(screen.getByLabelText("Ticker")).toHaveValue("AAPL");
    expect(screen.getByLabelText("Fiscal year")).toHaveValue(2024);
    await screen.findByText(/Health: ok/);
  });

  test("switching to Agent hides scope and replaces the example question", () => {
    render(<FinragApp />);

    fireEvent.click(screen.getByRole("radio", { name: "Agent" }));

    expect(screen.queryByRole("heading", { name: "Scope" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Ticker")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Question")).toHaveValue(
      "How did Apple's R&D-to-revenue ratio change from FY2023 to FY2024?",
    );
  });

  test("switching language changes labels without rewriting the question", () => {
    render(<FinragApp />);
    const question = screen.getByLabelText("Question");
    fireEvent.change(question, { target: { value: "My unchanged question?" } });

    fireEvent.change(screen.getByLabelText("Language"), {
      target: { value: "zh" },
    });

    expect(screen.getByLabelText("问题")).toHaveValue("My unchanged question?");
    expect(screen.getByRole("button", { name: "提问" })).toBeInTheDocument();
  });

  test("rejects a blank question without making an ask request", async () => {
    const fetchMock = vi.mocked(fetch);
    render(<FinragApp />);
    fireEvent.change(screen.getByLabelText("Question"), {
      target: { value: "   " },
    });

    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Enter a question.");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/health",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  test("streams RAG status, answer, and done events", async () => {
    let streamController: ReadableStreamDefaultController<Uint8Array>;
    mockFetch((url) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      if (url === "/api/ask") {
        return new Response(
          new ReadableStream({
            start(controller) {
              streamController = controller;
            },
          }),
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<FinragApp />);

    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    act(() => {
      streamController!.enqueue(
        encoder.encode('event: status\ndata: {"stage":"processing"}\n\n'),
      );
    });
    expect(await screen.findByText("Processing…")).toBeInTheDocument();

    act(() => {
      streamController!.enqueue(
        encoder.encode(
          `event: answer\ndata: ${JSON.stringify(ragAnswer)}\n\nevent: done\ndata: {}\n\n`,
        ),
      );
      streamController!.close();
    });

    expect(await screen.findByText(ragAnswer.text)).toBeInTheDocument();
    expect(screen.getByText("Complete")).toBeInTheDocument();
  });

  test("uppercases ticker and omits year when its filter is off", async () => {
    let askInit: RequestInit | undefined;
    mockFetch((url, init) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      askInit = init;
      return sseResponse([
        ["answer", ragAnswer],
        ["done", {}],
      ]);
    });
    render(<FinragApp />);
    fireEvent.change(screen.getByLabelText("Ticker"), {
      target: { value: " msft " },
    });
    fireEvent.click(screen.getByLabelText("Filter by year"));

    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText(ragAnswer.text);

    expect(JSON.parse(String(askInit?.body))).toEqual({
      question: "What was Apple's total net sales in fiscal 2024?",
      ticker: "MSFT",
      top_k: 5,
    });
  });

  test("clears the old result and disables Ask while a new request is pending", async () => {
    let requestCount = 0;
    let secondController: ReadableStreamDefaultController<Uint8Array>;
    mockFetch((url) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      requestCount += 1;
      if (requestCount === 1) {
        return sseResponse([
          ["answer", ragAnswer],
          ["done", {}],
        ]);
      }
      return new Response(
        new ReadableStream({
          start(controller) {
            secondController = controller;
          },
        }),
      );
    });
    render(<FinragApp />);
    const askButton = screen.getByRole("button", { name: "Ask" });
    fireEvent.click(askButton);
    await screen.findByText(ragAnswer.text);

    fireEvent.click(askButton);

    expect(screen.queryByText(ragAnswer.text)).not.toBeInTheDocument();
    expect(askButton).toBeDisabled();
    act(() => {
      secondController!.enqueue(
        encoder.encode(
          `event: answer\ndata: ${JSON.stringify(ragAnswer)}\n\nevent: done\ndata: {}\n\n`,
        ),
      );
      secondController!.close();
    });
    await waitFor(() => expect(askButton).not.toBeDisabled());
  });

  test("posts Agent questions and renders its JSON result", async () => {
    let agentInit: RequestInit | undefined;
    mockFetch((url, init) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      if (url === "/api/agent") {
        agentInit = init;
        return Response.json(agentAnswer);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<FinragApp />);
    fireEvent.click(screen.getByRole("radio", { name: "Agent" }));

    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(agentAnswer.answer)).toBeInTheDocument();
    expect(JSON.parse(String(agentInit?.body))).toEqual({
      question:
        "How did Apple's R&D-to-revenue ratio change from FY2023 to FY2024?",
    });
    const tools = screen.getByRole("heading", { name: "Tools used" })
      .parentElement;
    expect(tools).not.toBeNull();
    expect(within(tools!).getByText("calculator")).toBeInTheDocument();
    expect(screen.getByText(/Step 1/).closest("details")).not.toBeNull();
  });

  test.each([
    {
      name: "HTTP error",
      response: new Response(JSON.stringify({ detail: "<b>Unavailable</b>" }), {
        status: 503,
      }),
      expected: "<b>Unavailable</b>",
    },
    {
      name: "SSE error",
      response: sseResponse([
        ["error", { error: "<img src=x onerror=alert(1)>" }],
      ]),
      expected: "<img src=x onerror=alert(1)>",
    },
    {
      name: "stream without answer",
      response: sseResponse([
        ["mystery", { ignored: true }],
        ["done", {}],
      ]),
      expected: "The server returned an invalid response.",
    },
    {
      name: "invalid SSE JSON",
      response: new Response("event: answer\ndata: not-json\n\n"),
      expected: "The server returned an invalid response.",
    },
    {
      name: "missing response body",
      response: new Response(null),
      expected: "The server returned an invalid response.",
    },
  ])("shows a safe message for $name", async ({ response, expected }) => {
    mockFetch((url) => (url === "/api/health" ? healthResponse() : response));
    const { container } = render(<FinragApp />);

    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(expected);
    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect(container.querySelector("b")).not.toBeInTheDocument();
  });

  test("handles invalid Agent JSON without crashing", async () => {
    mockFetch((url) =>
      url === "/api/health"
        ? healthResponse()
        : new Response("not-json", {
            headers: { "content-type": "application/json" },
          }),
    );
    render(<FinragApp />);
    fireEvent.click(screen.getByRole("radio", { name: "Agent" }));

    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The server returned an invalid response.",
    );
  });

  test("loads health only once and aborts it on unmount", async () => {
    let healthSignal: AbortSignal | undefined;
    const fetchMock = mockFetch((url, init) => {
      if (url !== "/api/health") {
        throw new Error(`Unexpected request: ${url}`);
      }
      healthSignal = init?.signal ?? undefined;
      return new Promise<Response>(() => {});
    });
    const { rerender, unmount } = render(<FinragApp />);
    rerender(<FinragApp />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(healthSignal?.aborted).toBe(false);
    unmount();
    expect(healthSignal?.aborted).toBe(true);
  });
});
