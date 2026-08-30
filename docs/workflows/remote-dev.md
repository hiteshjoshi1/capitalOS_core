# Remote Dev: Driving Claude Code on CapitalOS from a Phone

CapitalOS is local-first by design (see `AGENTS.md`) — Postgres, the
api container, and all seeded demo/dev data only exist on your home machine
via `docker-compose.yml`. There's no hosted/staging copy. That means "drive
Claude Code from my phone" splits into two genuinely different situations,
and this doc covers both rather than picking one.

**Not doing remote desktop / VNC**: Claude Code is a TUI with no GUI
dependency, and RDP/VNC is heavier, less secure by default, and doesn't
survive mobile network drops as gracefully as SSH+tmux (below). Skip it.

## Path 1: `claude.ai/code` (web) — no live stack needed

Use this when the task doesn't depend on the running Postgres/api containers,
local ports, or data already seeded on your machine — code review, planning,
docs, RAG config edits, anything you could equally do against a fresh clone.

What it actually is, confirmed against current product behavior (not
assumed, since this changes over time):

- Each session runs in an **isolated, Anthropic-managed cloud VM**, cloned
  fresh from this repo's GitHub remote (`origin` is already
  `github.com/hiteshjoshi1/capitalOS`, so this works with zero setup).
- **No network path to your home machine.** There's no VPN, port-forward, or
  bridging mechanism — a sandbox session cannot reach your local Postgres,
  your running containers, or `localhost:8000`/`:5173` on your laptop.
  Outbound internet access itself is restricted by an allowlist by default
  (package registries, GitHub, cloud SDKs), not open to arbitrary sites.
- Docker and Postgres binaries are pre-installed **inside the sandbox** and
  can be started fresh per session (`service postgresql start`, etc.) —
  but that's a throwaway instance seeded with nothing, not your real data.
  Running services don't carry over between sessions; only cached
  filesystem artifacts from a setup script do.
- Pushes go back through GitHub auth, same as pushing from a normal clone.

**When to reach for this**: quick asks from your phone that are really about
the code or docs, not about exercising the running app.

## Path 2: Tailscale + SSH + tmux to your home machine — needs the live stack

Use this for anything that needs the real Postgres data, the actual running
containers, or local ports — testing an ingestion job, checking real API
responses, anything where "restart from empty" (Path 1) isn't good enough.

1. **Tailscale on both ends.** Install and sign in to the same Tailscale
   account on your home machine and your phone — see
   [Tailscale's own setup docs](https://tailscale.com/kb/1017/install)
   rather than re-deriving their onboarding here. Once both devices are on
   the same tailnet, your phone can reach your home machine's SSH port by
   its Tailscale hostname/IP from anywhere, without opening anything on your
   home router.
2. **SSH client on the phone: [Termius](https://termius.com/).** Don't spend
   time comparing SSH apps — Termius handles key-based auth and reconnects
   cleanly on a flaky mobile connection, which is what actually matters here.
3. **tmux to survive the phone backgrounding.** A phone SSH app gets
   backgrounded or loses signal constantly; a plain SSH session dies with it
   and takes your Claude Code session along. tmux decouples the running
   session from the SSH connection, so it survives both:
   ```bash
   tmux new -s capitalos      # first connection: start a named session
   tmux attach -t capitalos   # reconnecting later (phone or laptop): reattach to it
   ```
   Start Claude Code inside the tmux session once, then just reattach on
   every future connection — from the phone or later from a laptop, since
   the session isn't tied to either device.
4. **Once connected, nothing about CapitalOS itself changes** — this path
   only changes how you reach the terminal. Run it the same way described in
   `CLAUDE.md`: `make up`, then the demo login (`demo` / `Test@1234`), API at
   `http://localhost:8000` (`curl http://localhost:8000/health`), web at
   `http://localhost:5173`.

**When to reach for this**: anything Path 1 can't do — real data, real
containers, real ports.

## Which one?

| Need | Path |
|---|---|
| Code review, planning, docs, non-DB-dependent edits | Web (`claude.ai/code`) |
| Real Postgres data, running containers, local ports | Tailscale + SSH + tmux |

For the actual run/verify commands once you're connected either way, see
`CLAUDE.md` (quickstart) and the `run`/`verify` project skills — this doc is
only about how you reach the terminal, not what to run once you're there.
