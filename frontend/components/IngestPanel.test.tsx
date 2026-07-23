import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import type { IngestStatus } from "@/lib/types";
import { IngestPanel } from "./IngestPanel";

test("submits one normalized ticker with the supported default filing fields", () => {
  const onSubmit = vi.fn();
  render(
    <IngestPanel
      locale="en"
      pending={false}
      status={null}
      error={null}
      canRetry={false}
      onSubmit={onSubmit}
      onRetry={vi.fn()}
    />,
  );

  expect(screen.getByLabelText("Ingest a filing: Filing ticker")).toHaveValue(
    "MSFT",
  );
  expect(screen.getByLabelText("Ingest a filing: Year")).toHaveValue(2024);
  expect(screen.getByLabelText("Ingest a filing: Form")).toHaveValue("10-K");
  expect(
    within(screen.getByLabelText("Ingest a filing: Form")).getAllByRole(
      "option",
    ),
  ).toHaveLength(5);

  fireEvent.change(screen.getByLabelText("Ingest a filing: Filing ticker"), {
    target: { value: " msft " },
  });
  fireEvent.click(screen.getByRole("button", { name: "Ingest filing" }));

  expect(onSubmit).toHaveBeenCalledWith({
    tickers: ["MSFT"],
    form_type: "10-K",
    year: 2024,
  });
});

test("renders backend result and error strings as text", () => {
  const status: IngestStatus = {
    job_id: "job-1",
    status: "error",
    items: [
      {
        id: "item-1",
        ticker: "MSFT",
        status: "error",
        attempts: 2,
      },
    ],
    results: [
      {
        ticker: "MSFT",
        error: "<img src=x onerror=alert(1)>",
        elapsed_s: 1.25,
      },
    ],
  };
  const { container } = render(
    <IngestPanel
      locale="en"
      pending={false}
      status={status}
      error={null}
      canRetry={false}
      onSubmit={vi.fn()}
      onRetry={vi.fn()}
    />,
  );

  expect(container).toHaveTextContent("<img src=x onerror=alert(1)>");
  expect(container.querySelector("img")).not.toBeInTheDocument();
  expect(screen.getByText(/Attempts: 2/)).toBeInTheDocument();
});

test("exposes retry submission without rendering the idempotency key", () => {
  const onRetry = vi.fn();
  const { container } = render(
    <IngestPanel
      locale="en"
      pending={false}
      status={null}
      error="The request failed."
      canRetry
      onSubmit={vi.fn()}
      onRetry={onRetry}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Retry submission" }));

  expect(onRetry).toHaveBeenCalledOnce();
  expect(container).not.toHaveTextContent("idempotency");
});
