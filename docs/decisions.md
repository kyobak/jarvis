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
