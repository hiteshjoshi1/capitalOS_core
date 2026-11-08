# Issue 317: Header bell, and Alerts on the same list

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/317

## Objective
- One count for "what needs you", the same on every page and on a phone; Alerts can't disagree with the Data Hub (#309).

## Architecture Decisions
- `InboxBell` in the top bar (AppShell), reading `GET /operations/inbox` (#316) through the shared
  `operationsInbox` cache key, so the bell, the Data Hub Inbox and Alerts make one request and show one list.
  Desktop: a popover with up to 8 items (each links to its fix; refreshes link to the Data Hub). Phone: a link
  to the Data Hub Inbox. Labelled ("3 items need you"), 44px on touch.
- Alerts reads the same list (`lib/inbox.ts`: route and severity labels shared with the Inbox).
- Sidebar "Utilities / Alerts" removed (`UTILITY_NAV_ITEMS` empty); `/alerts` still works. The old
  `/alerts/*` endpoints stay (fields never removed) but the UI no longer calls them.

## Acceptance Criteria
- [x] Bell count = inbox count = Alerts list, one request (Alerts.test.tsx).
- [x] Phone: the bell links to the Data Hub with the same count; no overflow at 375px.
- [x] Sidebar has no Utilities/Alerts; e2e alerts spec on the inbox.

<!-- IMMUTABLE_PLAN_END -->
