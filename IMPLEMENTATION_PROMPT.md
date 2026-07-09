Paste this into Sonnet (Claude Code) or Codex, in the root of the CapitalOS `web/` codebase, alongside this handoff folder.

---

## Prompt

I'm handing you a design handoff for seven screens: the full Data Hub section (`Data Hub Overview.dc.html`, `Import Statements.dc.html`, `Add Accounts.dc.html`, `Add Platforms.dc.html`, `Add Crypto Wallets.dc.html`, `Market Data.dc.html`) and the Stocks screen from Wealth (`Stock Holdings.dc.html`). Read `README.md` in this folder first — it documents exact layout, behavior, copy, and design tokens (already defined in our `App.css`, nothing new to add). Then open each `.dc.html` file in `screens/` in a browser to see the live interactive reference (plain HTML/CSS/JS prototypes with mock data — a visual/behavioral reference, not code to copy).

**Your task:** recreate these seven screens as production UI in this codebase, using our existing React/TypeScript stack, `PageShell`, `Sidebar`/`AppShell`, and the CSS-variable theme already in `App.css` — not the prototypes' inline-styled markup. Match pixel-accurately (layout, spacing, type, color, radii, shadows) but implement the way this codebase already builds screens — check the closest existing routes/components for patterns to follow before inventing new ones.

### Step 1 — Data Hub Overview
Build (or replace) the Data Hub landing page: 4 status stat cards, 5 quick-action cards linking to the other five Data Hub screens, and a recent-activity timeline. Wire the stats to real aggregate data per the README's Data Requirements — flag any stat that needs a new summary endpoint rather than silently faking it.

### Step 2 — Import Statements
Build the upload flow: account picker, dropzone, upload button, an import-report panel (stat chips, skipped-row warning, 3-row preview) that appears after a successful parse, and a recent-imports history list. Wire to the existing statement-parsing pipeline; surface parse-job stats and a preview slice as described in the README.

### Step 3 — Add Accounts & Add Platforms
Build both as single-column create forms (see README for exact fields) each with a directory list below and a transient success state after submit. Cross-link "+ Add platform" from the Add Accounts form to Add Platforms. These are straightforward CRUD against accounts/platforms tables.

### Step 4 — Add Crypto Wallets
Build the two-column connect-wallet + connected-wallets-list layout, reusing the existing wallet sign-and-verify flow (EVM/Solana chain switch) — restyle only, no new connection logic. Add the token allowlist section (add-token form + allowlist table) — flag whether an allowlisted-ERC-20-contracts table already exists or needs to be created. Implement the mobile notice (desktop-only wallet connection) exactly as described.

### Step 5 — Market Data
Build the exchange-status list with expand-in-place per-symbol detail, the 4 status chips, "Refresh all quotes" action, and the recent-runs history table. Confirm with me whether per-symbol stale reasons ("Rate limited", "No trade reported") are already persisted by the refresh worker — if not, that's a backend change to flag, not something to fabricate client-side.

### Step 6 — Stocks
Build the hero value card (with refresh-quotes action + freshness note), the geography/platform exposure donuts, the 6-month trend bar chart, and the top-holdings table (capped at 8, "View all 42 holdings" link — wire that to wherever the full holdings list should live, ask me if that page doesn't exist yet). Reuse any existing donut/bar-chart primitives from Cash Flow or Credit Cards if they already exist in `web/src/components/dashboard/`; build once and share if not.

### Step 7 — Shared pieces to extract (if they don't already exist)
- A "success banner" pattern (dot + text, auto-dismiss) — used in Add Accounts, Add Platforms, Add Crypto Wallets. Should be one shared component, not duplicated three times.
- A "status pill" helper (Fresh/Stale/Completed/Needs mapping/etc., each with its own color) — reused across Market Data, Stocks, Import Statements.
- Directory-list row pattern (name/meta on the left, status on the right) — reused across Add Accounts, Add Platforms, Add Crypto Wallets.

### Step 8 — Data / backend flags (don't silently stub)
Go through the README's "Data Requirements / Backend Work Needed" section point by point and flag anything that needs new backend work rather than quietly faking it with mock data in the shipped app.

### Step 9 — QA
Diff each screen against its `.dc.html` reference at ~1440px and ~390px widths for spacing/color/type fidelity, and confirm dark/light theme parity on all seven.

Ask me before making product decisions the README flags as undesigned (e.g. what "View all 42 holdings" should link to, whether per-symbol stale reasons exist server-side, what the allowlisted-token add flow should validate) — don't invent scope silently.
