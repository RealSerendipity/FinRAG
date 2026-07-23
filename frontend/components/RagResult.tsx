import { copy, type Locale } from "@/lib/i18n";
import type { RagAnswer } from "@/lib/types";

export type RagResultProps = {
  locale: Locale;
  result: RagAnswer;
};

function safeTraceUrl(value: string | null): string | null {
  if (!value) {
    return null;
  }
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? value : null;
  } catch {
    return null;
  }
}

/** Render a parsed RAG answer, citations, usage, and trace metadata. */
export function RagResult({ locale, result }: RagResultProps) {
  const t = copy[locale];
  const traceUrl = safeTraceUrl(result.trace_url);

  return (
    <article className="rag-result">
      <h2>{t.answerTitle}</h2>
      <p className="answer-text">{result.text}</p>
      {result.citations.length > 0 ? (
        <section aria-labelledby="citations-title">
          <h3 id="citations-title">
            {t.citationsTitle} ({result.citations.length})
          </h3>
          <ol className="citation-list">
            {result.citations.map((citation) => (
              <li key={citation.chunk_id}>
                <details>
                  <summary>
                    {t.citationChunk} {citation.chunk_id} ·{" "}
                    <span className="citation-verification">
                      {citation.verified
                        ? t.citationVerified
                        : t.citationUnverified}
                    </span>
                  </summary>
                  <p>{citation.quote}</p>
                </details>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      <footer className="result-metrics">
        <span>
          {t.metricsLatency}: {result.latency_ms} ms
        </span>
        <span>
          {t.metricsTokens}: {result.usage.input_tokens}{" "}
          {t.metricsInputTokens} + {result.usage.output_tokens}{" "}
          {t.metricsOutputTokens}
        </span>
        <span>
          {t.metricsCost}:{" "}
          {result.cost_estimated
            ? `$${result.cost_usd.toFixed(6)}`
            : t.metricsCostUnknown}
        </span>
        {traceUrl ? (
          <a href={traceUrl} target="_blank" rel="noreferrer">
            {t.metricsTrace}
          </a>
        ) : null}
      </footer>
    </article>
  );
}
