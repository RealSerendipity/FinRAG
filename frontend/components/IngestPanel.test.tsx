import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import type { IngestStatus } from "@/lib/types";
import { IngestPanel } from "./IngestPanel";

function openPanel() {
  const panel = screen.getByTestId("ingest-panel") as HTMLDetailsElement;
  const summary = panel.querySelector("summary");
  expect(summary).not.toBeNull();
  if (!panel.open) {
    fireEvent.click(summary!);
  }
  return within(panel);
}

test("submits one normalized ticker with the supported default filing fields", () => {
  const onSubmit = vi.fn();
  render(
    <IngestPanel
      locale="en"
      pending={false}
      status={null}
      error={null}
      canRetry={false}
      canRetryPoll={false}
      onSubmit={onSubmit}
      onRetry={vi.fn()}
      onRetryPoll={vi.fn()}
    />,
  );
  const panel = openPanel();

  expect(panel.getByLabelText("Ingest a filing: Filing ticker")).toHaveValue(
    "MSFT",
  );
  expect(panel.getByLabelText("Ingest a filing: Year")).toHaveValue(2024);
  expect(panel.getByLabelText("Ingest a filing: Form")).toHaveValue("10-K");
  expect(
    within(panel.getByLabelText("Ingest a filing: Form")).getAllByRole(
      "option",
    ),
  ).toHaveLength(5);

  fireEvent.change(panel.getByLabelText("Ingest a filing: Filing ticker"), {
    target: { value: " msft " },
  });
  fireEvent.click(panel.getByRole("button", { name: "Ingest filing" }));

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
      canRetryPoll={false}
      onSubmit={vi.fn()}
      onRetry={vi.fn()}
      onRetryPoll={vi.fn()}
    />,
  );
  openPanel();

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
      canRetryPoll={false}
      onSubmit={vi.fn()}
      onRetry={onRetry}
      onRetryPoll={vi.fn()}
    />,
  );
  const panel = openPanel();

  fireEvent.click(panel.getByRole("button", { name: "Retry submission" }));

  expect(onRetry).toHaveBeenCalledOnce();
  expect(container).not.toHaveTextContent("idempotency");
});

test("offers a separate status-check retry action", () => {
  const onRetryPoll = vi.fn();
  render(
    <IngestPanel
      locale="en"
      pending={false}
      status={{
        job_id: "job-1",
        status: "running",
        items: [],
        results: [],
      }}
      error="Polling stopped."
      canRetry={false}
      canRetryPoll
      onSubmit={vi.fn()}
      onRetry={vi.fn()}
      onRetryPoll={onRetryPoll}
    />,
  );
  const panel = openPanel();

  fireEvent.click(
    panel.getByRole("button", { name: "Retry status check" }),
  );

  expect(onRetryPoll).toHaveBeenCalledOnce();
  expect(
    panel.queryByRole("button", { name: "Retry submission" }),
  ).not.toBeInTheDocument();
});

test("uses a collapsed native disclosure with labelled form controls", () => {
  render(
    <IngestPanel
      locale="en"
      pending={false}
      status={null}
      error={null}
      canRetry={false}
      canRetryPoll={false}
      onSubmit={vi.fn()}
      onRetry={vi.fn()}
      onRetryPoll={vi.fn()}
    />,
  );

  const details = screen.getByTestId("ingest-panel");
  expect(details.tagName).toBe("DETAILS");
  expect(details).not.toHaveAttribute("open");
  expect(details.querySelector("summary")).toHaveTextContent(
    "⬇️ Ingest a filing — add a company / year to the store",
  );

  const panel = openPanel();
  expect(panel.getByLabelText("Ingest a filing: Filing ticker")).toHaveAttribute(
    "id",
  );
  expect(panel.getByLabelText("Ingest a filing: Year")).toHaveAttribute("id");
  expect(panel.getByLabelText("Ingest a filing: Form")).toHaveAttribute("id");
});

test("announces pending ingest work in an independent live status", () => {
  const props = {
    locale: "en" as const,
    status: null,
    error: null,
    canRetry: false,
    canRetryPoll: false,
    onSubmit: vi.fn(),
    onRetry: vi.fn(),
    onRetryPoll: vi.fn(),
  };
  const { rerender } = render(
    <IngestPanel
      {...props}
      pending={false}
    />,
  );

  const panel = openPanel();
  const status = panel.getByRole("status");
  expect(status).toBeEmptyDOMElement();
  expect(status).toHaveAttribute("aria-live", "polite");
  expect(status).toHaveAttribute("aria-atomic", "true");

  rerender(<IngestPanel {...props} pending />);

  expect(panel.getByRole("status")).toBe(status);
  expect(status).toHaveTextContent("Submitting filing…");
});
