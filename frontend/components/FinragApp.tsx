"use client";

import { useEffect, useRef, useState } from "react";

import { copy, defaultLocale, type Locale } from "@/lib/i18n";
import { parseSse } from "@/lib/sse";
import type {
  AgentAnswer,
  AgentRequest,
  HealthStatus,
  RagAnswer,
  RagRequest,
} from "@/lib/types";
import { AgentResult } from "./AgentResult";
import { ModeSidebar, type FinragMode } from "./ModeSidebar";
import { QuestionPanel } from "./QuestionPanel";
import { RagResult } from "./RagResult";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasUsage(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.input_tokens === "number" &&
    typeof value.output_tokens === "number" &&
    typeof value.calls === "number"
  );
}

function isRagAnswer(value: unknown): value is RagAnswer {
  return (
    isRecord(value) &&
    typeof value.text === "string" &&
    Array.isArray(value.citations) &&
    value.citations.every(
      (citation) =>
        isRecord(citation) &&
        typeof citation.chunk_id === "number" &&
        typeof citation.quote === "string" &&
        typeof citation.verified === "boolean",
    ) &&
    hasUsage(value.usage) &&
    typeof value.cost_usd === "number" &&
    typeof value.cost_estimated === "boolean" &&
    typeof value.latency_ms === "number" &&
    (typeof value.trace_url === "string" || value.trace_url === null)
  );
}

function isAgentAnswer(value: unknown): value is AgentAnswer {
  const stopped = isRecord(value) ? value.stopped : null;
  return (
    isRecord(value) &&
    typeof value.answer === "string" &&
    Array.isArray(value.tools_used) &&
    value.tools_used.every((tool) => typeof tool === "string") &&
    Array.isArray(value.steps) &&
    value.steps.every(
      (step) =>
        isRecord(step) &&
        typeof step.thought === "string" &&
        (typeof step.action === "string" || step.action === null) &&
        (isRecord(step.action_input) || step.action_input === null) &&
        (typeof step.observation === "string" || step.observation === null),
    ) &&
    (stopped === "final_answer" ||
      stopped === "max_steps" ||
      stopped === "blocked" ||
      stopped === "blocked_output") &&
    hasUsage(value.usage) &&
    typeof value.cost_usd === "number" &&
    typeof value.cost_estimated === "boolean" &&
    typeof value.latency_ms === "number" &&
    (typeof value.trace_url === "string" || value.trace_url === null)
  );
}

function errorFromPayload(value: unknown): string | null {
  if (!isRecord(value)) {
    return null;
  }
  if (typeof value.error === "string") {
    return value.error;
  }
  if (typeof value.detail === "string") {
    return value.detail;
  }
  if (isRecord(value.detail) && typeof value.detail.error === "string") {
    return value.detail.error;
  }
  if (Array.isArray(value.detail)) {
    const messages = value.detail
      .filter(isRecord)
      .map((detail) => detail.msg)
      .filter((message): message is string => typeof message === "string");
    return messages.length > 0 ? messages.join("; ") : null;
  }
  return null;
}

async function responseError(
  response: Response,
  locale: Locale,
): Promise<string> {
  const t = copy[locale];
  try {
    const text = await response.text();
    if (text) {
      const message = errorFromPayload(JSON.parse(text));
      if (message) {
        return message;
      }
    }
  } catch {
    // Fall through to a stable localized message for malformed error bodies.
  }
  if (response.status === 401 || response.status === 403) {
    return t.backendUnauthorized;
  }
  if (response.status >= 500) {
    return t.backendUnavailable;
  }
  return t.backendUnknownError;
}

