# 설치 및 준비 안내

개발은 **메인 맥북(Apple Silicon)** 에서, 실제 구동은 **책상 위 맥북 에어(Intel, macOS 12 Monterey)** 에서 합니다.
아래 순서대로 진행하면 돼요. 각 연동은 해당 Phase에서 쓰이므로, 지금 당장 전부 준비할 필요는 없어요.

| 준비물 | 필요한 Phase |
|---|---|
| 개발 맥 환경 | Phase 0–1 |
| 책상 맥 환경 + 호환성 체크 | Phase 0–1 |
| AI 연결 (Claude Code 구독 또는 API 키, 선택) | Phase 2 |
| 음성 패키지 + STT 벤치마크 | Phase 2 |
| Google Cloud OAuth (캘린더·Gmail) | Phase 3, 5 |
| Spotify 개발자 앱 | Phase 5 |
| Slack 앱 | Phase 5 |

---

## 1. 개발 맥 (Apple Silicon)

1. **uv** 설치 (Python 패키지 관리 도구):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
   설치가 끝나면 **터미널 창을 닫고 새로 열거나**, 지금 창에서 `source $HOME/.local/bin/env` 를 실행하세요.
   `uv --version` 이 버전을 출력하면 성공이에요. (`zsh: command not found: uv` 가 나오면 이 단계가 빠진 거예요.)
2. **Node.js LTS** 설치: https://nodejs.org 에서 macOS 설치 파일 (UI 빌드용). 확인: `node --version`
3. 저장소 폴더에서:
   ```bash
   uv sync --extra voice --extra stt-faster     # Python 3.12가 없으면 uv가 알아서 받아요
   cd ui && npm install && npm run build && cd ..
   uv run jarvis --mock --windowed              # 가짜 데이터 + 가짜 음성
   uv run jarvis --mock --voice real --windowed # 가짜 데이터 + 실제 마이크·스피커
   ```
4. 모의 모드에서 `?` 키를 누르면 단축키가 나와요.
5. 처음 `--voice real`로 실행하면 macOS가 **터미널의 마이크 접근**을 물어봐요. 허용하세요.

## 2. 책상 맥 (MacBook Air 2015, Monterey)

### 2.1 기본 설치
1. **Python 3.12**: https://www.python.org/downloads/macos/ 에서 *macOS 64-bit universal2 installer* (3.12.x)
   - Homebrew는 Monterey를 공식 지원하지 않으니 쓰지 않아요.
   - 설치 후 `/Applications/Python 3.12/Install Certificates.command` 를 한 번 실행하세요.
2. **uv**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
3. **Safari 업데이트**: 소프트웨어 업데이트에서 Monterey용 최신 Safari로 올려 주세요.
   UI 창(WKWebView)은 설치된 Safari 엔진을 그대로 씁니다.
4. **Node.js는 필요 없어요.** UI는 개발 맥에서 빌드해서 보냅니다.

### 2.2 원격 로그인 켜기 (배포용)
시스템 환경설정 → 공유 → **원격 로그인** 체크. 그러면 개발 맥에서:
```bash
scripts/deploy.sh 사용자이름@맥북에어이름.local
```
으로 UI 빌드 → 복사 → 의존성 설치까지 한 번에 됩니다.

### 2.3 호환성 체크 (Phase 0 완료 조건)
책상 맥에서 저장소 폴더로 이동한 뒤:
```bash
python3 scripts/check_env.py --install --write
```
- OpenCV, MediaPipe, openWakeWord, STT 후보(faster-whisper, whisper.cpp, Apple Speech) 등을
  임시 가상환경(`.check-venv/`)에 하나씩 설치하고 import까지 확인해요. 10–20분 걸릴 수 있어요.
- 결과는 책상 맥의 `docs/decisions.md` 끝에 표로 추가됩니다. **다음 배포 전에** 개발 맥으로 가져와 커밋하세요
  (`deploy.sh`는 책상 맥의 파일을 개발 맥 내용으로 덮어써요):
  ```bash
  scp 사용자이름@맥북에어이름.local:~/jarvis/docs/decisions.md docs/decisions.md
  ```
- 끝나면 `.check-venv/` 폴더는 지워도 돼요.

### 2.4 UI 성능 측정 (Phase 1 완료 조건)
```bash
uv run jarvis --mock &
# 부팅 애니메이션이 끝나고 30초쯤 뒤에
python3 scripts/measure_cpu.py --seconds 60
```
대기 상태 UI(WebKit) CPU가 **10% 이하**인지 확인하고, 결과를 `docs/decisions.md`에 한 줄 적어 주세요.
`1`–`5` 키로 상태를 바꿔 가며 부드러운지도 봐 주세요.

