# Jarvis

책상 위 구형 맥북 에어를 위한 개인 비서 HUD예요. 전체화면 코어 UI, 음성 명령, 웹캠 인식,
일정·음악·메시지를 한 화면에 모아 보여줍니다.

> 현재 단계: **Phase 0–1** — 기반 구조와 HUD UI가 모의(mock) 데이터로 동작합니다.
> 음성·Claude 연동은 Phase 2부터 추가돼요.

## 빠르게 실행해 보기 (개발 맥)

필요한 것: [uv](https://docs.astral.sh/uv/), Node.js LTS ([nodejs.org](https://nodejs.org))

```bash
uv sync
cd ui && npm install && npm run build && cd ..
uv run jarvis --mock            # 전체화면 창으로 실행 (종료: ⌘Q)
uv run jarvis --mock --windowed # 창 모드
```

브라우저로만 보고 싶다면 `uv run jarvis --mock --no-window` 후 http://127.0.0.1:8765 를 여세요.

## 개발자 단축키 (모의 모드)

| 키 | 동작 |
|---|---|
| `1`–`6` | 코어 상태: 대기 / 듣기 / 생각 / 말하기 / 알림 / 오프라인 |
| 스페이스 길게 | 말하기 (모의 모드에서는 대화 시연) |
| `R` / `E` | 리마인더 알림 / 일정 예고 알림 |
| `D` / `Shift+D` | 졸음 경고 1단계 / 2단계 |
| `Esc` | 알림 닫기 |
| `M` | 새 메시지 도착 |
| `G` / `C` | Gmail 인증 만료 / 캘린더 오프라인 토글 |
| `F` | 집중 모드 시작·종료 |
| `N` / `P` | 다음 곡 / 재생·일시정지 |
| `?` | 단축키 도움말 |

## 문서

- [docs/setup.md](docs/setup.md) — 준비물(API 키, OAuth 앱)과 책상 맥 설치 안내
- [docs/decisions.md](docs/decisions.md) — 검증 결과와 기술 선택 기록
- [CLAUDE.md](CLAUDE.md) — 개발 규칙 요약 (영문)
