# Issue 91: Run CapitalOS's host tooling on patched Node 22.23.4 and Python 3.13.16

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/91

## Objective
- CapitalOS's host processes (Vite dev servers, npm, Playwright, the orchestration venv) run on patched runtimes, without changing the machine-wide defaults InvestOS shares.

## Architecture Decisions
- `.nvmrc` 22.23.4; the Makefile prepends that nvm version's bin to PATH when installed. CI's setup-node reads `.nvmrc`.
- CPython 3.13.16 managed by uv in `~/.capitalos/python` (`--no-bin`; uv only discovers its own default dir, so other projects never pick it up); `PYTHON` defaults to it.
- `make host-tools` installs both, saving and restoring nvm's aliases: `nvm install` of an LTS release rewrites `alias/lts/<line>`, which would move the shared default (it did once, for about a minute, before this guard).
- Python 3.13.16 not .18: the shared uv (0.12.23) offers up to .16; upgrading uv is a shared-tool change.

## Acceptance Criteria
- [x] `make where` shows node v22.23.4 / python 3.13.16 (CapitalOS); nvm default still resolves to v22.17.0 after `make host-tools`.
- [x] `make verify`, Playwright e2e 14, orchestration 201 (venv on 3.13.16); orchestration lock identical under 3.13.16.
- [ ] Main checkout after merge: `make host-tools`, `make orch-bootstrap`, restart `make web-up`.

## How To Test
- `make host-tools && make where`.

<!-- IMMUTABLE_PLAN_END -->