### 2.5 이 기기 보안 수칙
- Monterey는 보안 업데이트가 끝난 OS예요. **메인 Apple ID로 로그인하지 말고**, 필요 없는 앱은 설치하지 마세요.
- Jarvis 서버는 `127.0.0.1`에만 열려요. 방화벽 설정을 바꿀 필요가 없어요.

### 2.6 카메라 설치 (기숙사)
- 카메라 화각에 **룸메이트 자리나 침대가 들어가지 않도록** 책상 정면·약간 위에서 사용자 얼굴만 향하게 두세요.
- 카메라 영상은 저장하지도, 외부로 보내지도 않아요(얼굴 등록 시 수치 벡터만 저장).
- UI의 카메라 일시 중지 버튼으로 언제든 카메라를 완전히 끌 수 있어요(Phase 4).

### 2.7 한국어 음성 (Yuna)
시스템 환경설정 → 손쉬운 사용 → 음성 콘텐츠 → 시스템 음성 → **사용자화…** → 한국어 **Yuna** 체크 후 다운로드.
확인: `say -v Yuna "안녕하세요, 재원님"`

### 2.8 macOS 권한
처음 쓸 때 권한 요청 창이 뜨면 허용하세요. 나중에 바꾸려면
시스템 환경설정 → 보안 및 개인 정보 보호 → 개인 정보 보호 탭에서:
- **카메라**, **마이크**: 터미널(또는 Jarvis를 실행하는 앱)
- **자동화**: 터미널 → Spotify (AppleScript로 재생 제어)

---

## 3. AI 연결 (Phase 2)

자비스의 기본은 **AI 없이 로컬에서 처리하는 명령**(시간, 날짜, 상태, 인사 등)이에요. 무료이고 빨라요.
로컬로 답할 수 없는 질문만 AI로 보내요. 기본 AI는 **Google Gemini 무료 등급**이고,
**API 키가 없으면 자동으로 `off`(로컬 명령만)로 동작**하니 키는 나중에 넣어도 돼요.
연결 방법은 `config.yaml`의 `llm.backend`로 바꿀 수 있어요.

| `llm.backend` | 비용 | 준비물 |
|---|---|---|
| `openai_compat` (기본, Gemini) | 무료 등급 (분당·하루 요청 수 제한) | Gemini API 키 (3.0). 다른 무료 서비스도 가능 (3.3) |
| `off` | 무료 | 없음 — 로컬 명령만 동작 |
| `api` | Claude, 토큰당 과금 (Haiku 기준 대략 월 1–3달러) | API 키 + 크레딧 (3.2) |
| `claude_code` | 구독(Pro/Max) 사용량 안에서 추가 결제 없음 | **개발 맥 전용** (macOS 13+). Claude Code 설치 + 로그인 (3.1) |

화면 오른쪽 위 상태 표시줄에 `AI·Gemini` / `AI·Claude` / `AI 꺼짐`처럼 보여요.
답변 아래에는 `로컬 처리` 또는 `Gemini`처럼 작게 표시돼서 어떤 질문이 AI를 썼는지 알 수 있어요.

> **개인정보**: 무료 등급은 보낸 내용이 서비스 개선에 쓰일 수 있어요. 그래서 무료 AI에는 **일정 제목을 보내지 않고**
> (예: "다음 일정: 22:30 (40분 후)"만 보냄), Phase 5부터는 **메일·슬랙 내용도 보내지 않아요.**
> Claude(`api`)로 바꾸면 이 제한이 풀려요. 직접 정하려면 `llm.send_personal_data: true/false`.

### 3.0 Gemini API 키 (기본, 무료)

1. https://aistudio.google.com/apikey 에 Google 계정으로 로그인해요. (학교 계정은 막혀 있을 수 있어요 — 개인 Gmail 권장)
2. **API 키 만들기(Create API key)** → 키를 복사해요. 결제 정보를 등록하지 않으면 무료 등급으로만 동작해요.
3. 저장소 폴더의 `.env` 파일(`.env.example` 복사)에:
   ```
   GEMINI_API_KEY=붙여넣은키
   ```
4. 자비스를 다시 시작하면 상태 표시줄이 `AI·Gemini`로 바뀌어요. `T`를 누르고 "오늘 저녁 뭐 먹을까?"로 확인해 보세요.

알아 둘 점
- 무료 등급의 모델 이름과 한도는 자주 바뀌어요. 기본값 `gemini-flash-latest`는 항상 최신 Flash 모델을 가리키는 별칭이에요.
  "AI 모델 이름을 확인해 주세요"라고 하면 AI Studio에서 쓸 수 있는 모델 이름을 `llm.openai_compat.model`에 적어 주세요.
- 한도에 걸리면 자비스가 "무료 사용량 한도에 걸렸어요"라고 말해요. 로컬 명령은 계속 돼요.

### 3.1 Claude Code (구독으로 쓰기, 개발 맥 전용)

