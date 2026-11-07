# Issue 268: Accessibility basics

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/268

## Objective
- Charts readable by screen readers, a working skip link, text at WCAG AA contrast, and ▲/▼ beside
  every red/green change, on every page (builds on D-47, #151/#199).

## Architecture Decisions
- Audit first: a throwaway Playwright probe over 14 pages × both themes (demo data) for text contrast,
  role=img without data, aria-label on role-less elements, and good/bad-coloured numbers without a sign.
- Fixes found by it:
  - Light `.statusPill--warn/--bad` text was 4.07:1 on its tint: a darker shade of the same token
    (`color-mix(.., 80%, black)`). Dark `.statusPill--bad` was 4.48:1: its tint goes 16% → 12%.
  - `ValueTrendChart`'s bars had `role="img"` and `aria-hidden` together: role dropped (the labelled
    wrapper with its data description stays).
  - aria-label on role-less divs/spans (ignored by screen readers): role="group" / "status" / "img"
    (freshness chips, column picker, cash-flow unavailable, alerts list/cards/empty, hero delta row,
    cash bridge, merchants and crypto exposure cards, sidebar alert badge).
  - Colour-only changes outside `<Delta>`: `DeltaArrow` (exported from Delta.tsx, same glyph markup) on
    the History drill-down (delta, waterfall, movers), Cash Flow drivers, Stocks P&L (table + mobile).
    Zero P&L is neutral, not green.
- Guards (no axe-core, D-47): `__tests__/a11yGuard.test.ts` computes contrast from App.css tokens
  (hex/oklch/rgba) for text/muted/good/bad/warn on bg/panel/panel2 and each status pill on its tint, both
  themes; and fails on any `<div>/<span>` with aria-label but no role, or role=img + aria-hidden.
- Skip link: already present (#151); checked it shows on first Tab and moves focus to #main-content.
- Left alone: Dividends hero "Quarter/Year-to-date" totals are coloured green but are totals, not changes;
  #267 (Income page) reworks that page.

## Acceptance Criteria
- [x] Probe: 0 contrast failures, 0 unlabelled charts, 0 role-less labels, both themes, 14 pages.
- [x] Skip link visible on focus, lands on the content.
- [x] Every good/bad-coloured change shows ▲/▼ (or is a total/status with its meaning in text).

## How To Test
- `cd web && npx vitest run src/__tests__/a11yGuard.test.ts src/__tests__/Delta.test.tsx`

<!-- IMMUTABLE_PLAN_END -->
