"use client";

import { useEffect, useRef, useState } from "react";

import { copy, defaultLocale, type Locale } from "@/lib/i18n";
import { parseSse } from "@/lib/sse";
import type {
  AgentAnswer,
  AgentRequest,
  HealthStatus,
  IngestRequest,
  IngestStatus,
  IngestSubmission,
  RagAnswer,
  RagRequest,
} from "@/lib/types";
import { AgentResult } from "./AgentResult";
import { IngestPanel } from "./IngestPanel";
import { ModeSidebar, type FinragMode } from "./ModeSidebar";
import { QuestionPanel } from "./QuestionPanel";
import { RagResult } from "./RagResult";

type CopyKey = keyof (typeof copy)["en"];
type StatusKey =
  | "pendingRag"
  | "pendingAgent"
  | "statusProcessing"
  | "statusComplete";
type UiError =
  | { kind: "copy"; key: CopyKey }
  | { kind: "raw"; text: string };

class UiRequestError extends Error {
  constructor(readonly detail: UiError) {
    super(detail.kind === "raw" ? detail.text : detail.key);
  }
}

type HealthCache = {
  fetchImpl: typeof fetch;
  promise: Promise<HealthStatus | null>;
};

const INGEST_JOB_ID = /^[A-Za-z0-9-]{1,64}$/;

let healthCache: HealthCache | null = null;

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

function isIngestSubmission(value: unknown): value is IngestSubmission {
  return (
    isRecord(value) &&
    typeof value.job_id === "string" &&
    INGEST_JOB_ID.test(value.job_id) &&
    value.status === "queued" &&
    typeof value.poll === "string"
  );
}

