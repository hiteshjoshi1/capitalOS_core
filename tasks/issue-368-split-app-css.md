# Issue #368 part 2: split App.css by page

## Goal
`web/src/App.css` (7,315 lines) held most page styles and loads with every page. Move page styles next to their page, with no visual change.

## Change
- 300 of App.css's 1,070 rules moved into 14 route stylesheets (`web/src/routes/<Page>.css`, new except `AddFlow.css`), each imported right after `App.css` by its page. App.css: 7,315 → 5,284 lines.
- Moved by `scripts/split-app-css.mjs` (dry run without `--apply`), which moves a rule only when:
  - every class in its selector is used by exactly one source file, and that file imports App.css itself (so the page's CSS always loads after App.css);
  - no rule left in App.css *after* it styles the same elements (last selector part shares a class or element) and sets a property it sets. Moved rules load after App.css, so such a rule would otherwise start losing. Checked to a fixpoint.
  - `@media` blocks are kept around moved rules; rules moved into an existing page stylesheet go before its own rules.
- Kept in App.css: tokens, resets, the app shell, shared components and anything used by more than one file (e.g. classes shared by a page and a component it renders). Those can move later as components get their own stylesheets.

## Verification
- `make e2e-smoke` (production web container, 21 pages at 375px and 1440px): 45 passed with **zero** screenshot baseline changes.
- tsc, eslint, vitest (719), `make verify`.
