import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * #268 guards (no axe-core, D-47): text colour tokens meet WCAG AA (4.5:1) on both themes'
 * backgrounds, status pills meet it on their own tint, and no labelled <div>/<span> lacks a
 * role (an aria-label on a role-less div is ignored by screen readers).
 */
const SRC = resolve(__dirname, "..");
const CSS = readFileSync(join(SRC, "App.css"), "utf8");

type RGB = [number, number, number];

function block(selector: string): string {
  const start = CSS.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`no ${selector} block`);
  return CSS.slice(start, CSS.indexOf("}", start));
}

function tokens(selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of block(selector).matchAll(/--([\w-]+):\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}

const DARK = tokens(":root");
const LIGHT = { ...DARK, ...tokens('[data-theme="light"]') };

function oklchToRgb(l: number, c: number, hDeg: number): RGB {
  const h = (hDeg * Math.PI) / 180;
  const a = c * Math.cos(h);
  const b = c * Math.sin(h);
  const l_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m_ = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s_ = (l - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const lin = [
    4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
    -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
    -0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_,
  ];
  return lin.map((x) => {
    const v = Math.min(Math.max(x, 0), 1);
    return 255 * (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055);
  }) as RGB;
}

/** A colour token as sRGB, resolving var(); rgba() is laid over `under`. */
function color(value: string, theme: Record<string, string>, under: RGB = [255, 255, 255]): RGB {
  const v = value.trim();
  const ref = /^var\(--([\w-]+)\)$/.exec(v);
  if (ref) return color(theme[ref[1]], theme, under);
  if (v.startsWith("#")) {
    const hex = v.length === 4 ? v.slice(1).split("").map((x) => x + x).join("") : v.slice(1, 7);
    return [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16)) as RGB;
  }
  const ok = /^oklch\(([\d.]+)%\s+([\d.]+)\s+([\d.]+)\)/.exec(v);
  if (ok) return oklchToRgb(Number(ok[1]) / 100, Number(ok[2]), Number(ok[3]));
  const rgba = /^rgba?\(([^)]+)\)/.exec(v);
  if (rgba) {
    const [r, g, b, a = 1] = rgba[1].split(/[\s,/]+/).filter(Boolean).map(Number);
    return mix([r, g, b], under, a);
  }
  throw new Error(`unparsed colour ${v}`);
}

const mix = (top: RGB, bottom: RGB, share: number): RGB => top.map((x, i) => x * share + bottom[i] * (1 - share)) as RGB;

function ratio(fg: RGB, bg: RGB): number {
  const lum = (c: RGB) => {
    const [r, g, b] = c.map((x) => {
      const s = x / 255;
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const [hi, lo] = [lum(fg), lum(bg)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const THEMES = { dark: DARK, light: LIGHT } as const;

describe("colour contrast (#268, WCAG AA 4.5:1)", () => {
  for (const [name, theme] of Object.entries(THEMES)) {
    const page = color(theme.bg, theme);
    const surfaces = { bg: page, panel: color(theme.panel, theme, page), panel2: color(theme.panel2, theme, page) };
    for (const text of ["text", "muted", "good", "bad", "warn"]) {
      for (const [surface, bg] of Object.entries(surfaces)) {
        it(`${name}: --${text} on --${surface}`, () => {
          expect(ratio(color(theme[text], theme), bg)).toBeGreaterThanOrEqual(4.5);
        });
      }
    }

    for (const tone of ["good", "warn", "bad"]) {
      it(`${name}: .statusPill--${tone} text on its tint`, () => {
        const rule = block(`.statusPill--${tone}`);
        const tint = Number(new RegExp(`var\\(--${tone}\\) (\\d+)%`).exec(rule)?.[1]) / 100;
        const toneColor = color(theme[tone], theme);
        const bg = mix(toneColor, surfaces.panel, tint);
        let fg = toneColor;
        const override = name === "light" && CSS.includes(`[data-theme="light"] .statusPill--${tone} {`)
          ? /(\d+)%, black/.exec(block(`[data-theme="light"] .statusPill--${tone}`))
          : null;
        if (override) fg = mix(toneColor, [0, 0, 0], Number(override[1]) / 100);
        expect(ratio(fg, bg)).toBeGreaterThanOrEqual(4.5);
      });
    }
  }
});

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return entry === "__tests__" ? [] : sourceFiles(path);
    return /\.tsx$/.test(entry) && !/\.test\.tsx$/.test(entry) ? [path] : [];
  });
}

describe("labels screen readers can use (#268)", () => {
  it("no <div>/<span> has an aria-label without a role", () => {
    const offenders: string[] = [];
    for (const file of sourceFiles(SRC)) {
      const text = readFileSync(file, "utf8");
      for (const m of text.matchAll(/<(div|span)\b((?:[^>]|=>)*?)>/g)) {
        if (m[2].includes("aria-label=") && !m[2].includes("role=")) {
          offenders.push(`${relative(SRC, file)}:${text.slice(0, m.index).split("\n").length}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("an aria-hidden element is never also role=img", () => {
    const offenders = sourceFiles(SRC).filter((file) =>
      /role="img"\s+aria-hidden="true"|aria-hidden="true"\s+role="img"/.test(readFileSync(file, "utf8")),
    );
    expect(offenders).toEqual([]);
  });
});
