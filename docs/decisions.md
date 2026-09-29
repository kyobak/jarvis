# 결정 기록

검증이 필요했던 항목(계획서 §13)과 기술 선택을 한 줄씩 기록합니다. 형식: `날짜 — 항목: 결정 (근거)`

## Phase 0–1

- 2026-09-29 — LLM 모델 ID: 기본 `claude-haiku-4-5`, 고급 `claude-sonnet-5-5` (계획서의 `claude-sonnet-5`는 이전 세대. 현재 Sonnet 라인은 5.5이고 가격이 같음. `config.yaml`에서 변경 가능)
- 2026-09-29 — Sonnet 5.5 주의사항(Phase 2 반영): `thinking: {type: "disabled"}`와 강제 `tool_choice`(any/tool)는 400 오류 → `tool_choice: auto` + 프롬프트 지시, 짧은 응답은 effort `low`
- 2026-09-29 — UI 프레임워크: Svelte 5 + Vite 8, 빌드 타깃 `safari15` (Monterey WKWebView). JS 75KB / gzip 28KB
- 2026-09-29 — 서체: npm 패키지(`pretendard`, `@fontsource/chakra-petch`)에서 빌드 시 `ui/public/fonts`로 복사. 둘 다 OFL
- 2026-09-29 — 코어 렌더링: Canvas 2D, 발광은 미리 그린 방사형 그라디언트 스프라이트. 프레임 상한 대기 20fps / 활성 30fps / reduced-motion 2fps. 탭 숨김 시 정지
- 2026-09-29 — 코어 주변 수치(다음 일정·AI 사용량/집중 타이머)는 코어 양옆이 아니라 코어 아래 계기판 줄에 배치 (1440폭에서 양옆 배치 시 패널과 겹침)
- 2026-09-29 — pywebview는 macOS에서만 의존성 설치, 없으면 기본 브라우저로 자동 대체
- 2026-09-29 — uvicorn WebSocket 구현: `websockets-sansio` (기존 `websockets` 구현은 deprecated)
- 2026-09-29 — 모의 모드는 개발자 단축키를 자동으로 켬. 실제 모드에서는 `--dev`일 때만 dev 명령 수락
- 대기 — 구동 기기 호환성 체크: `python3 scripts/check_env.py --install --write` 실행 후 아래에 결과 추가
- 대기 — 구동 기기 idle UI CPU(목표 ≤10%): `scripts/measure_cpu.py` 결과 기록
- 대기 — pywebview/WKWebView(Monterey) CSS 호환성: 구동 기기에서 확인, 문제 시 Safari 전체화면 대체

## Phase 2

