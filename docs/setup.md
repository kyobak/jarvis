# 설치 및 준비 안내

개발은 **메인 맥북(Apple Silicon)** 에서, 실제 구동은 **책상 위 맥북 에어(Intel, macOS 12 Monterey)** 에서 합니다.
아래 순서대로 진행하면 돼요. 각 연동은 해당 Phase에서 쓰이므로, 지금 당장 전부 준비할 필요는 없어요.

| 준비물 | 필요한 Phase |
|---|---|
| 개발 맥 환경 | 지금 (Phase 0–1) |
| 책상 맥 환경 + 호환성 체크 | 지금 (Phase 0–1) |
| Claude API 키 | Phase 2 |
| Google Cloud OAuth (캘린더·Gmail) | Phase 3, 5 |
| Spotify 개발자 앱 | Phase 5 |
| Slack 앱 | Phase 5 |

---

## 1. 개발 맥 (Apple Silicon)

1. **uv** 설치: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. **Node.js LTS** 설치: https://nodejs.org 에서 macOS 설치 파일
3. 저장소에서:
   ```bash
   uv sync
   cd ui && npm install && npm run build && cd ..
   uv run jarvis --mock --windowed
   ```
4. 모의 모드에서 `?` 키를 누르면 개발자 단축키가 나와요.

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

## 3. Claude API 키 (Phase 2)

1. https://console.anthropic.com 에 로그인해 **API Keys**에서 키를 발급해요.
2. **Billing**에서 크레딧을 충전해요.
   - 주의: **Claude.ai 구독(Pro/Max)과 API는 결제가 별개**예요. 구독이 있어도 API 크레딧은 따로 필요해요.
3. **Limits**에서 **월 사용 한도**를 설정해 두세요(예: $5). 앱 자체에도 일일 토큰 한도가 있어요.
4. 저장소 루트에 `.env` 파일을 만들고(`.env.example` 복사):
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   `.env`는 git에 올라가지 않아요.

## 4. Google Cloud — 캘린더·Gmail (Phase 3, 5)

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

## 5. Spotify (Phase 5)

1. https://developer.spotify.com/dashboard → **Create app**
2. Redirect URI: `http://127.0.0.1:8765/callback/spotify`
3. 사용 API: **Web API**
4. Client ID / Client Secret은 Phase 5에서 키체인에 저장하도록 안내할게요.
5. 개발 모드 앱의 이용 조건(사용자 수 제한, Premium 필요 여부)은 **구현 시점에 다시 확인**해요.
6. 책상 맥에 Spotify 데스크톱 앱이 설치되는지도 확인해 주세요(Monterey 지원 여부는 체크 스크립트가 알려줘요).

## 6. Slack (Phase 5)

1. https://api.slack.com/apps → **Create New App → From scratch**, 워크스페이스 선택
2. **OAuth & Permissions → User Token Scopes**에 추가:
   `search:read`, `im:history`, `users:read`, `channels:read`, `groups:read`, `im:read`
3. **Install to Workspace** → 발급된 **User OAuth Token (`xoxp-…`)** 을 Phase 5에서 키체인에 저장해요.
4. 학교·동아리 워크스페이스는 **관리자 승인**이 필요할 수 있어요. 승인이 안 되면 Slack 패널만
   "연결 안 됨"으로 표시되고 나머지 기능은 그대로 동작해요.
