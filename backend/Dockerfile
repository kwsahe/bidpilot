# BidPilot AI — 백엔드(FastAPI) 컨테이너 이미지
#
# 빌드 컨텍스트는 **저장소 루트**다 (씨앗 데이터가 backend/ 바깥에 있다):
#
#     docker build -f backend/Dockerfile -t bidpilot-api .
#
# 이미지에 굽는 것   : backend/app, backend/pyproject.toml, 공개 샘플·합성 회사자료(→ /seed/data)
# 이미지에 넣지 않는 것: data/private, data/company (실제 회사자료), 업로드 원본, 실행 산출물, .env
#   → 실제 데이터는 볼륨($DATA_DIR)에만 쌓인다. 자세한 내용은 docs/deploy_backend.md.

########################################################################
# 1) seed — 이미지에 구울 씨앗 데이터만 추리는 스테이지
#
# 실제 회사자료 경로(data/private, data/company)는 여기서 아예 COPY 하지 않는다.
# 최종 이미지에는 이 스테이지의 결과물만 넘어가므로, .dockerignore 가 적용되지
# 않는 환경에서 빌드해도 지운 파일이 이미지 레이어에 남지 않는다.
########################################################################
FROM python:3.12-slim AS seed

COPY data/public/ /seed/data/public/
COPY data/synthetic_company/ /seed/data/synthetic_company/

# 실행할 때마다 쌓이는 산출물·로컬 전용 백업·재생성 가능한 캐시는 이미지에서 뺀다.
# (볼륨에서 앱이 저장할 때 부모 디렉터리를 알아서 만든다)
RUN set -eux; \
    rm -rf \
      /seed/data/public/real_rfp \
      /seed/data/public/audit_runs \
      /seed/data/public/reviews \
      /seed/data/public/conditions \
      /seed/data/public/actions \
      /seed/data/public/decisions \
      /seed/data/public/corrections \
      /seed/data/public/notice_versions \
      /seed/data/public/exports \
      /seed/data/synthetic_company/docs_backup_before_import \
      /seed/data/synthetic_company/index/requirement_vectors.json; \
    find /seed/data -name '__pycache__' -type d -prune -exec rm -rf {} +; \
    mkdir -p /seed/data/templates/hwpx; \
    if [ -e /seed/data/private ] || [ -e /seed/data/company ]; then \
      echo "실제 회사자료가 씨앗 데이터에 섞였습니다: /seed/data/{private,company}" >&2; \
      exit 1; \
    fi

########################################################################
# 2) runtime — 실행 이미지
########################################################################
FROM python:3.12-slim AS runtime

# pyproject.toml 은 Python 3.11+ 를 요구한다. 여기서는 3.12 로 고정한다.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/srv/backend \
    DATA_DIR=/data \
    SEED_DIR=/seed/data \
    PORT=8000

WORKDIR /srv/backend

# ── 의존성 먼저 (소스가 바뀌어도 이 레이어는 캐시가 산다) ────────────────
# pyproject.toml 의 [project].dependencies 를 그대로 설치한다. 목록을 이 파일에
# 다시 적지 않는다 — 의존성 단일 출처는 backend/pyproject.toml 이다.
COPY backend/pyproject.toml /srv/backend/pyproject.toml
RUN set -eux; \
    python -c "import pathlib, tomllib; d = tomllib.loads(pathlib.Path('/srv/backend/pyproject.toml').read_text(encoding='utf-8')); pathlib.Path('/tmp/requirements.txt').write_text('\n'.join(d['project']['dependencies']) + '\n', encoding='utf-8')"; \
    cat /tmp/requirements.txt; \
    pip install --no-cache-dir --upgrade pip; \
    pip install --no-cache-dir -r /tmp/requirements.txt; \
    rm -f /tmp/requirements.txt

# ── 소스 ──────────────────────────────────────────────────────────────
COPY backend/app /srv/backend/app

# ── 씨앗 데이터 ────────────────────────────────────────────────────────
COPY --from=seed /seed/data /seed/data

# ── 실행 계정(비 root)과 데이터 디렉터리 ────────────────────────────────
# /data 를 이미지에 미리 만들고 소유자를 실행 계정으로 바꾼다.
#   → 이름 있는 볼륨(named volume)을 처음 붙일 때 도커가 이 디렉터리의 소유권을
#     그대로 가져가므로 비 root 로도 볼륨에 쓸 수 있다.
# /srv 소유자도 바꾼다 — entrypoint 가 /srv/data 링크를 만들어야 한다.
COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN set -eux; \
    groupadd --system --gid 10001 app; \
    useradd --system --uid 10001 --gid 10001 --home-dir /srv --shell /usr/sbin/nologin app; \
    # 윈도우에서 체크아웃하면 CRLF 가 섞일 수 있다(core.autocrlf=true). 실행 전에 털어낸다.
    sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh; \
    chmod 0755 /usr/local/bin/docker-entrypoint.sh; \
    mkdir -p /data; \
    chown app:app /data /srv

USER app:app

EXPOSE 8000

# PaaS 가 주입하는 PORT 를 존중한다 (기본 8000).
# /health 는 인증 없이 열려 있는 엔드포인트다 (인증 상태 자체를 여기서 확인한다).
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os, sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
