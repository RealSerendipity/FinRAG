import { render, screen, within } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import type { AgentAnswer } from "@/lib/types";
import { AgentResult } from "./AgentResult";

const baseResult: AgentAnswer = {
  answer: "The ratio increased by 0.4 percentage points.",
  steps: [
    {
      thought: "I need both fiscal years.",
      action: "sec_xbrl_metric",
      action_input: { ticker: "AAPL", metric: "R&D" },
      observation: "FY2023: 29.9; FY2024: 31.4",
    },
  ],
  tools_used: ["sec_xbrl_metric", "calculator"],
  stopped: "final_answer",
  usage: { input_tokens: 300, output_tokens: 80, calls: 2 },
  cost_usd: 0.004,
  cost_estimated: true,
  latency_ms: 2300,
  trace_url: null,
};

describe("AgentResult", () => {
  test("renders answer, tools, and native expandable step details", () => {
    render(<AgentResult locale="en" result={baseResult} />);

    expect(screen.getByText(baseResult.answer)).toBeInTheDocument();
    const tools = screen.getByRole("heading", { name: "Tools used" })
      .parentElement;
    expect(tools).not.toBeNull();
    expect(within(tools!).getByText("sec_xbrl_metric")).toBeInTheDocument();
    expect(within(tools!).getByText("calculator")).toBeInTheDocument();
    const details = screen.getByText(/Step 1/).closest("details");
    expect(details).not.toBeNull();
    expect(details!.querySelector("summary")).toHaveTextContent(
      "Step 1 — sec_xbrl_metric",
    );
    expect(screen.getByText("I need both fiscal years.")).toBeInTheDocument();
    expect(screen.getByText(/\"ticker\": \"AAPL\"/)).toBeInTheDocument();
    expect(screen.getByText(/FY2023: 29.9/)).toBeInTheDocument();
  });

  test.each([
    ["final_answer", "Final answer"],
    ["max_steps", "Maximum steps reached"],
    ["blocked", "Blocked by policy or unavailable tools"],
    ["blocked_output", "Blocked output"],
  ] as const)("localizes the %s stopped state", (stopped, label) => {
    render(
      <AgentResult locale="en" result={{ ...baseResult, stopped }} />,
    );

    expect(screen.getByText(`Stopped: ${label}`)).toBeInTheDocument();
  });
});
