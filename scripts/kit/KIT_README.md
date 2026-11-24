# BidPilot AI 설치 안내

나라장터 입찰 · 기업마당 지원사업 공고를 회사 기준으로 정리하고, 회사 자료를 근거로 제안서 · 사업계획서 초안을 쓰는 프로그램입니다.
마지막 판단과 제출은 담당자가 합니다.

## 1. 설치 (처음 한 번)

1. 이 폴더를 원하는 곳(예: `C:\BidPilot`)에 풉니다. 폴더 이름에 빈칸이 없으면 더 좋습니다.
2. `start_kit.bat` 을 두 번 누릅니다.
3. Python 3.11 이상 · Node 20.9 이상이 없으면 설치 명령을 보여 주고 멈춥니다. 보여 준 명령을 PowerShell 에 붙여 넣어 설치한 뒤,
   창을 닫고 `start_kit.bat` 을 다시 누르세요.
   - `winget install -e --id Python.Python.3.12`
   - `winget install -e --id OpenJS.NodeJS.LTS`
4. 처음에는 프로그램 부품을 인터넷에서 받느라 몇 분 걸립니다.

## 2. 처음 켤 때 묻는 것

| 질문 | 쓰는 곳 |
| --- | --- |
| 회사 이름 | 화면 맨 위 · 문서 표지. **나중에 화면에서 못 고칩니다** |
| 사업영역(쉼표로 구분) | 공고를 고르는 기준(회사 기준 검토 우선순위) |
| 활동 지역(비워도 됨) | 지역 제한 공고 판정 — 비우면 「확인 필요」 |
| 나라장터 · 기업마당 인증키(비워도 됨 · 공공데이터포털 API 키 — 입찰할 때 쓰는 회사 인증서와 다릅니다) | 새 공고 받기 — 없으면 저장된 예시 목록만 보입니다 |
| Claude · Codex 사용 여부 | 사업계획서 「Claude로 쓰기」 · 「Codex로 쓰기」 단추 — 답은 `.env` 에 남아 다음에 켤 때도 같습니다 |

답은 이 폴더의 `.env` 와 `data\private\` 에만 저장됩니다. 인증키는 화면에 찍지 않습니다.

## 3. 키 넣기 (나중에)

1. 공공데이터포털(나라장터) · 기업마당에서 인증키를 받습니다(공공데이터포털 API 키 — 입찰할 때 쓰는 회사 인증서와 다릅니다).
2. 이 폴더의 `.env` 를 메모장으로 열어 `DATA_GO_KR_SERVICE_KEY=` · `BIZINFO_API_KEY=` 뒤에 붙여 넣고 저장합니다.
3. 프로그램을 껐다가 `start_kit.bat` 으로 다시 켭니다.

## 4. 쓰기

- 켜지면 브라우저에 `http://localhost:3110` 이 열립니다.
- 「회사자료」에서 회사 소개서 · 실적 자료를 올리고, 제안서에 써도 되는 문장을 골라 근거로 등록하세요.
- 「사업기회」에서 공고를 고르고 「사업계획서 작성」에서 초안을 만듭니다.
- 입찰 · 지원사업이 처음이면 이 폴더의 `GUIDE.md`(처음 하는 회사를 위한 실전 가이드)를 먼저 읽으세요 — 나라장터 등록 · 인증서 · 확인서 · 제출은 BidPilot 밖에서 사람이 합니다. 화면 맨 위 「?」에도 한 장 요약이 있습니다. 화면 메뉴 **「실전 가이드」**에서도 같은 내용을 볼 수 있습니다.

## 4-1. Claude · Codex 켜기 (나중에)

처음에 「아니요」로 답했어도 나중에 켤 수 있습니다.

1. 이 폴더의 `.env` 를 메모장으로 열어 `KIT_PLAN_WRITER=` 뒤에 `1`(Claude · Codex 둘 다) · `claude` · `codex` 중 하나를 적고 저장합니다.
2. 프로그램을 껐다가 `start_kit.bat` 으로 다시 켭니다. 사업계획서 화면에 「Claude로 쓰기」 · 「Codex로 쓰기」 단추가 켜집니다.
3. Claude Code · Codex 프로그램이 이 PC 에 있고 로그인돼 있어야 합니다(`claude auth login` · `codex login`).

## 5. 끄기

- 서버 창 두 개(백엔드 · 프론트)를 닫거나, PowerShell 에서
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop_dev.ps1`

## 6. 안 될 때

| 보이는 것 | 할 일 |
| --- | --- |
| 「포트를 다른 프로그램이 쓰고 있습니다」 | 다른 BidPilot 창을 닫거나, 이 폴더에서 PowerShell 을 열고 `powershell -NoProfile -ExecutionPolicy Bypass -File kit_setup.ps1 -FrontendPort 3120 -BackendPort 8120` — 바꾼 포트는 `.env` 에 남아 다음부터 `start_kit.bat` 도 같은 포트로 켭니다 |
| 공고 목록이 오래된 것만 보임 | 3번대로 인증키를 넣고 다시 켜기 |
| 「Claude 프로그램이 없습니다」 | Claude Code 를 설치하고 터미널에서 `claude auth login` |
