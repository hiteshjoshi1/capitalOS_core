# Issue #368: split the biggest frontend files (part 1: lib/api.ts)

## Goal
`web/src/lib/api.ts` had grown to 2,570 lines (#130 §7.6). Split it by area with no behaviour change and no import site changes. App.css is the follow-up (part 2, still open on #368).

## Change
- `web/src/lib/api/http.ts`: API base, access token, refresh, `req`, errors (the old top of the file).
- `web/src/lib/api/types/<area>.ts`: the response/request types, 12 areas (common, system, auth, accounts, wealth, cashFlow, cards, ingest, crypto, marketData, dataHub, income).
- `web/src/lib/api/clients/<area>.ts`: each area's calls as `<area>Client`; `web/src/lib/api/client.ts` assembles the one `api` object from them.
- `web/src/lib/api/errors.ts`: `UploadRefusedError` and the 409 refusal parser.
- `web/src/lib/api.ts` is now a barrel exporting exactly the old public names (10 values, 159 types; `export type *` for the types), so every `import … from "../lib/api"` and every `vi.mock("../lib/api")` keeps working.
- The split was done by a script keyed on declaration and method names; the old `isAuthenticated` read the private token variable directly and now calls `getAccessToken()` (same value).
- No OpenAPI → TS generator (a new dev dependency needs Hitesh's okay).

## Checks
- Parity: a throwaway file importing every old public name (values and types) from `lib/api` typechecks; the 94 `api` methods are all present, none duplicated.
- `npx tsc -b`, `npx eslint .`, `npx vitest run`, `make verify`, `make e2e-smoke`.