function isIngestStatus(value: unknown): value is IngestStatus {
  const statuses = ["queued", "running", "retrying", "done", "error"];
  return (
    isRecord(value) &&
    typeof value.job_id === "string" &&
    INGEST_JOB_ID.test(value.job_id) &&
    ["queued", "running", "done", "error"].includes(String(value.status)) &&
    Array.isArray(value.items) &&
    value.items.every(
      (item) =>
        isRecord(item) &&
        typeof item.id === "string" &&
        typeof item.ticker === "string" &&
        statuses.includes(String(item.status)) &&
        Number.isInteger(item.attempts) &&
        Number(item.attempts) >= 0,
    ) &&
    Array.isArray(value.results) &&
    value.results.every(
      (result) =>
        isRecord(result) &&
        typeof result.ticker === "string" &&
        (result.elapsed_s === null ||
          (typeof result.elapsed_s === "number" &&
            Number.isFinite(result.elapsed_s))) &&
        (typeof result.error === "string" ||
          (typeof result.chunks === "number" &&
            Number.isInteger(result.chunks) &&
            result.chunks >= 0)),
    )
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

async function responseError(response: Response): Promise<UiError> {
  try {
    const text = await response.text();
    if (text) {
      const message = errorFromPayload(JSON.parse(text));
      if (message) {
        return { kind: "raw", text: message };
      }
    }
  } catch {
    // Fall through to a stable localized message for malformed error bodies.
  }
  if (response.status === 401 || response.status === 403) {
    return { kind: "copy", key: "backendUnauthorized" };
  }
  if (response.status >= 500) {
    return { kind: "copy", key: "backendUnavailable" };
  }
  return { kind: "copy", key: "backendUnknownError" };
}

function loadHealthOnce(): Promise<HealthStatus | null> {
  const fetchImpl = fetch;
  if (healthCache?.fetchImpl === fetchImpl) {
    return healthCache.promise;
  }

  const cache: HealthCache = {
    fetchImpl,
    promise: Promise.resolve(null),
  };
  cache.promise = Promise.resolve(
    fetchImpl("/api/health", { signal: AbortSignal.timeout(10_000) }),
  )
    .then(async (response) => {
      if (!response.ok) {
        return null;
      }
      const data: unknown = await response.json();
      if (
        isRecord(data) &&
        typeof data.status === "string" &&
        typeof data.tracing === "boolean"
      ) {
        return { status: data.status, tracing: data.tracing };
      }
      return null;
    })
    .catch(() => {
      if (healthCache === cache) {
        healthCache = null;
      }
      return null;
    });
  healthCache = cache;
  return cache.promise;
}

/** Coordinate all public RAG, Agent, and filing-ingest network and UI state. */
export function FinragApp() {
  const [locale, setLocale] = useState<Locale>(defaultLocale);
  const [mode, setMode] = useState<FinragMode>("rag");
  const [ticker, setTicker] = useState("AAPL");
  const [year, setYear] = useState(2024);
  const [useYear, setUseYear] = useState(true);
  const [topK, setTopK] = useState(5);
  const [question, setQuestion] = useState(copy[defaultLocale].questionExampleRag);
  const [pending, setPending] = useState(false);
  const [statusKey, setStatusKey] = useState<StatusKey | null>(null);
  const [error, setError] = useState<UiError | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [ragResult, setRagResult] = useState<RagAnswer | null>(null);
  const [agentResult, setAgentResult] = useState<AgentAnswer | null>(null);
  const [ingestPending, setIngestPending] = useState(false);
  const [ingestStatus, setIngestStatus] = useState<IngestStatus | null>(null);
  const [ingestError, setIngestError] = useState<UiError | null>(null);
  const [ingestCanRetry, setIngestCanRetry] = useState(false);
  const [ingestCanRetryPoll, setIngestCanRetryPoll] = useState(false);
  const requestController = useRef<AbortController | null>(null);
  const requestGeneration = useRef(0);
  const ingestController = useRef<AbortController | null>(null);
  const ingestTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const ingestGeneration = useRef(0);
  const ingestLogicalSubmission = useRef<{
    request: IngestRequest;
    idempotencyKey: string;
  } | null>(null);
  const t = copy[locale];
  const statusText = statusKey ? t[statusKey] : null;
  const errorText =
    error?.kind === "copy" ? t[error.key] : (error?.text ?? null);
  const ingestErrorText =
    ingestError?.kind === "copy"
      ? t[ingestError.key]
      : (ingestError?.text ?? null);

  useEffect(() => {
    let active = true;
    void loadHealthOnce().then((result) => {
      if (active && result) {
        setHealth(result);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(
    () => () => {
      requestController.current?.abort();
      ingestGeneration.current += 1;
      ingestController.current?.abort();
      if (ingestTimer.current !== null) {
        clearTimeout(ingestTimer.current);
      }
    },
    [],
  );

  function cancelIngestWork() {
    ingestController.current?.abort();
    ingestController.current = null;
    if (ingestTimer.current !== null) {
      clearTimeout(ingestTimer.current);
      ingestTimer.current = null;
    }
  }

  function queuedStatus(jobId: string): IngestStatus {
    return {
      job_id: jobId,
      status: "queued",
      items: [],
      results: [],
    };
  }

  function scheduleIngestPoll(
    jobId: string,
    generation: number,
    failures: number,
  ) {
    if (ingestGeneration.current !== generation) {
      return;
    }
    if (ingestTimer.current !== null) {
      clearTimeout(ingestTimer.current);
    }
    ingestTimer.current = setTimeout(() => {
      ingestTimer.current = null;
      void pollIngest(jobId, generation, failures);
    }, 5_000);
  }

  async function pollIngest(
    jobId: string,
    generation: number,
    failures: number,
  ) {
    if (ingestGeneration.current !== generation) {
      return;
    }
    const controller = new AbortController();
    ingestController.current = controller;
    const isCurrent = () =>
      !controller.signal.aborted &&
      ingestController.current === controller &&
      ingestGeneration.current === generation;

    try {
      const response = await fetch(`/api/ingest/${encodeURIComponent(jobId)}`, {
        signal: controller.signal,
      });
      if (!response.ok) {
        if ([429, 502, 503].includes(response.status)) {
          throw new Error("transient ingest status response");
        }
        throw new UiRequestError(await responseError(response));
      }
      let parsed: unknown;
      try {
        parsed = await response.json();
      } catch {
        throw new UiRequestError({
          kind: "copy",
          key: "validationInvalidResponse",
        });
      }
      if (!isIngestStatus(parsed) || parsed.job_id !== jobId) {
        throw new UiRequestError({
          kind: "copy",
          key: "validationInvalidResponse",
        });
      }
      if (!isCurrent()) {
        return;
      }
      setIngestStatus(parsed);
      setIngestError(null);
      setIngestCanRetryPoll(false);
      if (parsed.status === "done" || parsed.status === "error") {
        setIngestCanRetry(false);
        return;
      }
      scheduleIngestPoll(jobId, generation, 0);
    } catch (caught) {
      if (!isCurrent()) {
        return;
      }
      if (caught instanceof UiRequestError) {
        setIngestError(caught.detail);
        setIngestCanRetryPoll(false);
        return;
      }
      const nextFailures = failures + 1;
      if (nextFailures >= 3) {
        setIngestError({ kind: "copy", key: "networkPollingStopped" });
        setIngestCanRetryPoll(true);
        return;
      }
      setIngestError({ kind: "copy", key: "networkPollFailed" });
      scheduleIngestPoll(jobId, generation, nextFailures);
    } finally {
      if (ingestController.current === controller) {
        ingestController.current = null;
      }
    }
  }

  async function postIngest(
    logical: { request: IngestRequest; idempotencyKey: string },
    generation: number,
  ) {
    const controller = new AbortController();
    ingestController.current = controller;
    const isCurrent = () =>
      !controller.signal.aborted &&
      ingestController.current === controller &&
      ingestGeneration.current === generation;
    setIngestPending(true);
    setIngestError(null);
    setIngestCanRetry(false);
    setIngestCanRetryPoll(false);

    try {
      const response = await fetch("/api/ingest", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": logical.idempotencyKey,
        },
        body: JSON.stringify(logical.request),
        signal: controller.signal,
      });
      if (!response.ok) {
        let parsed: unknown = null;
        try {
          parsed = await response.clone().json();
        } catch {
          // The standard response parser below handles malformed error bodies.
        }
        const detail =
          isRecord(parsed) && isRecord(parsed.detail) ? parsed.detail : null;
        if (response.status === 503 && detail?.retryable === true) {
          if (!isCurrent()) {
            return;
          }
          const jobId =
            typeof detail.job_id === "string" ? detail.job_id : null;
          if (jobId) {
            setIngestStatus(queuedStatus(jobId));
            scheduleIngestPoll(jobId, generation, 0);
          }
          setIngestCanRetry(true);
          setIngestError(
            typeof detail.error === "string"
              ? { kind: "raw", text: detail.error }
              : { kind: "copy", key: "backendUnavailable" },
          );
          return;
        }
        throw new UiRequestError(await responseError(response));
      }

      let parsed: unknown;
      try {
        parsed = await response.json();
      } catch {
        throw new UiRequestError({
          kind: "copy",
          key: "validationInvalidResponse",
        });
      }
      if (!isIngestSubmission(parsed)) {
        throw new UiRequestError({
          kind: "copy",
          key: "validationInvalidResponse",
        });
      }
      if (!isCurrent()) {
        return;
      }
      setIngestStatus(queuedStatus(parsed.job_id));
      setIngestCanRetry(false);
      scheduleIngestPoll(parsed.job_id, generation, 0);
    } catch (caught) {
      if (!isCurrent()) {
        return;
      }
      if (caught instanceof UiRequestError) {
        setIngestError(caught.detail);
      } else {
        setIngestError({ kind: "copy", key: "networkRequestFailed" });
        setIngestCanRetry(true);
      }
    } finally {
      if (isCurrent()) {
        setIngestPending(false);
        ingestController.current = null;
      }
    }
  }

  function submitIngest(request: IngestRequest) {
    const tickerValue = request.tickers[0]?.trim().toUpperCase() ?? "";
    if (!tickerValue) {
      setIngestError({ kind: "copy", key: "validationTickerRequired" });
      return;
    }
    if (
      !Number.isInteger(request.year) ||
      Number(request.year) < 1994 ||
      Number(request.year) > 2030
    ) {
      setIngestError({ kind: "copy", key: "validationYearRange" });
      return;
    }

    cancelIngestWork();
    const generation = ingestGeneration.current + 1;
    ingestGeneration.current = generation;
    const logical = {
      request: { ...request, tickers: [tickerValue] },
      idempotencyKey: crypto.randomUUID(),
    };
    ingestLogicalSubmission.current = logical;
    setIngestStatus(null);
    setIngestCanRetry(false);
    setIngestCanRetryPoll(false);
    void postIngest(logical, generation);
  }

  function retryIngestSubmission() {
    const logical = ingestLogicalSubmission.current;
    if (!logical) {
      return;
    }
    cancelIngestWork();
    const generation = ingestGeneration.current + 1;
    ingestGeneration.current = generation;
    void postIngest(logical, generation);
  }

  function retryIngestPoll() {
    const jobId = ingestStatus?.job_id;
    if (!jobId || !INGEST_JOB_ID.test(jobId)) {
      return;
    }
    cancelIngestWork();
    const generation = ingestGeneration.current + 1;
    ingestGeneration.current = generation;
    setIngestError(null);
    setIngestCanRetryPoll(false);
    void pollIngest(jobId, generation, 0);
  }

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
    requestGeneration.current += 1;
    requestController.current?.abort();
    requestController.current = null;
    setMode(nextMode);
    setPending(false);
    setError(null);
    setStatusKey(null);
    setRagResult(null);
    setAgentResult(null);
  }

  async function runRag(
    controller: AbortController,
    generation: number,
    trimmed: string,
  ) {
    const isCurrent = () =>
      !controller.signal.aborted &&
      requestController.current === controller &&
      requestGeneration.current === generation;
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
      throw new UiRequestError(await responseError(response));
    }
    if (!response.body) {
      throw new UiRequestError({
        kind: "copy",
        key: "validationInvalidResponse",
      });
    }

    let answer: RagAnswer | null = null;
    let done = false;
    for await (const event of parseSse(response.body)) {
      if (!isCurrent()) {
        return;
      }
      if (event.event === "status") {
        setStatusKey("statusProcessing");
      } else if (event.event === "answer") {
        let parsed: unknown;
        try {
          parsed = JSON.parse(event.data);
        } catch {
          throw new UiRequestError({
            kind: "copy",
            key: "validationInvalidResponse",
          });
        }
        if (!isRagAnswer(parsed)) {
          throw new UiRequestError({
            kind: "copy",
            key: "validationInvalidResponse",
          });
        }
        answer = parsed;
      } else if (event.event === "error") {
        let parsed: unknown;
        try {
          parsed = JSON.parse(event.data);
        } catch {
          throw new UiRequestError({
            kind: "copy",
            key: "validationInvalidResponse",
          });
        }
        const message = errorFromPayload(parsed);
        throw new UiRequestError(
          message
            ? { kind: "raw", text: message }
            : { kind: "copy", key: "backendUnknownError" },
        );
      } else if (event.event === "done") {
        done = true;
      }
    }
    if (!answer || !done) {
      throw new UiRequestError({
        kind: "copy",
        key: "validationInvalidResponse",
      });
    }
    if (isCurrent()) {
      setRagResult(answer);
      setStatusKey("statusComplete");
    }
  }

  async function runAgent(
    controller: AbortController,
    generation: number,
    trimmed: string,
  ) {
    const isCurrent = () =>
      !controller.signal.aborted &&
      requestController.current === controller &&
      requestGeneration.current === generation;
    const payload: AgentRequest = { question: trimmed };
    const response = await fetch("/api/agent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new UiRequestError(await responseError(response));
    }

    let parsed: unknown;
    try {
      parsed = await response.json();
    } catch {
      throw new UiRequestError({
        kind: "copy",
        key: "validationInvalidResponse",
      });
    }
    if (!isAgentAnswer(parsed)) {
      throw new UiRequestError({
        kind: "copy",
        key: "validationInvalidResponse",
      });
    }
    if (isCurrent()) {
      setAgentResult(parsed);
      setStatusKey("statusComplete");
    }
  }

  async function submitQuestion() {
    const trimmed = question.trim();
    if (!trimmed) {
      setError({ kind: "copy", key: "validationQuestionRequired" });
      return;
    }
    if (mode === "rag" && useYear && (!Number.isInteger(year) || year < 1994 || year > 2030)) {
      setError({ kind: "copy", key: "validationYearRange" });
      return;
    }

    requestController.current?.abort();
    const controller = new AbortController();
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    requestController.current = controller;
    setPending(true);
    setError(null);
    setRagResult(null);
    setAgentResult(null);
    setStatusKey(mode === "rag" ? "pendingRag" : "pendingAgent");

    try {
      if (mode === "rag") {
        await runRag(controller, generation, trimmed);
      } else {
        await runAgent(controller, generation, trimmed);
      }
    } catch (caught) {
      if (
        !controller.signal.aborted &&
        requestController.current === controller &&
        requestGeneration.current === generation
      ) {
        setError(
          caught instanceof UiRequestError
            ? caught.detail
            : caught instanceof Error && caught.message
              ? { kind: "raw", text: caught.message }
              : { kind: "copy", key: "networkRequestFailed" },
        );
        setStatusKey(null);
        setRagResult(null);
        setAgentResult(null);
      }
    } finally {
      if (
        requestController.current === controller &&
        requestGeneration.current === generation
      ) {
        setPending(false);
        requestController.current = null;
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
        pending={pending}
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
        {errorText ? <p role="alert">{errorText}</p> : null}
        {mode === "rag" && ragResult ? (
          <RagResult locale={locale} result={ragResult} />
        ) : null}
        {mode === "agent" && agentResult ? (
          <AgentResult locale={locale} result={agentResult} />
        ) : null}
        <IngestPanel
          locale={locale}
          pending={ingestPending}
          status={ingestStatus}
          error={ingestErrorText}
          canRetry={ingestCanRetry}
          canRetryPoll={ingestCanRetryPoll}
          onSubmit={submitIngest}
          onRetry={retryIngestSubmission}
          onRetryPoll={retryIngestPoll}
        />
      </div>
    </main>
  );
}