/** Coordinate all public RAG and Agent network and presentation state. */
export function FinragApp() {
  const [locale, setLocale] = useState<Locale>(defaultLocale);
  const [mode, setMode] = useState<FinragMode>("rag");
  const [ticker, setTicker] = useState("AAPL");
  const [year, setYear] = useState(2024);
  const [useYear, setUseYear] = useState(true);
  const [topK, setTopK] = useState(5);
  const [question, setQuestion] = useState(copy[defaultLocale].questionExampleRag);
  const [pending, setPending] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [ragResult, setRagResult] = useState<RagAnswer | null>(null);
  const [agentResult, setAgentResult] = useState<AgentAnswer | null>(null);
  const requestController = useRef<AbortController | null>(null);
  const t = copy[locale];

  useEffect(() => {
    const controller = new AbortController();

    async function loadHealth() {
      try {
        const response = await fetch("/api/health", {
          signal: controller.signal,
        });
        if (!response.ok) {
          return;
        }
        const data: unknown = await response.json();
        if (
          isRecord(data) &&
          typeof data.status === "string" &&
          typeof data.tracing === "boolean" &&
          !controller.signal.aborted
        ) {
          setHealth({ status: data.status, tracing: data.tracing });
        }
      } catch {
        // Health is advisory; the sidebar keeps its unreachable fallback.
      }
    }

    void loadHealth();
    return () => controller.abort();
  }, []);

  useEffect(
    () => () => {
      requestController.current?.abort();
    },
    [],
  );

  function changeMode(nextMode: FinragMode) {
    if (nextMode === mode) {
      return;
    }
    const currentExample =
      mode === "rag" ? t.questionExampleRag : t.questionExampleAgent;
    const nextExample =
      nextMode === "rag" ? t.questionExampleRag : t.questionExampleAgent;
    if (question === currentExample) {
      setQuestion(nextExample);
    }
    setMode(nextMode);
    setError(null);
    setStatusText(null);
  }

  async function runRag(controller: AbortController, trimmed: string) {
    const payload: RagRequest = { question: trimmed, top_k: topK };
    const normalizedTicker = ticker.trim().toUpperCase();
    if (normalizedTicker) {
      payload.ticker = normalizedTicker;
    }
    if (useYear) {
      payload.year = year;
    }

    const response = await fetch("/api/ask", {
      method: "POST",
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(await responseError(response, locale));
    }
    if (!response.body) {
      throw new Error(t.validationInvalidResponse);
    }

    let answer: RagAnswer | null = null;
    for await (const event of parseSse(response.body)) {
      if (controller.signal.aborted) {
        return;
      }
      if (event.event === "status") {
        setStatusText(t.statusProcessing);
      } else if (event.event === "answer") {
        let parsed: unknown;
        try {
          parsed = JSON.parse(event.data);
        } catch {
          throw new Error(t.validationInvalidResponse);
        }
        if (!isRagAnswer(parsed)) {
          throw new Error(t.validationInvalidResponse);
        }
        answer = parsed;
        setRagResult(parsed);
      } else if (event.event === "error") {
        let parsed: unknown;
        try {
          parsed = JSON.parse(event.data);
        } catch {
          throw new Error(t.validationInvalidResponse);
        }
        throw new Error(errorFromPayload(parsed) ?? t.backendUnknownError);
      } else if (event.event === "done" && answer) {
        setStatusText(t.statusComplete);
      }
    }
    if (!answer) {
      throw new Error(t.validationInvalidResponse);
    }
  }

  async function runAgent(controller: AbortController, trimmed: string) {
    const payload: AgentRequest = { question: trimmed };
    const response = await fetch("/api/agent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(await responseError(response, locale));
    }

    let parsed: unknown;
    try {
      parsed = await response.json();
    } catch {
      throw new Error(t.validationInvalidResponse);
    }
    if (!isAgentAnswer(parsed)) {
      throw new Error(t.validationInvalidResponse);
    }
    if (!controller.signal.aborted) {
      setAgentResult(parsed);
      setStatusText(t.statusComplete);
    }
  }

  async function submitQuestion() {
    const trimmed = question.trim();
    if (!trimmed) {
      setError(t.validationQuestionRequired);
      return;
    }
    if (mode === "rag" && useYear && (!Number.isInteger(year) || year < 1994 || year > 2030)) {
      setError(t.validationYearRange);
      return;
    }

    requestController.current?.abort();
    const controller = new AbortController();
    requestController.current = controller;
    setPending(true);
    setError(null);
    setRagResult(null);
    setAgentResult(null);
    setStatusText(mode === "rag" ? t.pendingRag : t.pendingAgent);

    try {
      if (mode === "rag") {
        await runRag(controller, trimmed);
      } else {
        await runAgent(controller, trimmed);
      }
    } catch (caught) {
      if (!controller.signal.aborted) {
        setError(
          caught instanceof Error && caught.message
            ? caught.message
            : t.networkRequestFailed,
        );
        setStatusText(null);
      }
    } finally {
      if (
        requestController.current === controller &&
        !controller.signal.aborted
      ) {
        setPending(false);
      }
    }
  }

  return (
    <main className="finrag-app">
      <ModeSidebar
        locale={locale}
        mode={mode}
        ticker={ticker}
        year={year}
        useYear={useYear}
        topK={topK}
        health={health}
        onLocaleChange={setLocale}
        onModeChange={changeMode}
        onTickerChange={setTicker}
        onYearChange={setYear}
        onUseYearChange={setUseYear}
        onTopKChange={setTopK}
      />
      <div className="finrag-content">
        <header>
          <h1>📑 {t.appTitle}</h1>
          <p>{t.appTagline}</p>
        </header>
        <QuestionPanel
          label={t.questionLabel}
          askLabel={t.askButton}
          question={question}
          pending={pending}
          statusText={statusText}
          onQuestionChange={setQuestion}
          onSubmit={() => void submitQuestion()}
        />
        {error ? <p role="alert">{error}</p> : null}
        {ragResult ? <RagResult locale={locale} result={ragResult} /> : null}
        {agentResult ? (
          <AgentResult locale={locale} result={agentResult} />
        ) : null}
      </div>
    </main>
  );
}