- 2026-09-29 — 두뇌 구조: 로컬 규칙 파서 우선(시간·날짜·상태·인사·감사·취소), 매칭 안 될 때만 LLM. 발화 전체가 패턴과 일치할 때만 로컬 처리("3시에 스터디 있어?"는 LLM으로)
- 2026-09-29 — LLM 백엔드 교체 가능: `llm.backend` = `claude_code`(구독) / `api` / `off`. 기본값 `claude_code`
- 2026-09-29 — `claude_code` 백엔드: `claude -p --output-format json --tools "" --strict-mcp-config --allowedTools mcp__jarvis --system-prompt …`, 빈 작업 폴더에서 실행, 프롬프트는 stdin으로 전달, 후속 질문은 `--resume`. `--bare`는 API 키 인증만 지원해서 사용 안 함
- 2026-09-29 — Claude Code가 부를 수 있는 도구는 Jarvis MCP 브리지(표준 라이브러리만 사용, 빠른 시작)뿐. 브리지는 루프백 HTTP + 실행마다 새로 만드는 토큰으로 서버에 접근
- 2026-09-29 — 실제 CLI 검증(클라우드 x86 서버, Haiku): 도구 호출 포함 7.5s, 이어지는 질문 4.8s. 구동 기기에서는 더 느릴 것 → 5초 목표는 로컬 명령으로 달성, LLM 질문은 초과 가능
- 2026-09-29 — 구독 사용량 계산에서 캐시 읽기 토큰은 제외 (재개된 대화마다 수천 토큰이라 포함하면 일일 한도가 금방 참)
- 2026-09-29 — `api` 백엔드: SDK 1.x `AsyncAnthropic` + 직접 작성한 도구 루프(최대 4회). 베타 tool runner 대신 요청별 사용량 기록과 루프 상한을 직접 제어. 재시도는 SDK가 아니라 Brain에서 1회
- 2026-09-29 — onnxruntime(호출어, Silero VAD 의존): 1.20부터 macOS 13 이상 필요 → Intel Mac에서는 `<1.20`(마지막 1.19.2)으로 고정
- 2026-09-29 — pywhispercpp: Intel Mac용 휠은 1.2.0이 마지막 → Intel Mac에서는 `<1.3`으로 고정
- 2026-09-29 — openWakeWord: macOS는 0.6(모델 첫 실행 시 다운로드), Linux는 0.4(모델 내장, 0.6은 py3.12용 tflite-runtime 없음). 코드가 두 API 모두 지원. 프레임당 4.6ms(클라우드 x86)
- 2026-09-29 — Apple Speech 엔진은 별도 하위 프로세스에서 실행 (권한 설명이 없는 프로세스는 macOS가 종료시킬 수 있음)
- 2026-09-29 — TTS: `say`로 WAV를 먼저 만들고 음량 곡선을 계산한 뒤 `afplay`로 재생 → 코어 파형이 실제 목소리에 맞춰 움직임. 텍스트는 stdin으로 전달
- 2026-09-29 — 말 끝 판정: webrtcvad(없으면 에너지 기반), 무음 0.8초. 호출어 후 5초간 말이 없으면 조용히 대기로 복귀
- 2026-09-29 — Claude Code on 구동 기기: 불가. 문서상 macOS 13+ 필요, `@anthropic-ai/claude-code-darwin-x64` 2.1.284 실행 파일의 `LC_BUILD_VERSION minos = 13.0.0` 확인 → macOS 12에서 로드 안 됨. 구동 기기는 `api` 또는 `off`, 개발 맥은 `claude_code`
- 2026-09-29 — (사용자 결정) 기본 백엔드를 `api`로, 단 로컬 처리가 기반: API 키가 없으면 자동으로 `off`처럼 동작하고, 키가 있어도 로컬 명령은 API를 쓰지 않음. `claude_code`는 개발 맥 전용 옵션으로 유지
- 2026-09-29 — (사용자 결정) 무료 AI 사용: 기본 백엔드 `openai_compat` + Gemini 무료 등급(`gemini-flash-latest` 별칭). 계획서의 "Claude만 사용"에서 변경. Claude API·Claude Code·Groq·OpenRouter·GitHub Models·Ollama로 설정만 바꿔 전환 가능
- 2026-09-29 — 무료 등급은 입력이 학습에 쓰일 수 있음 → `llm.send_personal_data` 기본값: Claude 계열만 true. 무료 AI에는 일정 제목 미전송, Phase 5의 메일·슬랙 요약도 미전송
- 2026-09-29 — OpenAI 호환 요청: 도구 스키마에서 `additionalProperties`/빈 `required` 제거(Gemini 호환), `max_tokens` 1024(생각하는 모델이 토큰 일부를 먼저 씀), 429는 재시도하지 않음(무료 한도 소모 방지)
- 대기 — Gemini 실제 응답·도구 호출 확인: 이 개발 환경에서는 Google API가 막혀 있어 미검증. 사용자 맥에서 키 넣고 확인
- 대기 — STT 엔진 선택: 구동 기기에서 `scripts/bench_stt.py --synth` → `--write` 결과로 결정
- 대기 — 호출어→응답 음성 시작 지연(목표 5초): 구동 기기 로그의 `reply via … after …s`로 측정
