import { copy, type Locale } from "@/lib/i18n";
import type { HealthStatus } from "@/lib/types";

export type FinragMode = "rag" | "agent";

export type ModeSidebarProps = {
  locale: Locale;
  mode: FinragMode;
  ticker: string;
  year: number;
  useYear: boolean;
  topK: number;
  health: HealthStatus | null;
  pending: boolean;
  onLocaleChange: (locale: Locale) => void;
  onModeChange: (mode: FinragMode) => void;
  onTickerChange: (value: string) => void;
  onYearChange: (value: number) => void;
  onUseYearChange: (value: boolean) => void;
  onTopKChange: (value: number) => void;
};

/** Render mode, locale, scope, and backend-health controls. */
export function ModeSidebar({
  locale,
  mode,
  ticker,
  year,
  useYear,
  topK,
  health,
  pending,
  onLocaleChange,
  onModeChange,
  onTickerChange,
  onYearChange,
  onUseYearChange,
  onTopKChange,
}: ModeSidebarProps) {
  const t = copy[locale];

  return (
    <aside className="mode-sidebar">
      <section className="settings-panel" aria-labelledby="settings-title">
        <h2 id="settings-title">{t.settingsTitle}</h2>
        <label>
          {t.languageLabel}
          <select
            value={locale}
            disabled={pending}
            onChange={(event) =>
              onLocaleChange(event.target.value as Locale)
            }
          >
            <option value="en">{t.languageEnglish}</option>
            <option value="zh">{t.languageChinese}</option>
          </select>
        </label>
      </section>

      <fieldset className="mode-selector">
        <legend>{t.modeLabel}</legend>
        <label>
          <input
            type="radio"
            name="mode"
            value="rag"
            checked={mode === "rag"}
            onChange={() => onModeChange("rag")}
          />
          {t.modeRag}
        </label>
        <p>{t.modeRagDescription}</p>
        <label>
          <input
            type="radio"
            name="mode"
            value="agent"
            checked={mode === "agent"}
            onChange={() => onModeChange("agent")}
          />
          {t.modeAgent}
        </label>
        <p>{t.modeAgentDescription}</p>
      </fieldset>

      {mode === "rag" ? (
        <section className="scope-panel" aria-labelledby="scope-title">
          <h2 id="scope-title">{t.scopeTitle}</h2>
          <label>
            {t.scopeTicker}
            <input
              type="text"
              value={ticker}
              onChange={(event) => onTickerChange(event.target.value)}
            />
          </label>
          <p>{t.scopeTickerHint}</p>
          <label>
            {t.scopeYear}
            <input
              type="number"
              min={1994}
              max={2030}
              value={year}
              onChange={(event) => onYearChange(event.target.valueAsNumber)}
            />
          </label>
          <label>
            <input
              type="checkbox"
              checked={useYear}
              onChange={(event) => onUseYearChange(event.target.checked)}
            />
            {t.scopeUseYear}
          </label>
          <label>
            {t.scopeTopK}
            <input
              type="range"
              min={1}
              max={20}
              value={topK}
              onChange={(event) => onTopKChange(event.target.valueAsNumber)}
            />
            <output>{topK}</output>
          </label>
        </section>
      ) : (
        <p className="agent-scope-note">{t.scopeAgentManaged}</p>
      )}

      <section className="health-panel" aria-label={t.healthLabel}>
        <p>
          {t.healthLabel}:{" "}
          {health ? health.status : t.healthUnreachable}
        </p>
        <p>
          {t.tracingLabel}:{" "}
          {health?.tracing ? t.tracingEnabled : t.tracingDisabled}
        </p>
      </section>
    </aside>
  );
}
