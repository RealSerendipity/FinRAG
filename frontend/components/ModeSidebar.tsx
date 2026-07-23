import { copy, type Locale } from "@/lib/i18n";
import type { HealthStatus } from "@/lib/types";

export type FinragMode = "rag" | "agent";

export type ModeSidebarProps = {
  idPrefix: "desktop" | "mobile";
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
  idPrefix,
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
  const settingsTitleId = `${idPrefix}-settings-title`;
  const modeTitleId = `${idPrefix}-mode-title`;
  const scopeTitleId = `${idPrefix}-scope-title`;
  const tickerId = `${idPrefix}-ticker`;
  const yearId = `${idPrefix}-year`;
  const useYearId = `${idPrefix}-use-year`;
  const topKId = `${idPrefix}-top-k`;
  const currentLanguage =
    locale === "en" ? t.languageEnglish : t.languageChinese;
  const nextLanguage =
    locale === "en" ? t.languageChinese : t.languageEnglish;
  const languageButtonLabel =
    locale === "en"
      ? `${t.languageLabel}: ${currentLanguage}. Switch to ${nextLanguage}`
      : `${t.languageLabel}：${currentLanguage}。切换至 ${nextLanguage}`;

  return (
    <div className="mode-sidebar">
      <section
        className="settings-panel"
        aria-labelledby={settingsTitleId}
      >
        <h2 id={settingsTitleId}>{t.settingsTitle}</h2>
        <div className="language-control">
          <span>{t.languageLabel}</span>
          <button
            type="button"
            className="language-button"
            aria-label={languageButtonLabel}
            disabled={pending}
            onClick={() => onLocaleChange(locale === "en" ? "zh" : "en")}
          >
            {currentLanguage}
          </button>
        </div>
      </section>

      <fieldset
        className="mode-selector"
        role="radiogroup"
        aria-labelledby={modeTitleId}
      >
        <legend id={modeTitleId}>{t.modeLabel}</legend>
        <label>
          <input
            id={`${idPrefix}-mode-rag`}
            type="radio"
            name={`${idPrefix}-mode`}
            value="rag"
            checked={mode === "rag"}
            disabled={pending}
            onChange={() => onModeChange("rag")}
          />
          {t.modeRag}
        </label>
        <p>{t.modeRagDescription}</p>
        <label>
          <input
            id={`${idPrefix}-mode-agent`}
            type="radio"
            name={`${idPrefix}-mode`}
            value="agent"
            checked={mode === "agent"}
            disabled={pending}
            onChange={() => onModeChange("agent")}
          />
          {t.modeAgent}
        </label>
        <p>{t.modeAgentDescription}</p>
      </fieldset>

      {mode === "rag" ? (
        <section className="scope-panel" aria-labelledby={scopeTitleId}>
          <h2 id={scopeTitleId}>{t.scopeTitle}</h2>
          <label htmlFor={tickerId}>
            {t.scopeTicker}
            <input
              id={tickerId}
              type="text"
              value={ticker}
              disabled={pending}
              onChange={(event) => onTickerChange(event.target.value)}
            />
          </label>
          <p className="control-hint">{t.scopeTickerHint}</p>
          <label htmlFor={yearId}>
            {t.scopeYear}
            <input
              id={yearId}
              type="number"
              min={1994}
              max={2030}
              value={year}
              disabled={pending}
              onChange={(event) => onYearChange(event.target.valueAsNumber)}
            />
          </label>
          <label htmlFor={useYearId} className="inline-control">
            <input
              id={useYearId}
              type="checkbox"
              checked={useYear}
              disabled={pending}
              onChange={(event) => onUseYearChange(event.target.checked)}
            />
            {t.scopeUseYear}
          </label>
          <label htmlFor={topKId}>
            {t.scopeTopK}
            <input
              id={topKId}
              type="range"
              min={1}
              max={20}
              value={topK}
              disabled={pending}
              onChange={(event) => onTopKChange(event.target.valueAsNumber)}
            />
            <output htmlFor={topKId}>{topK}</output>
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
    </div>
  );
}
