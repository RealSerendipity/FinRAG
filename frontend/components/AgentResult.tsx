import { copy, type Locale } from "@/lib/i18n";
import type { AgentAnswer } from "@/lib/types";

export type AgentResultProps = {
  locale: Locale;
  result: AgentAnswer;
};

function stoppedLabel(
  locale: Locale,
  stopped: AgentAnswer["stopped"],
): string {
  const t = copy[locale];
  return {
    final_answer: t.agentStoppedFinal,
    max_steps: t.agentStoppedMaxSteps,
    blocked: t.agentStoppedBlocked,
    blocked_output: t.agentStoppedBlockedOutput,
  }[stopped];
}

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

/** Render a parsed Agent answer with tools and native step disclosures. */
export function AgentResult({ locale, result }: AgentResultProps) {
  const t = copy[locale];
  const traceUrl = safeTraceUrl(result.trace_url);

  return (
    <article className="agent-result">
      <h2>{t.answerTitle}</h2>
      <p className="answer-text">{result.answer}</p>

      {result.tools_used.length > 0 ? (
        <section aria-labelledby="agent-tools-title">
          <h3 id="agent-tools-title">{t.agentToolsUsed}</h3>
          <ul className="tool-list">
            {result.tools_used.map((tool) => (
              <li key={tool}>{tool}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {result.steps.length > 0 ? (
        <section aria-labelledby="agent-steps-title">
          <h3 id="agent-steps-title">{t.agentSteps}</h3>
          {result.steps.map((step, index) => (
            <details key={`${index}-${step.action ?? "thought"}`}>
              <summary>
                {t.agentStep} {index + 1}
                {step.action ? ` — ${step.action}` : ""}
              </summary>
              {step.thought ? (
                <p>
                  <strong>{t.agentThought}:</strong> {step.thought}
                </p>
              ) : null}
              {step.action ? (
                <p>
                  <strong>{t.agentAction}:</strong> {step.action}
                </p>
              ) : null}
              {step.action_input ? (
                <pre>
                  <code>{JSON.stringify(step.action_input, null, 2)}</code>
                </pre>
              ) : null}
              {step.observation ? (
                <p>
                  <strong>{t.agentObservation}:</strong> {step.observation}
                </p>
              ) : null}
            </details>
          ))}
        </section>
      ) : null}

      <p>
        {t.agentStopped}: {stoppedLabel(locale, result.stopped)}
      </p>
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