> ⚠️ **책상 맥(macOS 12)에서는 Claude Code가 실행되지 않아요.** Claude Code는 macOS 13 이상만 지원하고,
> Intel용 실행 파일도 최소 macOS 13.0으로 빌드되어 있어요(2.1.284 기준 확인).
> 개발 맥(Apple Silicon)에서는 문제없이 쓸 수 있어요. 책상 맥에서는 다음 중 하나를 고르세요.
> - `api`: 소액 과금 (3.2). 로컬 명령이 대부분을 처리해서 월 1–3달러 수준 예상
> - `off`: 무료, 로컬 명령만
> - (고급) OpenCore Legacy Patcher로 책상 맥을 macOS 13 이상으로 올리기 — 비공식이고 되돌리기 번거로워요.
>   대신 보안 업데이트와 최신 onnxruntime도 쓸 수 있게 돼요. 원하시면 따로 안내할게요.

1. 설치: `curl -fsSL https://claude.ai/install.sh | bash`
2. 터미널에서 `claude`를 한 번 실행해 브라우저로 **구독 계정에 로그인**해요. 로그인이 끝나면 `/exit`.
3. `config.yaml`:
   ```yaml
   llm:
     backend: claude_code
     claude_code_model: haiku   # 빠르고 사용량을 적게 씀
   ```
4. 확인: `uv run jarvis --windowed` 실행 후 `T`를 눌러 "오늘 저녁 뭐 먹을까?"를 입력해 보세요.

알아 둘 점
- 구독의 **사용량 한도를 평소 채팅과 나눠** 써요. 한도에 걸리면 자비스가 "구독 사용량 한도에 도달했어요"라고 말해요.
- Claude Code의 기본 도구(셸 실행, 파일 수정 등)는 **모두 끈 상태**로 실행돼요. 자비스가 허락한 도구만 쓸 수 있어요.
- 개인 용도로 쓰는 건 Claude Code 본래 용도에 가깝지만, 상시 켜 두는 비서로 쓰는 게 괜찮은지는
  Anthropic 소비자 약관을 한 번 확인해 보세요.

### 3.2 Claude API 키

1. https://console.anthropic.com 에 로그인해 **API Keys**에서 키를 발급해요.
2. **Billing**에서 크레딧을 충전해요.
   - 주의: **Claude.ai 구독(Pro/Max)과 API는 결제가 별개**예요. 구독이 있어도 API 크레딧은 따로 필요해요.
3. **Limits**에서 **월 사용 한도**를 설정해 두세요(예: $5). 앱 자체에도 일일 토큰 한도가 있어요.
4. 저장소 루트에 `.env` 파일을 만들고(`.env.example` 복사):
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   `.env`는 git에 올라가지 않아요.
5. `config.yaml`에서 `llm.backend: api`로 바꾸고 다시 시작하면 상태 표시줄이 `AI·Claude`로 바뀌어요.

### 3.3 다른 무료 서비스 (선택)

모두 같은 방식(OpenAI 호환)이라 `config.yaml`만 바꾸면 돼요. 무료 조건과 모델 이름은 가입할 때 확인하세요.

| provider | 키 (`.env`) | `model` 예시 | 비고 |
|---|---|---|---|
| `gemini` (기본) | `GEMINI_API_KEY` | 생략 가능 (`gemini-flash-latest`) | 한국어 좋음 |
| `groq` | `GROQ_API_KEY` | Groq 콘솔의 모델 목록에서 선택 | 매우 빠름, 한국어 보통 |
| `openrouter` | `OPENROUTER_API_KEY` | 이름이 `:free`로 끝나는 모델 | 하루 요청 수 제한 |
| `github` | `GITHUB_TOKEN` | GitHub Models 목록에서 선택 | 시험용 |
| `ollama` | 필요 없음 | 예: `qwen2.5:3b` (직접 받은 모델) | 내 컴퓨터에서 실행. 책상 맥에서는 너무 느려요 |

```yaml
llm:
  backend: openai_compat
  openai_compat:
    provider: groq
    model: 여기에-모델-이름
```

## 4. 음성 (Phase 2)

### 4.1 음성 패키지 설치
음성 관련 패키지는 선택 설치예요. 책상 맥에서 호환성 체크(2.3)가 OK였던 것만 골라 설치하세요.
```bash
uv sync --extra voice --extra stt-faster          # 호출어 + faster-whisper (권장 조합)
uv sync --extra voice --extra stt-cpp             # 또는 whisper.cpp
uv sync --extra voice --extra stt-apple           # 또는 Apple 음성 인식
```
Intel Mac(macOS 12)에서 설치되는 버전(onnxruntime 1.19.x, pywhispercpp 1.2.0)으로 이미 고정해 뒀어요.

