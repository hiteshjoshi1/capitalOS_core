import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

// #150: formatting lives in lib/format.ts and lib/chartColors.ts only. This guard stops
// page-local copies (browser-locale toLocaleString, hand-built "S$" prefixes, per-page
// currency option lists and palettes) from creeping back.
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
  ["browser-locale toLocaleString/toLocaleDateString", /\.toLocale(Date)?String\(/],
  ["a hand-built S$ prefix", /===\s*"SGD"\s*\?\s*"S\$"/],
  ["a hard-coded currency <option> list", /<option value="SGD">/],
  ["a per-page currency state", /useState(<string>)?\("SGD"\)/],
  ["a page-local chart palette", /const [A-Z_]*COLORS\s*=\s*\[/],
];

describe("formatting guard", () => {
  for (const [what, pattern] of RULES) {
    it(`no ${what} outside lib/format`, () => {
      const offenders = sourceFiles(SRC)
        .filter((file) => !ALLOWED.has(file))
        .filter((file) => pattern.test(readFileSync(file, "utf8")))
        .map((file) => file.slice(SRC.length + 1));
      expect(offenders).toEqual([]);
    });
  }
});
