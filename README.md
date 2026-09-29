# Jarvis

책상 위 구형 맥북 에어를 위한 개인 비서 HUD예요. 전체화면 코어 UI, 음성 명령, 웹캠 인식,
일정·음악·메시지를 한 화면에 모아 보여줍니다.

> 현재 단계: **Phase 0–2** — HUD UI, 음성 대화(호출어 → 음성 인식 → 답변 → 음성 출력),
> AI 연결(기본: Gemini 무료 등급)까지 동작해요. 일정·메일·음악 패널은 아직 모의(mock) 데이터예요.

## 빠르게 실행해 보기 (개발 맥)

필요한 것: [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh` 후 터미널 새로 열기),
Node.js LTS ([nodejs.org](https://nodejs.org))

```bash
uv sync
cd ui && npm install && npm run build && cd ..
uv run jarvis --mock            # 전체화면, 전부 가짜 (종료: ⌘Q)
uv run jarvis --mock --windowed # 창 모드
```

실제 마이크·스피커로 대화해 보려면 ([docs/setup.md](docs/setup.md) 3·4장):

```bash
uv sync --extra voice --extra stt-faster
uv run jarvis --mock --voice real --windowed
```

"헤이 자비스, 지금 몇 시야?"처럼 자주 쓰는 명령은 AI 없이 바로 답해요(기본).
`.env`에 무료 `GEMINI_API_KEY`를 넣으면 로컬로 못 한 질문만 Gemini로 보내요. 키가 없으면 로컬 명령만 동작해요.
Claude API나 다른 무료 서비스로도 바꿀 수 있어요 ([docs/setup.md](docs/setup.md) 3장).
답변 아래의 `로컬 처리` / `Gemini` 표시로 구분돼요.

브라우저로만 보고 싶다면 `uv run jarvis --mock --no-window` 후 http://127.0.0.1:8765 를 여세요.

## 조작

| 키 | 동작 |
|---|---|
| "헤이 자비스" | 음성 호출 (음성 패키지 설치 시) |
| 스페이스 길게 | 말하기. 자비스가 말하는 중이면 끊고 다시 듣기 |
| `T` | 텍스트로 명령 입력 |
| `?` | 단축키 도움말 |

모의 모드 전용 개발자 단축키:

| 키 | 동작 |
|---|---|
| `1`–`6` | 코어 상태: 대기 / 듣기 / 생각 / 말하기 / 알림 / 오프라인 |
| `R` / `E` | 리마인더 알림 / 일정 예고 알림 |
| `D` / `Shift+D` | 졸음 경고 1단계 / 2단계 |
| `Esc` | 알림 닫기 |
| `M` | 새 메시지 도착 |
| `G` / `C` | Gmail 인증 만료 / 캘린더 오프라인 토글 |
| `F` | 집중 모드 시작·종료 |
| `N` / `P` | 다음 곡 / 재생·일시정지 |

## 문서

- [docs/setup.md](docs/setup.md) — 준비물(AI 연결, OAuth 앱), 음성 설치, 책상 맥 설치 안내
- [docs/decisions.md](docs/decisions.md) — 검증 결과와 기술 선택 기록
- [CLAUDE.md](CLAUDE.md) — 개발 규칙 요약 (영문)
