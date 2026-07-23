import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { StrictMode } from "react";
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

function desktopSettings() {
  return within(screen.getByTestId("desktop-settings"));
}

function ingestPanel() {
  const panel = screen.getByTestId("ingest-panel") as HTMLDetailsElement;
  const summary = panel.querySelector("summary");
  if (!panel.open && summary) {
    fireEvent.click(summary);
  }
  return within(panel);
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
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("FinragApp", () => {
  test("defaults to English RAG mode with scope controls", async () => {
    render(<FinragApp />);
    const settings = desktopSettings();

    expect(
      screen.getByRole("heading", { name: /finrag/ }),
    ).toBeInTheDocument();
    expect(settings.getByRole("radio", { name: "RAG" })).toBeChecked();
    expect(settings.getByRole("heading", { name: "Scope" })).toBeInTheDocument();
    expect(settings.getByLabelText("Ticker")).toHaveValue("AAPL");
    expect(settings.getByLabelText("Fiscal year")).toHaveValue(2024);
    await waitFor(() =>
      expect(settings.getByText(/Health: ok/)).toBeInTheDocument(),
    );
  });

  test("renders separately named desktop and mobile settings without duplicate ids", () => {
    const { container } = render(<FinragApp />);
    const desktop = screen.getByTestId("desktop-settings");
    const mobile = screen.getByTestId("mobile-settings");
    const ids = Array.from(container.querySelectorAll("[id]")).map(
      (element) => element.id,
    );

    expect(new Set(ids).size).toBe(ids.length);
    expect(
      within(desktop).getByRole("radiogroup", { name: "Mode" }),
    ).toBeInTheDocument();
    expect(
      within(mobile).getByRole("radiogroup", { name: "Mode" }),
    ).toBeInTheDocument();
    expect(
      within(desktop).getByRole("button", {
        name: "Language: English. Switch to 中文",
      }),
    ).toBeInTheDocument();
    expect(
      within(mobile).getByRole("button", {
        name: "Language: English. Switch to 中文",
      }),
    ).toBeInTheDocument();
    expect(desktop.querySelector('input[type="radio"]')).toHaveAttribute(
      "name",
      "desktop-mode",
    );
    expect(mobile.querySelector('input[type="radio"]')).toHaveAttribute(
      "name",
      "mobile-mode",
    );
    expect(mobile.tagName).toBe("DETAILS");
  });

  test("gives every form control an accessible name", () => {
    const { container } = render(<FinragApp />);
    const controls = Array.from(
      container.querySelectorAll("input, select, textarea"),
    );

    expect(controls.length).toBeGreaterThan(0);
    for (const control of controls) {
      expect(control).toHaveAccessibleName();
    }
  });

  test("switching to Agent hides scope and replaces the example question", () => {
    render(<FinragApp />);
    const settings = desktopSettings();

    fireEvent.click(settings.getByRole("radio", { name: "Agent" }));

    expect(settings.queryByRole("heading", { name: "Scope" })).not.toBeInTheDocument();
    expect(settings.queryByLabelText("Ticker")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Question")).toHaveValue(
      "How did Apple's R&D-to-revenue ratio change from FY2023 to FY2024?",
    );
  });

  test("switching language changes labels without rewriting the question", () => {
    render(<FinragApp />);
    const question = screen.getByLabelText("Question");
    fireEvent.change(question, { target: { value: "My unchanged question?" } });

    fireEvent.click(
      desktopSettings().getByRole("button", {
        name: "Language: English. Switch to 中文",
      }),
    );

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
    expect(screen.getByRole("alert")).toHaveAttribute(
      "aria-live",
      "assertive",
    );
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
    const status = await screen.findByText("Processing…");
    expect(status).toHaveAttribute("role", "status");
    expect(status).toHaveAttribute("aria-live", "polite");

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
    fireEvent.change(desktopSettings().getByLabelText("Ticker"), {
      target: { value: " msft " },
    });
    fireEvent.click(desktopSettings().getByLabelText("Filter by year"));

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

  test("aborts an old RAG request when mode changes and ignores its late result", async () => {
    let ragController: ReadableStreamDefaultController<Uint8Array>;
    let ragSignal: AbortSignal | undefined;
    mockFetch((url, init) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      ragSignal = init?.signal ?? undefined;
      return new Response(
        new ReadableStream({
          start(controller) {
            ragController = controller;
          },
        }),
      );
    });
    render(<FinragApp />);
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();

    fireEvent.click(desktopSettings().getByRole("radio", { name: "Agent" }));

    expect(ragSignal?.aborted).toBe(true);
    expect(screen.getByRole("button", { name: "Ask" })).not.toBeDisabled();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    act(() => {
      ragController!.enqueue(
        encoder.encode(
          `event: answer\ndata: ${JSON.stringify(ragAnswer)}\n\nevent: done\ndata: {}\n\n`,
        ),
      );
      ragController!.close();
    });
    await act(async () => {});
    expect(screen.queryByText(ragAnswer.text)).not.toBeInTheDocument();
    expect(screen.queryByText("Complete")).not.toBeInTheDocument();
  });

  test("requires a done event before committing a RAG answer", async () => {
    mockFetch((url) =>
      url === "/api/health"
        ? healthResponse()
        : sseResponse([["answer", ragAnswer]]),
    );
    render(<FinragApp />);

    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The server returned an invalid response.",
    );
    expect(screen.queryByText(ragAnswer.text)).not.toBeInTheDocument();
    expect(screen.queryByText("Complete")).not.toBeInTheDocument();
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
    fireEvent.click(desktopSettings().getByRole("radio", { name: "Agent" }));

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
    fireEvent.click(desktopSettings().getByRole("radio", { name: "Agent" }));

    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The server returned an invalid response.",
    );
  });

  test("disables locale changes while a request is pending", () => {
    mockFetch((url) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      return new Promise<Response>(() => {});
    });
    render(<FinragApp />);

    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(
      desktopSettings().getByRole("button", { name: /Language:/ }),
    ).toBeDisabled();
  });

  test("relocalizes completed local status without changing model text", async () => {
    mockFetch((url) =>
      url === "/api/health"
        ? healthResponse()
        : sseResponse([
            ["answer", ragAnswer],
            ["done", {}],
          ]),
    );
    render(<FinragApp />);
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Complete")).toBeInTheDocument();
    expect(screen.getByText(ragAnswer.text)).toBeInTheDocument();

    fireEvent.click(
      desktopSettings().getByRole("button", {
        name: "Language: English. Switch to 中文",
      }),
    );

    expect(screen.getByText("已完成")).toBeInTheDocument();
    expect(screen.getByText(ragAnswer.text)).toBeInTheDocument();
  });

  test("relocalizes client validation errors after a locale change", () => {
    render(<FinragApp />);
    fireEvent.change(screen.getByLabelText("Question"), {
      target: { value: " " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a question.");

    fireEvent.click(
      desktopSettings().getByRole("button", {
        name: "Language: English. Switch to 中文",
      }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent("请输入问题。");
  });

  test("shares one health request across StrictMode effect replay", async () => {
    const fetchMock = mockFetch((url) => {
      if (url !== "/api/health") {
        throw new Error(`Unexpected request: ${url}`);
      }
      return healthResponse();
    });
    render(
      <StrictMode>
        <FinragApp />
      </StrictMode>,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(desktopSettings().getByText(/Health: ok/)).toBeInTheDocument(),
    );
  });

  test("aborts an active question request on unmount", async () => {
    let requestSignal: AbortSignal | undefined;
    mockFetch((url, init) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      requestSignal = init?.signal ?? undefined;
      return new Promise<Response>(() => {});
    });
    const { unmount } = render(<FinragApp />);
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(requestSignal?.aborted).toBe(false);

    unmount();
    expect(requestSignal?.aborted).toBe(true);
  });

  test("queues one filing with one idempotency key and polls to completion", async () => {
    vi.useFakeTimers();
    const randomUUID = vi
      .spyOn(globalThis.crypto, "randomUUID")
      .mockReturnValue("11111111-1111-4111-8111-111111111111");
    let pollCount = 0;
    const fetchMock = mockFetch((url) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      if (url === "/api/ingest") {
        return Response.json(
          { job_id: "job-1", status: "queued", poll: "/ingest/job-1" },
          { status: 202 },
        );
      }
      if (url === "/api/ingest/job-1") {
        pollCount += 1;
        return Response.json(
          pollCount === 1
            ? {
                job_id: "job-1",
                status: "running",
                items: [
                  {
                    id: "item-1",
                    ticker: "MSFT",
                    status: "running",
                    attempts: 1,
                  },
                ],
                results: [],
              }
            : {
                job_id: "job-1",
                status: "done",
                items: [
                  {
                    id: "item-1",
                    ticker: "MSFT",
                    status: "done",
                    attempts: 1,
                  },
                ],
                results: [
                  { ticker: "MSFT", chunks: 42, elapsed_s: 3.5 },
                ],
              },
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<FinragApp />);

    await act(async () => {
      fireEvent.click(ingestPanel().getByRole("button", { name: "Ingest filing" }));
    });
    expect(screen.getByText("Queued")).toBeInTheDocument();
    expect(randomUUID).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/ingest",
      expect.objectContaining({
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": "11111111-1111-4111-8111-111111111111",
        },
        body: JSON.stringify({
          tickers: ["MSFT"],
          form_type: "10-K",
          year: 2024,
        }),
      }),
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(screen.getByText("Running")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(screen.getByText(/42 chunks/)).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(pollCount).toBe(2);
  });

  test("retries an ambiguous submission with the same idempotency key", async () => {
    const randomUUID = vi
      .spyOn(globalThis.crypto, "randomUUID")
      .mockReturnValue("22222222-2222-4222-8222-222222222222");
    const keys: string[] = [];
    let submissions = 0;
    mockFetch((url, init) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      if (url === "/api/ingest") {
        submissions += 1;
        keys.push(new Headers(init?.headers).get("Idempotency-Key") ?? "");
        if (submissions === 1) {
          return Response.json(
            {
              detail: {
                code: "queue_unavailable",
                error: "Queue unavailable",
                retryable: true,
                job_id: "job-ambiguous",
              },
            },
            { status: 503 },
          );
        }
        return Response.json(
          {
            job_id: "job-ambiguous",
            status: "queued",
            poll: "/ingest/job-ambiguous",
          },
          { status: 202 },
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<FinragApp />);

    fireEvent.click(ingestPanel().getByRole("button", { name: "Ingest filing" }));
    expect(
      await screen.findByRole("button", { name: "Retry submission" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry submission" }));
    await waitFor(() => expect(submissions).toBe(2));

    expect(randomUUID).toHaveBeenCalledOnce();
    expect(keys).toEqual([
      "22222222-2222-4222-8222-222222222222",
      "22222222-2222-4222-8222-222222222222",
    ]);
  });

  test("continues after one poll failure and stops after three consecutive failures", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      "33333333-3333-4333-8333-333333333333",
    );
    let pollCount = 0;
    mockFetch((url) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      if (url === "/api/ingest") {
        return Response.json(
          { job_id: "job-3", status: "queued", poll: "/ingest/job-3" },
          { status: 202 },
        );
      }
      if (url === "/api/ingest/job-3") {
        pollCount += 1;
        return Promise.reject(new Error("offline"));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<FinragApp />);
    await act(async () => {
      fireEvent.click(ingestPanel().getByRole("button", { name: "Ingest filing" }));
    });
    expect(screen.getByText("Queued")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Unable to check ingest status.",
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Polling stopped after three consecutive network failures.",
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(pollCount).toBe(3);
  });

  test("aborts ingest polling on a new submission and on unmount", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis.crypto, "randomUUID")
      .mockReturnValueOnce("44444444-4444-4444-8444-444444444444")
      .mockReturnValueOnce("55555555-5555-4555-8555-555555555555");
    const signals: AbortSignal[] = [];
    mockFetch((url, init) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      if (url === "/api/ingest") {
        return Response.json(
          {
            job_id: `job-${signals.length + 1}`,
            status: "queued",
            poll: `/ingest/job-${signals.length + 1}`,
          },
          { status: 202 },
        );
      }
      if (url.startsWith("/api/ingest/job-")) {
        signals.push(init?.signal as AbortSignal);
        return new Promise<Response>(() => {});
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    const { unmount } = render(<FinragApp />);
    await act(async () => {
      fireEvent.click(ingestPanel().getByRole("button", { name: "Ingest filing" }));
    });
    expect(screen.getByText("Queued")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(signals[0]?.aborted).toBe(false);

    await act(async () => {
      fireEvent.click(ingestPanel().getByRole("button", { name: "Ingest filing" }));
    });
    expect(signals[0]?.aborted).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(signals[1]?.aborted).toBe(false);

    unmount();
    expect(signals[1]?.aborted).toBe(true);
  });

  test("shows a localized safe error for an invalid ingest response", async () => {
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      "66666666-6666-4666-8666-666666666666",
    );
    mockFetch((url) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      return Response.json({ job_id: 123 }, { status: 202 });
    });
    render(<FinragApp />);

    fireEvent.click(ingestPanel().getByRole("button", { name: "Ingest filing" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The server returned an invalid response.",
    );
  });

  test("retries transient poll HTTP responses and resets failures after success", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      "77777777-7777-4777-8777-777777777777",
    );
    const pollResponses = [
      new Response(null, { status: 502 }),
      new Response(null, { status: 503 }),
      Response.json({
        job_id: "job-transient",
        status: "running",
        items: [],
        results: [],
      }),
      new Response(null, { status: 502 }),
      new Response(null, { status: 503 }),
      Response.json({
        job_id: "job-transient",
        status: "done",
        items: [],
        results: [
          { ticker: "MSFT", chunks: 8, elapsed_s: 2 },
        ],
      }),
    ];
    let polls = 0;
    mockFetch((url) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      if (url === "/api/ingest") {
        return Response.json(
          {
            job_id: "job-transient",
            status: "queued",
            poll: "/ingest/job-transient",
          },
          { status: 202 },
        );
      }
      if (url === "/api/ingest/job-transient") {
        const response = pollResponses[polls];
        polls += 1;
        return response;
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<FinragApp />);
    await act(async () => {
      fireEvent.click(ingestPanel().getByRole("button", { name: "Ingest filing" }));
    });

    for (let index = 0; index < pollResponses.length; index += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });
    }

    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(polls).toBe(6);
    expect(
      screen.queryByRole("button", { name: "Retry status check" }),
    ).not.toBeInTheDocument();
  });

  test("resumes only GET polling after three failures", async () => {
    vi.useFakeTimers();
    const randomUUID = vi
      .spyOn(globalThis.crypto, "randomUUID")
      .mockReturnValue("88888888-8888-4888-8888-888888888888");
    let posts = 0;
    let polls = 0;
    mockFetch((url) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      if (url === "/api/ingest") {
        posts += 1;
        return Response.json(
          {
            job_id: "job-recover",
            status: "queued",
            poll: "/ingest/job-recover",
          },
          { status: 202 },
        );
      }
      if (url === "/api/ingest/job-recover") {
        polls += 1;
        if (polls <= 3) {
          return Promise.reject(new Error("offline"));
        }
        return Response.json({
          job_id: "job-recover",
          status: "done",
          items: [],
          results: [
            { ticker: "MSFT", chunks: 9, elapsed_s: 2.5 },
          ],
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<FinragApp />);
    await act(async () => {
      fireEvent.click(ingestPanel().getByRole("button", { name: "Ingest filing" }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });

    const retryPoll = screen.getByRole("button", {
      name: "Retry status check",
    });
    await act(async () => {
      fireEvent.click(retryPoll);
    });

    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(posts).toBe(1);
    expect(polls).toBe(4);
    expect(randomUUID).toHaveBeenCalledOnce();
  });

  test("rejects an unsafe submission job id without polling", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      "99999999-9999-4999-8999-999999999999",
    );
    const fetchMock = mockFetch((url) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      if (url === "/api/ingest") {
        return Response.json(
          { job_id: "../health", status: "queued", poll: "/ingest/../health" },
          { status: 202 },
        );
      }
      throw new Error(`Unsafe poll request: ${url}`);
    });
    render(<FinragApp />);
    await act(async () => {
      fireEvent.click(ingestPanel().getByRole("button", { name: "Ingest filing" }));
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The server returned an invalid response.",
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        String(input).startsWith("/api/ingest/"),
      ),
    ).toHaveLength(0);
  });

  test("rejects an unsafe job id in a retryable submission error", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    );
    const fetchMock = mockFetch((url) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      if (url === "/api/ingest") {
        return Response.json(
          {
            detail: {
              code: "queue_unavailable",
              error: "Queue unavailable",
              retryable: true,
              job_id: "../health",
            },
          },
          { status: 503 },
        );
      }
      throw new Error(`Unsafe poll request: ${url}`);
    });
    render(<FinragApp />);
    await act(async () => {
      fireEvent.click(ingestPanel().getByRole("button", { name: "Ingest filing" }));
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The server returned an invalid response.",
    );
    expect(
      screen.queryByRole("button", { name: "Retry submission" }),
    ).not.toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        String(input).startsWith("/api/ingest/"),
      ),
    ).toHaveLength(0);
  });

  test("rejects an unsafe job id returned by status polling", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    );
    let polls = 0;
    mockFetch((url) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      if (url === "/api/ingest") {
        return Response.json(
          { job_id: "job-safe", status: "queued", poll: "/ingest/job-safe" },
          { status: 202 },
        );
      }
      if (url === "/api/ingest/job-safe") {
        polls += 1;
        return Response.json({
          job_id: "../health",
          status: "running",
          items: [],
          results: [],
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<FinragApp />);
    await act(async () => {
      fireEvent.click(ingestPanel().getByRole("button", { name: "Ingest filing" }));
      await vi.advanceTimersByTimeAsync(5_000);
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The server returned an invalid response.",
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(polls).toBe(1);
  });

  test("hides submission retry after a deterministic retry response", async () => {
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    );
    let submissions = 0;
    mockFetch((url) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      if (url === "/api/ingest") {
        submissions += 1;
        if (submissions === 1) {
          return Response.json(
            {
              detail: {
                code: "queue_unavailable",
                error: "Queue unavailable",
                retryable: true,
              },
            },
            { status: 503 },
          );
        }
        return Response.json({ detail: "Invalid filing" }, { status: 400 });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<FinragApp />);
    fireEvent.click(ingestPanel().getByRole("button", { name: "Ingest filing" }));
    const retry = await screen.findByRole("button", {
      name: "Retry submission",
    });

    fireEvent.click(retry);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Invalid filing",
    );
    expect(
      screen.queryByRole("button", { name: "Retry submission" }),
    ).not.toBeInTheDocument();
  });

  test("StrictMode submits exactly once for one ingest click", async () => {
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    );
    let posts = 0;
    mockFetch((url) => {
      if (url === "/api/health") {
        return healthResponse();
      }
      if (url === "/api/ingest") {
        posts += 1;
        return Response.json(
          {
            job_id: "job-strict",
            status: "queued",
            poll: "/ingest/job-strict",
          },
          { status: 202 },
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(
      <StrictMode>
        <FinragApp />
      </StrictMode>,
    );

    fireEvent.click(ingestPanel().getByRole("button", { name: "Ingest filing" }));

    await waitFor(() => expect(posts).toBe(1));
  });
});
