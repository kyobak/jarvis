# CLAUDE.md — Jarvis

Always-on desk assistant: fullscreen HUD on an old MacBook Air, webcam presence,
voice commands, calendar / music / messages. Full spec: `docs/JARVIS_PLAN.md` (Korean).
Work phase by phase (§12) and stop after each phase to report.

## Status
- Phase 0 (foundation) — done in code; **target-device check pending** (user runs `scripts/check_env.py`).
- Phase 1 (UI skeleton) — done in code; **idle CPU on target pending** (`scripts/measure_cpu.py`).
- Phase 2 (voice + brain) — done in code; **STT choice and 5 s latency on target pending**
  (`scripts/bench_stt.py`). Only tool so far: `get_status`.
- Next: Phase 3 (APScheduler reminders, Google OAuth, calendar). Reminder/schedule intents
  should get local fast paths in `brain/router.py` where the phrasing is fixed.

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
- Brain: local Korean intent router first (`brain/router.py`, whole-utterance regex, free);
  otherwise an LLM backend chosen by `llm.backend`:
  - `claude_code` (default): `claude -p` on the user's Pro/Max login, built-in tools off, Jarvis tools
    via the stdlib MCP bridge (`brain/mcp_bridge.py` → `/api/tools`, per-run bearer token).
    Claude Code needs macOS 13+ (binary minos 13.0, verified), so it cannot run on the target:
    the target uses `api` or `off`; `claude_code` is for the dev Mac.
  - `api`: Anthropic Python SDK 1.x `AsyncAnthropic`, manual tool loop, models from `llm.default_model`.
  - `off` / `mock`.
- Voice: sounddevice mic (80 ms / 16 kHz frames) → openWakeWord `hey_jarvis` → webrtcvad endpointing →
  STT engine (`voice/stt/`, chosen by benchmark) → brain → `say -v Yuna` rendered to WAV + `afplay`.
  Voice/STT packages are optional extras (`uv sync --extra voice --extra stt-faster`).
  Intel macOS 12 pins: onnxruntime <1.20, pywhispercpp <1.3 — don't bump them for the target.

## Layout
```
jarvis/
  main.py            entry point (`jarvis [run|enroll] --mock --dev --voice real|mock --llm … --stt … --no-window --windowed`)
  world.py           live world (real integrations land here phase by phase)
  core/              config, event_bus, state (sticky snapshot), status (StatusBoard), core_state
                     (voice phase + alert → visible core state), db, app (wiring), timeutil, korean
  brain/             brain.py (router → LLM, limits, retry), router.py, context.py, prompts.py,
                     tools.py (fixed registry), mcp_bridge.py, backends/{api,claude_code,simple}.py
  voice/             audio.py, vad.py (Endpointer), wakeword.py, tts.py, loop.py (VoiceLoop), stt/
  server/app.py      FastAPI: /ws, /api/health, /api/snapshot, /api/tools (token), /auth/{provider}, static ui/dist
  mocks/             data.py (fake content), world.py (fake integrations + dev controls)
  vision/ skills/    empty until their phase
ui/src/
  App.svelte, components/*.svelte, lib/{store.svelte.ts,clock.svelte.ts,coreRenderer.ts,types.ts,time.ts}
scripts/             check_env.py, measure_cpu.py, bench_stt.py, deploy.sh
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
uv run jarvis --mock --voice real --llm claude_code   # fake panels, real mic/speaker + subscription brain
uv run python scripts/bench_stt.py --synth && uv run python scripts/bench_stt.py
cd ui && npm run dev                     # Vite dev server on :5173, proxies /ws to :8765
```
Tests never call real Claude: backends are tested with a fake SDK client and a fake `claude` script.

## WebSocket protocol
Server → UI: `{"type": T, "payload": {...}}`. Sticky types (replayed on connect, see
`core/state.py`): `status, state, schedule, reminders, messages, now_playing, focus, drowsiness`.
Transient: `alert` (`active: false` clears), `transcript` (`{role, text, final, source?}`),
`level` (mic/TTS level, 12–20 Hz, lossy). `state` is published only by `core/core_state.py`
(plus the dev override), never directly by features.
UI → server: `ptt {down}`, `text {text}` (typed command), `alert_ack {id}`,
`dev {action, value}` (ignored unless mock/--dev).
Wire types live in `ui/src/lib/types.ts` — keep them in sync with the publishers.

## Rules
- User-facing text (UI, speech) in Korean; code, comments, commits in English.
- Never commit secrets. API keys/tokens go in `.env` (gitignored) or the macOS keychain (`keyring`).
- Server binds to loopback only (config validator enforces it).
- Integrations are **read-only** in v1: no sending mail/Slack, no calendar writes.
- Claude gets only the fixed tool list (plan §6.2, `brain/tools.py`) — never shell or generic tools.
  For `claude_code` that means `--tools ""` + `--strict-mcp-config` + `--allowedTools mcp__jarvis`; keep it.
  Message bodies are untrusted: summarisation calls run with tools disabled.
- Vision is 100% local; frames never leave memory, never touch disk (only face embeddings persist).
- Vision events and polling never call Claude.
- UI perf: no WebGL/Three.js, no `backdrop-filter`, no large `filter: blur`; animate only
  transform/opacity; canvas capped at 30 fps (20 idle); honour `prefers-reduced-motion`.
- No Marvel/Iron Man logos, assets, or fonts — original design only. Fonts are bundled locally
  (Pretendard for Korean, Chakra Petch for numerals) via `ui/scripts/copy-fonts.mjs`.
- Things the plan marks "needs verification" (§13) are decided by measuring on the target,
  then logged one line each in `docs/decisions.md`.
