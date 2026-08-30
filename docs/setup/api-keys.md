# Setting up your integrations: what to configure, and how

CapitalOS works fully with **zero** API keys — log in as the demo user (or
register your own), see the dashboard, and manually upload account
statements (CSV/XLS) — nothing below is required for that. This doc is a
checklist for turning on *automatic* syncing for each integration instead.

**How to apply changes**: edit `.env` at the repo root, then rebuild so the
running container actually picks it up —

```bash
make api-rebuild
```

Docker does not hot-reload `.env`. If you change a key and nothing seems
different, this is almost always why — the old value is still what's
running until you rebuild.

---

## 1. IBKR (Interactive Brokers) — automatic statement sync

Skip this and use manual upload instead (`POST /ingest/ibkr` via the Ingest
page, no keys needed) if you'd rather not do the Flex Query setup.

This is **one set of credentials for one real IBKR account**, shared by the
whole deployment — there's no per-user IBKR key. You must set an explicit
owner or sync refuses to run for anyone (see why below).

**Set:**
```bash
IBKR_FLEX_TOKEN=...
IBKR_FLEX_QUERY_ID=...
IBKR_FLEX_USERNAME=...   # required — the one CapitalOS user allowed to use this
```

**How to get the token/query ID** (from your own IBKR account, not a
third-party site):
1. IBKR **Client Portal** → **Performance & Reports** → **Flex Queries**.
2. Create an **Activity Flex Query**, enable these sections (the first two
   are required — import fails without them; the rest are what CapitalOS
   reads):
   - **Change in NAV** / **Equity Summary by Report Date in Base Currency** — required
   - **Open Positions** — required whenever you hold anything
   - **Base Currency Exchange Rate** (conversion rates) — required if anything isn't already in your base currency
   - **Cash Report**, **Statement of Funds**, **Trades**, **Corporate Actions**
3. Date period **Last 365 days** (or your preference), format **XML**, version 3.
4. Save it → the **Query ID** shown in the list is `IBKR_FLEX_QUERY_ID`.
5. **Settings** → **Flex Web Service** → generate a token → `IBKR_FLEX_TOKEN`.
   Tokens expire periodically; regenerate and update `.env` when that happens.

**Why `IBKR_FLEX_USERNAME` is required, not optional**: without it, *any*
user in the app — including the public demo account — could trigger a pull
of your real statement into their own records just by having an account on
platform "IBKR" and clicking refresh. Verified: tested both branches
directly — the configured owner resolves and succeeds, any other user is
rejected with a clear error.

**Verified working** (2026-08): real token/query ID tested end-to-end,
returned a real Flex statement successfully.

## 2. Coinbase — daily wallet sync

**Set:**
```bash
COINBASE_KEY_ID=organizations/{org_id}/apiKeys/{key_id}
COINBASE_KEY_SECRET="-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----\n"
COINBASE_USERNAME=...   # must match your CapitalOS username, required (see below)
```
Generate a **view-only** Advanced Trade API key from the Coinbase Developer
Platform. `COINBASE_KEY_SECRET` needs `\n`-escaped newlines if it's on one
line in `.env`.

**Why `COINBASE_USERNAME` is required, not optional**: same reasoning as
IBKR — without an explicit owner, the sync job falls back toward a default
user ID, which could point at the demo account. Verified: misconfiguration
now fails loudly instead of silently defaulting to user 1.

**Verified working** (2026-08): real key tested directly against the
Coinbase API, returned real account data successfully.

## 3. Crypto wallet tracking — EVM chains

Wallet holdings sync is all-or-nothing per chain family — no free fallback,
so without a key it just fails when you try to sync. Set **one** of:

```bash
MORALIS_API_KEY=...   # recommended
# or
ALCHEMY_API_KEY=...
```
[moralis.io](https://moralis.io/) or [alchemy.com](https://www.alchemy.com/),
both free tier. Covers Ethereum, Arbitrum, Base, Optimism, Mantle, Scroll.

**Verified working** (2026-08): both tested directly against a real wallet
address — identical results (native balance + 24 tokens) from either.
Kept Moralis as the single recommended key since it's the default
first-choice provider and its adapter also returns per-token USD prices,
which Alchemy's adapter doesn't.

Optionally narrow which chains get synced with `CRYPTO_EVM_CHAINS`
(comma-separated; default is all six: `ethereum,base,arbitrum,optimism,
mantle,scroll`). Fewer chains means fewer API calls per sync — worth
setting if you only actually hold assets on some of them. Verified: setting
it to a 5-chain subset correctly excluded the sixth from sync.

## 4. Crypto wallet tracking — Solana

```bash
HELIUS_API_KEY=...
```
[helius.dev](https://www.helius.dev/), free tier. Required specifically for
the scheduled holdings/snapshot sync that powers the crypto dashboard
numbers. (Basic wallet-verification RPC calls already fall back to the free
public `api.mainnet-beta.solana.com` endpoint with no key — `SOLANA_RPC_URL`
/ `HELIUS_RPC_URL` let you point that specific path at a different RPC
provider if you want, but they don't substitute for `HELIUS_API_KEY`.)

**Verified working** (2026-08): tested directly against a real Solana
address, returned real holdings.

## 5. Stock/ETF prices — Yahoo (built in, no key)

Nothing to configure — `yfinance`/Yahoo is the default, keyless fallback
for every exchange. **Treat it as a last resort, not something to rely on
for volume**: it's an unofficial, undocumented endpoint (not a real public
API), and it rate-limits aggressively and unpredictably — verified directly
this session: even a single request got a `429 Too Many Requests` after
enough prior traffic, regardless of how many symbols were batched into the
request. There's no reliable fix for that at the code level; it's inherent
to using a scraped endpoint with no SLA.

## 6. Stock/ETF prices — Finnhub (recommended if you hold US stocks)

```bash
FINNHUB_API_KEY=...
```
[finnhub.io/register](https://finnhub.io/register), free tier. Tried first
for US-exchange symbols, ahead of the flaky Yahoo fallback above.

**Verified working** (2026-08): with a real key, refreshed 24/24 US symbols
successfully in one run — fixed every US symbol that Yahoo's rate limiting
had left stale. Worth setting if you hold more than a couple of US
positions.

## 7. Stock/ETF prices — EODHD (optional alternate provider)

```bash
EODHD_API_KEY=...
```
Not in the default provider chain — only used if you set
`STOCK_PROVIDER_CHAIN_US` / `STOCK_PROVIDER_CHAIN_NON_US` to include
`eodhd`. **Verified working** (2026-08): tested directly with a real key,
returned real price data (a few days delayed on the free tier compared to
Finnhub).

---

## Keys considered and removed

**`EODDATA_API_KEY`** — removed 2026-08, along with the `EODDataProvider`
code path in `api/app/market_data/providers.py` and its wiring in
`api/app/market_data/service.py`. Tested directly with a real key: the key
itself authenticates correctly (not an invalid-credentials error), but the
account's plan returns `"This Exchange is not available at your membership
level"` for every exchange this deployment needs (US and HK both confirmed
blocked). Since it wasn't in the default provider chain anyway and provided
no working coverage, we removed the key and the code rather than carry a
documented-but-non-functional integration — a config option that looks
available but silently can't work is worse than no option at all. If your
EODData plan covers exchanges you need, this would need to be re-added.

Everything else documented above has been tested against the real provider
and confirmed working, as of the "Verified working" dates next to each. If
a key is later found to be unreliable or defunct for your account, it
belongs here too, along with removing the code path that calls it.

---

## Everything else

Auth (`AUTH_ACCESS_TOKEN_SECRET`), CORS, and misc timing/threshold vars are
covered inline in `.env.example` — none of them are required for local use.
There is currently no in-app "which integrations are configured" screen —
this doc plus `.env.example`'s comments are the source of truth.
