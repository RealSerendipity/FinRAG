import { useState } from "react";

import { copy, type Locale } from "@/lib/i18n";
import type { IngestRequest, IngestStatus } from "@/lib/types";

const FILING_FORMS = ["10-K", "10-Q", "8-K", "20-F", "DEF 14A"] as const;

type IngestPanelProps = {
  locale: Locale;
  pending: boolean;
  status: IngestStatus | null;
  error: string | null;
  canRetry: boolean;
  canRetryPoll: boolean;
  onSubmit: (request: IngestRequest) => void;
  onRetry: () => void;
  onRetryPoll: () => void;
};

/** Render filing inputs and persistent ingest progress without owning network state. */
export function IngestPanel({
  locale,
  pending,
  status,
  error,
  canRetry,
  canRetryPoll,
  onSubmit,
  onRetry,
  onRetryPoll,
}: IngestPanelProps) {
  const [ticker, setTicker] = useState("MSFT");
  const [year, setYear] = useState(2024);
  const [formType, setFormType] = useState<(typeof FILING_FORMS)[number]>(
    "10-K",
  );
  const t = copy[locale];
  const statusLabels = {
    queued: t.ingestStatusQueued,
    running: t.ingestStatusRunning,
    retrying: t.ingestRetrying,
    done: t.ingestStatusDone,
    error: t.ingestStatusError,
  };

  return (
    <details className="ingest-panel" data-testid="ingest-panel">
      <summary>{t.ingestSummary}</summary>
      <div className="ingest-panel-content">
        <p>{t.ingestDescription}</p>
        <form
          aria-busy={pending}
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit({
              tickers: [ticker.trim().toUpperCase()],
              form_type: formType,
              year,
            });
          }}
        >
          <label htmlFor="ingest-ticker">
            {t.ingestTicker}
            <input
              id="ingest-ticker"
              aria-label={`${t.ingestTitle}: ${t.ingestTicker}`}
              type="text"
              value={ticker}
              disabled={pending}
              onChange={(event) => setTicker(event.target.value)}
            />
          </label>
          <label htmlFor="ingest-year">
            {t.ingestYear}
            <input
              id="ingest-year"
              aria-label={`${t.ingestTitle}: ${t.ingestYear}`}
              type="number"
              min={1994}
              max={2030}
              value={year}
              disabled={pending}
              onChange={(event) => setYear(event.target.valueAsNumber)}
            />
          </label>
          <label htmlFor="ingest-form">
            {t.ingestForm}
            <select
              id="ingest-form"
              aria-label={`${t.ingestTitle}: ${t.ingestForm}`}
              value={formType}
              disabled={pending}
              onChange={(event) =>
                setFormType(
                  event.target.value as (typeof FILING_FORMS)[number],
                )
              }
            >
              {FILING_FORMS.map((form) => (
                <option key={form} value={form}>
                  {form}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" disabled={pending}>
            {pending ? t.ingestPending : t.ingestSubmit}
          </button>
        </form>
        <p
          className="sr-only"
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          {pending ? t.ingestPending : ""}
        </p>

        {error ? (
          <p className="error-message" role="alert" aria-live="assertive">
            {error}
          </p>
        ) : null}
        {canRetry ? (
          <button type="button" disabled={pending} onClick={onRetry}>
            {t.ingestRetrySubmit}
          </button>
        ) : null}
        {canRetryPoll ? (
          <button type="button" disabled={pending} onClick={onRetryPoll}>
            {t.ingestRetryPoll}
          </button>
        ) : null}

        {status ? (
          <section
            className="ingest-status"
            aria-labelledby="ingest-status-title"
          >
            <h3 id="ingest-status-title">{t.ingestJobStatus}</h3>
            <p role="status" aria-live="polite">
              {statusLabels[status.status]}
            </p>
            {status.items.map((item) => (
              <p key={item.id}>
                {item.ticker}: {statusLabels[item.status]} ·{" "}
                {t.ingestAttempts}: {item.attempts}
              </p>
            ))}
            {status.results.map((result) => (
              <p key={result.ticker}>
                {result.ticker}:{" "}
                {"error" in result
                  ? result.error
                  : `${result.chunks} ${t.ingestChunks}`}
                {result.elapsed_s === null
                  ? ""
                  : ` · ${t.ingestElapsed}: ${result.elapsed_s}s`}
              </p>
            ))}
            {status.status === "done" ? <p>{t.ingestSuccess}</p> : null}
            {status.status === "error" ? <p>{t.ingestFailed}</p> : null}
          </section>
        ) : null}
      </div>
    </details>
  );
}
