import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import type { RagAnswer } from "@/lib/types";
import { RagResult } from "./RagResult";

const result: RagAnswer = {
  text: "<strong>Net sales were $391 billion.</strong>",
  citations: [
    {
      chunk_id: 17,
      quote: "Total net sales were $391,035 million.",
      verified: true,
    },
  ],
  usage: { input_tokens: 120, output_tokens: 30, calls: 1 },
  cost_usd: 0.001234,
  cost_estimated: true,
  latency_ms: 1500,
  trace_url: "https://trace.example/run-1",
};

describe("RagResult", () => {
  test("renders model text safely and gives verified citations a text label", () => {
    const { container } = render(<RagResult locale="en" result={result} />);

    expect(
      screen.getByText("<strong>Net sales were $391 billion.</strong>"),
    ).toBeInTheDocument();
    expect(container.querySelector("strong")).not.toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(
      screen.getByText("Total net sales were $391,035 million."),
    ).toBeInTheDocument();
    const details = screen.getByText(/chunk 17/i).closest("details");
    expect(details).not.toBeNull();
    expect(details!.querySelector("summary")).toHaveTextContent(
      "chunk 17 · Verified",
    );
  });
});
