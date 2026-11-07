import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

// #150, #254 (D-46, D-69): formatting lives in lib/format.ts and lib/chartColors.ts only.
// This guard stops page-local copies (browser-locale toLocaleString, toFixed money and
// percentages, Intl formatters, hand-built "S$"/"$" prefixes, per-page currency option
// lists and palettes) from creeping back.
const SRC = resolve(__dirname, "..");
const ALLOWED = new Set([join(SRC, "lib", "format.ts"), join(SRC, "lib", "chartColors.ts")]);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "__tests__" ? [] : sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

const RULES: [string, RegExp][] = [
  ["browser-locale toLocaleString/toLocaleDateString/toLocaleTimeString", /\.toLocale(Date|Time)?String\(/],
  ["an Intl number or date formatter", /Intl\.NumberFormat|new Intl\.DateTimeFormat|Intl\.DateTimeFormat\([^)]/],
  ["a hand-built S$ prefix", /===\s*"SGD"\s*\?\s*"S\$"/],
  ["a hand-built $ prefix", /`\$\$\{|"\$"\s*\+|"S\$ ?"\s*\+/],
  ["a hard-coded currency <option> list", /<option value="SGD">/],
  ["a per-page currency state", /useState(<string>)?\("SGD"\)/],
  ["a page-local chart palette", /const [A-Z_]*COLORS\s*=\s*\[/],
];

/**
 * `toFixed` is only for CSS geometry: a width/offset/gradient stop inside a style or a
 * gradient (`width: `${pct.toFixed(1)}%``, `parts.push(`${color} ${a.toFixed(2)}% ...`)`).
 * Any other use (money, a percentage people read, a CSV cell) goes through lib/format.ts.
 */
const CSS_CONTEXT = /style=\{|\b(width|left|top|height):|parts\.push\(/;
function nonCssToFixed(line: string): boolean {
  const all = line.match(/\.toFixed\(/g)?.length ?? 0;
  if (all === 0) return false;
  const css = line.match(/\.toFixed\(\d\)\}%/g)?.length ?? 0;
  return css !== all || !CSS_CONTEXT.test(line);
}

function offendersOf(test: (source: string) => boolean): string[] {
  return sourceFiles(SRC)
    .filter((file) => !ALLOWED.has(file))
    .filter((file) => test(readFileSync(file, "utf8")))
    .map((file) => file.slice(SRC.length + 1));
}

describe("formatting guard", () => {
  for (const [what, pattern] of RULES) {
    it(`no ${what} outside lib/format`, () => {
      expect(offendersOf((source) => pattern.test(source))).toEqual([]);
    });
  }

  it("no toFixed outside lib/format except CSS geometry", () => {
    const offenders = sourceFiles(SRC)
      .filter((file) => !ALLOWED.has(file))
      .flatMap((file) =>
        readFileSync(file, "utf8")
          .split("\n")
          .map((line, i) => ({ line, at: `${file.slice(SRC.length + 1)}:${i + 1}` }))
          .filter(({ line }) => nonCssToFixed(line))
          .map(({ at, line }) => `${at}: ${line.trim()}`),
      );
    expect(offenders).toEqual([]);
  });

  it("tells CSS geometry from displayed numbers", () => {
    expect(nonCssToFixed('<span style={{ width: `${pct.toFixed(1)}%` }} />')).toBe(false);
    expect(nonCssToFixed("parts.push(`${color} ${a.toFixed(2)}% ${b.toFixed(2)}%`);")).toBe(false);
    expect(nonCssToFixed("Cash {pct.toFixed(1)}%")).toBe(true);
    expect(nonCssToFixed("return `${percent.toFixed(1)}%`;")).toBe(true);
    expect(nonCssToFixed("amount.toFixed(2),")).toBe(true);
    expect(nonCssToFixed('<span style={{ color }}>{amount.toFixed(2)}</span>')).toBe(true);
  });
});
