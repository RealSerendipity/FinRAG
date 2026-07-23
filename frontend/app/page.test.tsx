import { render, screen } from "@testing-library/react";
import Page from "./page";

test("renders the finrag heading", () => {
  render(<Page />);
  expect(screen.getByRole("heading", { name: /finrag/i })).toBeInTheDocument();
});