처음 실행할 때 인터넷이 필요해요.
- 호출어 모델("hey jarvis")을 GitHub에서 받아요.
- faster-whisper 모델을 Hugging Face에서 받아요 (`small` 약 480MB, `base` 약 150MB).

### 4.2 STT 엔진 고르기 (Phase 2 완료 조건)
책상 맥에서:
```bash
uv run python scripts/bench_stt.py --synth                       # Yuna 음성으로 시험용 명령 10개 생성
uv run python scripts/bench_stt.py --write                       # 설치된 엔진 전부 측정 → decisions.md
uv run python scripts/bench_stt.py --record                      # (선택) 내 목소리로 다시 녹음해서 측정
```
표에서 **지연이 짧고 CER(글자 오류율)이 낮은** 엔진을 골라 `config.yaml`에 적어요.
```yaml
voice:
  stt_engine: faster_whisper
  stt_model: base
```
합성음은 실제 목소리보다 깨끗해서 점수가 좋게 나와요. 가능하면 `--record`로도 한 번 확인해 주세요.

### 4.3 실행과 응답 시간 측정
```bash
uv run jarvis                 # 실제 마이크·스피커 + 연동은 아직 비활성
uv run jarvis --mock --voice real   # 가짜 일정·메일 화면 + 실제 음성
```
"헤이 자비스, 지금 몇 시야?"라고 말해 보세요. 터미널 로그의
`reply via local after 1.8s total` 같은 줄이 **말이 끝난 뒤 → 답변 준비**까지의 시간이에요.
여러 번 해 보고 평균을 `docs/decisions.md`에 적어 주세요 (목표: 호출부터 응답 시작까지 5초 이내).

- 호출어 대신 **스페이스 길게 누르기**, 화면의 마이크 버튼, **`T` 키로 텍스트 입력**도 돼요.
- 말하는 도중에 스페이스를 누르면 말을 끊고 바로 다시 들어요.
- 호출어가 너무 잘/안 걸리면 `voice.wake_threshold`(기본 0.5)를 조절하세요.

## 5. Google Cloud — 캘린더·Gmail (Phase 3, 5)

**Notion Calendar**는 공개 API가 없어요. 대신 Notion Calendar가 보여주는 일정은 연결된
**Google 캘린더**에서 오기 때문에, Google Calendar API로 같은 캘린더를 읽습니다.

1. https://console.cloud.google.com 에서 새 프로젝트 생성 (예: `jarvis-desk`)
2. **API 및 서비스 → 라이브러리**에서 **Google Calendar API**, **Gmail API** 사용 설정
3. **OAuth 동의 화면**
   - 사용자 유형: 외부 / 게시 상태: 테스트
   - 테스트 사용자에 본인 Gmail 주소 추가
   - 범위: `.../auth/calendar.readonly`, `.../auth/gmail.readonly` (읽기 전용만)
4. **사용자 인증 정보 → OAuth 클라이언트 ID 만들기** → 애플리케이션 유형 **데스크톱 앱**
5. JSON을 다운로드해서 이 위치에 저장:
   `~/Library/Application Support/Jarvis/google_client_secret.json`
6. 읽을 캘린더 ID 확인: Google 캘린더 웹 → 캘린더 설정 → **캘린더 통합 → 캘린더 ID**.
   Notion Calendar에서 보고 있는 캘린더들을 `config.yaml`의 `calendar.google_calendar_ids`에 넣어요.

> 앱이 "테스트" 상태면 약 **7일마다 다시 로그인**해야 할 수 있어요.
> Jarvis가 화면에 "Google 다시 연결 필요" 카드와 버튼을 띄워 줍니다.

## 6. Spotify (Phase 5)

1. https://developer.spotify.com/dashboard → **Create app**
2. Redirect URI: `http://127.0.0.1:8765/callback/spotify`
3. 사용 API: **Web API**
4. Client ID / Client Secret은 Phase 5에서 키체인에 저장하도록 안내할게요.
5. 개발 모드 앱의 이용 조건(사용자 수 제한, Premium 필요 여부)은 **구현 시점에 다시 확인**해요.
6. 책상 맥에 Spotify 데스크톱 앱이 설치되는지도 확인해 주세요(Monterey 지원 여부는 체크 스크립트가 알려줘요).

## 7. Slack (Phase 5)

1. https://api.slack.com/apps → **Create New App → From scratch**, 워크스페이스 선택
2. **OAuth & Permissions → User Token Scopes**에 추가:
   `search:read`, `im:history`, `users:read`, `channels:read`, `groups:read`, `im:read`
3. **Install to Workspace** → 발급된 **User OAuth Token (`xoxp-…`)** 을 Phase 5에서 키체인에 저장해요.
4. 학교·동아리 워크스페이스는 **관리자 승인**이 필요할 수 있어요. 승인이 안 되면 Slack 패널만
   "연결 안 됨"으로 표시되고 나머지 기능은 그대로 동작해요.
