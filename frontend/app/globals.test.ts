import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, test } from "vitest";

const css = readFileSync(resolve("app/globals.css"), "utf8");

function relativeLuminance(hex: string): number {
  const channels = hex
    .slice(1)
    .match(/.{2}/g)!
    .map((channel) => Number.parseInt(channel, 16) / 255)
    .map((channel) =>
      channel <= 0.04045
        ? channel / 12.92
        : ((channel + 0.055) / 1.055) ** 2.4,
    );
  // WCAG weights account for human sensitivity to each RGB channel.
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrast(first: string, second: string): number {
  const [lighter, darker] = [
    relativeLuminance(first),
    relativeLuminance(second),
  ].sort((left, right) => right - left);
  return (lighter + 0.05) / (darker + 0.05);
}

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

  test("uses contrast-safe semantic tokens for actions, links, and focus", () => {
    expect(css).toContain("--primary: #d93636");
    expect(css).toContain("--primary-hover: #c92d2d");
    expect(css).toContain("--link: #b42318");
    expect(css).toContain("--radius: 8px");
    expect(css).toContain("--link: #ff8f8f");
    expect(css).toContain("background: var(--primary)");
    expect(css).toContain("background: var(--primary-hover)");
    expect(css).toContain("color: var(--link)");
    expect(css).toContain("outline: 3px solid var(--focus)");
    expect(css).not.toContain("color-mix(in srgb, var(--focus)");

    expect(contrast("#ffffff", "#d93636")).toBeGreaterThanOrEqual(4.5);
    expect(contrast("#ffffff", "#c92d2d")).toBeGreaterThanOrEqual(4.5);
    expect(contrast("#ffffff", "#b42318")).toBeGreaterThanOrEqual(4.5);
    expect(contrast("#0e1117", "#ff8f8f")).toBeGreaterThanOrEqual(4.5);
    for (const background of ["#ffffff", "#f0f2f6"]) {
      expect(contrast(background, "#b42318")).toBeGreaterThanOrEqual(3);
    }
    for (const background of ["#0e1117", "#262730"]) {
      expect(contrast(background, "#ff8f8f")).toBeGreaterThanOrEqual(3);
    }
  });
});
