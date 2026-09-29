# CLAUDE.md — Jarvis

Always-on desk assistant: fullscreen HUD on an old MacBook Air, webcam presence,
voice commands, calendar / music / messages. Full spec: `docs/JARVIS_PLAN.md` (Korean).
Work phase by phase (§12) and stop after each phase to report.

## Status
- Phase 0 (foundation) — done in code; **target-device check pending** (user runs `scripts/check_env.py`).
- Phase 1 (UI skeleton) — done in code; **idle CPU on target pending** (`scripts/measure_cpu.py`).
- Next: Phase 2 (wake word, VAD, STT benchmark, Claude tool use, TTS).

## Machines
- Dev: user's Apple Silicon MacBook, latest macOS.
- Target: MacBook Air Early 2015 — Intel i5 dual-core, 8 GB, HD 6000, **macOS 12 Monterey**, 1440×900.
  Budgets: ≤1.5 GB RSS, ≤40% avg CPU incl. vision, idle UI ≤10% CPU.
- Everything hardware/external must have a `--mock` substitute; the full app must run on the dev Mac.

## Stack
- Python 3.12 (python.org installer on target), `uv`. Single asyncio process:
  FastAPI + uvicorn (WebSocket), pywebview (WKWebView) fullscreen window.
- UI: Vite + Svelte 5 + TypeScript, Canvas 2D + CSS/SVG. Build target `safari15`.
- Storage: SQLite at `~/Library/Application Support/Jarvis/jarvis.db` (`JARVIS_DATA_DIR` overrides).
- LLM: Anthropic Python SDK only (Phase 2+). Models come from `config.yaml` (`llm.default_model`, `llm.smart_model`).

## Layout
```
jarvis/
  main.py            entry point (`jarvis [run|enroll] --mock --dev --no-window --windowed`)
  world.py           live world (real integrations land here phase by phase)
  core/              config.py, event_bus.py, state.py (sticky snapshot), db.py, app.py, timeutil.py
  server/app.py      FastAPI: /ws, /api/health, /api/snapshot, /auth/{provider}, static ui/dist
  mocks/             data.py (fake content), world.py (fake integrations + dev controls)
  voice/ brain/ vision/ skills/   empty until their phase
ui/src/
  App.svelte, components/*.svelte, lib/{store.svelte.ts,clock.svelte.ts,coreRenderer.ts,types.ts,time.ts}
scripts/             check_env.py, measure_cpu.py, deploy.sh
docs/                setup.md (user guide, Korean), decisions.md (verification log)
tests/               pytest
```

## Commands
```bash
uv sync                                  # Python deps (+ dev group)
uv run pytest                            # backend tests
cd ui && npm install && npm run build    # UI → ui/dist (served by FastAPI)
cd ui && npm run check                   # svelte-check / TypeScript
uv run jarvis --mock                     # full app, fake everything, dev shortcuts on
uv run jarvis --mock --no-window         # server only → http://127.0.0.1:8765
cd ui && npm run dev                     # Vite dev server on :5173, proxies /ws to :8765
```

## WebSocket protocol
Server → UI: `{"type": T, "payload": {...}}`. Sticky types (replayed on connect, see
`core/state.py`): `status, state, schedule, reminders, messages, now_playing, focus, drowsiness`.
Transient: `alert` (`active: false` clears), `transcript`, `level` (20 Hz audio level, lossy).
UI → server: `ptt {down}`, `alert_ack {id}`, `dev {action, value}` (ignored unless mock/--dev).
Wire types live in `ui/src/lib/types.ts` — keep them in sync with the publishers.

## Rules
- User-facing text (UI, speech) in Korean; code, comments, commits in English.
- Never commit secrets. API keys/tokens go in `.env` (gitignored) or the macOS keychain (`keyring`).
- Server binds to loopback only (config validator enforces it).
- Integrations are **read-only** in v1: no sending mail/Slack, no calendar writes.
- Claude gets only the fixed tool list (plan §6.2) — never shell or generic tools.
  Message bodies are untrusted: summarisation calls run with tools disabled.
- Vision is 100% local; frames never leave memory, never touch disk (only face embeddings persist).
- Vision events and polling never call Claude.
- UI perf: no WebGL/Three.js, no `backdrop-filter`, no large `filter: blur`; animate only
  transform/opacity; canvas capped at 30 fps (20 idle); honour `prefers-reduced-motion`.
- No Marvel/Iron Man logos, assets, or fonts — original design only. Fonts are bundled locally
  (Pretendard for Korean, Chakra Petch for numerals) via `ui/scripts/copy-fonts.mjs`.
- Things the plan marks "needs verification" (§13) are decided by measuring on the target,
  then logged one line each in `docs/decisions.md`.
