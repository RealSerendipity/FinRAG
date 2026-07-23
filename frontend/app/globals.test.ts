import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, test } from "vitest";

const css = readFileSync(resolve("app/globals.css"), "utf8");

describe("responsive visual contract", () => {
  test("keeps the reference desktop geometry and palette", () => {
    expect(css).toContain("--background: #0e1117");
    expect(css).toContain("--sidebar: #262730");
    expect(css).toContain("--text: #fafafa");
    expect(css).toContain("--accent: #ff4b4b");
    expect(css).toContain("grid-template-columns: 300px minmax(0, 1fr)");
    expect(css).toContain("max-width: 736px");
    expect(css).toContain("padding: 96px 16px 64px");
    expect(css).toContain("font-size: 44px");
    expect(css).toContain("line-height: 52.8px");
  });

  test("switches to mobile settings and one-column content at 800px", () => {
    expect(css).toContain("@media (max-width: 800px)");
    expect(css).toMatch(
      /\.desktop-sidebar\s*\{\s*display:\s*none;/,
    );
    expect(css).toMatch(
      /\.mobile-settings\s*\{\s*display:\s*block;/,
    );
    expect(css).toContain("padding: 24px 16px 48px");
  });

  test("defines light, dark, focus, and reduced-motion behavior", () => {
    expect(css).toContain("--background: #ffffff");
    expect(css).toContain("--sidebar: #f0f2f6");
    expect(css).toContain("--text: #31333f");
    expect(css).toContain("--border: #d5d8dd");
    expect(css).toContain("@media (prefers-color-scheme: dark)");
    expect(css).toContain(":focus-visible");
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
  });
});
