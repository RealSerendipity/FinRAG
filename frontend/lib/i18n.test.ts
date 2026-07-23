import { describe, expect, test } from "vitest";

import { copy, defaultLocale } from "./i18n";

describe("bilingual copy", () => {
  test("defaults to English", () => {
    expect(defaultLocale).toBe("en");
  });

  test("keeps English and Chinese keys identical", () => {
    expect(Object.keys(copy.zh).sort()).toEqual(Object.keys(copy.en).sort());
  });

  test("covers every visible area needed by RAG, Agent, and ingest", () => {
    const requiredKeys = [
      "modeRag",
      "modeAgent",
      "scopeTicker",
      "scopeYear",
      "scopeUseYear",
      "scopeTopK",
      "healthLabel",
      "tracingLabel",
      "questionLabel",
      "questionExampleRag",
      "questionExampleAgent",
      "askButton",
      "pendingRag",
      "pendingAgent",
      "statusProcessing",
      "citationsTitle",
      "citationVerified",
      "metricsLatency",
      "metricsTokens",
      "metricsCost",
      "metricsTrace",
      "agentToolsUsed",
      "agentSteps",
      "agentThought",
      "agentAction",
      "agentInput",
      "agentObservation",
      "agentStopped",
      "agentStoppedFinal",
      "agentStoppedMaxSteps",
      "agentStoppedBlocked",
      "agentStoppedBlockedOutput",
      "ingestTitle",
      "ingestTicker",
      "ingestYear",
      "ingestForm",
      "ingestSubmit",
      "ingestStatusQueued",
      "ingestStatusRunning",
      "ingestStatusDone",
      "ingestStatusError",
      "ingestRetrying",
      "settingsTitle",
      "languageLabel",
      "validationQuestionRequired",
      "validationTickerRequired",
      "networkRequestFailed",
      "networkPollingStopped",
      "backendUnknownError",
    ];

    for (const key of requiredKeys) {
      expect(copy.en).toHaveProperty(key);
      expect(copy.zh).toHaveProperty(key);
      expect(copy.en[key as keyof typeof copy.en]).not.toBe("");
      expect(copy.zh[key as keyof typeof copy.zh]).not.toBe("");
    }
  });
});
