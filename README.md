# BidPilot AI

공공입찰 · 정부 지원사업 공고를 받아 회사 기준으로 검토 순서를 정하고, 제안요청서(RFP) 요구사항을 원문 근거와 함께 정리한 뒤
제안서 초안 작성과 제출 전 점검까지 돕는 도구입니다. 등록 · 제출 · 투찰은 하지 않고, 마지막 판단은 사람이 합니다.

## 사용 기록

- 2026 전남광주 청년(YOUTH) AI 솔버톤 B트랙(기업 실무 현안) 출품작으로 시작했습니다.
- 회사 자료 · 사내 문서는 이 저장소에 없습니다. 기본 회사는 시연용 **가상 회사 「샘플에듀」**(`org-sample`)이며,
  `data/synthetic_company/` 의 문서 · 숫자 · 실적은 모두 지어낸 값입니다.

## 하는 일

1. **공고 받기** — 조달청 나라장터(공공데이터포털 OpenAPI) 입찰공고 · 사전규격 · 발주계획, 기업마당 지원사업
2. **검토 순서** — 사업영역 · 참가자격 · 규모 · 지역으로 「회사 기준 검토 우선순위」(낙찰 · 선정 확률이 아님)
3. **참가 자격** — 규칙으로 가능 / 확인 필요 / 불가를 가르고 원문 근거를 남김(애매하면 확인 필요)
4. **요구사항 정리표** — RFP 를 요구사항 단위로 쪽 번호 · 원문과 함께 구조화
5. **회사 근거 연결** — 요구사항 ↔ 회사 수행근거(근거가 없으면 만들지 않음)
6. **제안서 초안** — 공고가 정한 목차 · 평가표대로 워드 · 한글(HWPX) · PDF
7. **제출 전 점검** — 요구사항 누락 · 숫자 불일치 · 근거 없는 주장 · 미작성 칸을 원문과 역대조

## 기술

- 프론트엔드: Next.js · React · TypeScript · Tailwind CSS
- 백엔드: Python 3.11+ · FastAPI · Pydantic · httpx
- AI: Claude / Codex CLI(구조화 출력 + 스키마 검증) · 임베딩 검색
- 문서: PDF · HWPX · DOCX 읽기 · 쓰기

## 폴더

```text
backend/   FastAPI 앱(app/api · app/services · app/schemas) · 시험(tests)
frontend/  Next.js 화면(src/app · src/components · src/lib) · 시험(tests)
data/      공개 샘플 공고 · 합성 예시 자료(회사 실자료는 Git 밖)
scripts/   켜기 · 받기 · 검사 스크립트
```

## 실행(개발)

```bash
# 백엔드
cd backend && python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/uvicorn app.main:app --port 8110

# 프론트엔드
cd frontend && npm install && npm run dev -- --port 3110
```

`.env.example` 을 `.env` 로 복사하고 필요한 키(공공데이터포털 서비스키 등)를 넣습니다. 키는 Git 에 올리지 않습니다.
근거 검색 색인(`data/synthetic_company/index/`)은 저장소에 없습니다. 임베딩 키를 넣고 `python scripts/build_company_index.py` 로 만들고,
없으면 근거 연결은 「AI 검색 꺼 둠 — 원장 후보에서 고르기」로 동작합니다. 읽기 전용 데모 스냅샷(`frontend/src/data/demo-snapshot.json`)은 빈 파일입니다.
