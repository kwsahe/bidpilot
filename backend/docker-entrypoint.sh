#!/bin/sh
# BidPilot AI — 백엔드 컨테이너 시작 스크립트
#
# 하는 일
#   1) $DATA_DIR(영구 볼륨)에 **없는 파일만** 씨앗 데이터(/seed/data)에서 채운다.
#      이미 있는 파일은 절대 덮어쓰지 않는다 — 볼륨에 쌓인 실제 회사자료를 지우면 안 된다.
#   2) 저장소 기준 경로(/srv/data)를 $DATA_DIR 로 연결한다.
#      앱 코드가 DATA_DIR 환경변수를 읽든, 저장소 기준 `data/` 를 찾든 같은 볼륨을 보게 한다.
#   3) uvicorn 을 exec 로 띄운다 (PID 1 = uvicorn → 종료 신호가 그대로 전달된다).
#
# 인자를 주면 그 명령을 대신 실행한다:  docker run ... bidpilot-api python -c "..."
set -eu

DATA_DIR="${DATA_DIR:-/data}"
# 앱도 같은 값을 읽어야 한다 (환경변수로 넘기지 않고 기본값만 쓰면 경로가 갈린다).
export DATA_DIR
SEED_DIR="${SEED_DIR:-/seed/data}"
APP_DIR="${APP_DIR:-/srv/backend}"
# backend/app/core/org_storage.py 등이 저장소 기준으로 계산하는 경로 (/srv/backend/../data)
REPO_DATA_DIR="${REPO_DATA_DIR:-/srv/data}"
PORT="${PORT:-8000}"

log() {
    echo "[entrypoint] $*"
}

# ── 1) 씨앗 데이터 채우기 (없는 파일만) ─────────────────────────────────
mkdir -p "$DATA_DIR"

if [ -d "$SEED_DIR" ]; then
    # cp -R -n: 대상에 이미 있는 파일은 건너뛴다(종료코드 0). 디렉터리는 합쳐진다.
    # -p(소유권·시각 보존)는 쓰지 않는다 — 비 root 로는 소유권을 못 바꿔 실패한다.
    if cp -R -n "$SEED_DIR/." "$DATA_DIR/"; then
        log "씨앗 데이터 확인 완료: $SEED_DIR → $DATA_DIR (있는 파일은 그대로 둠)"
    else
        # 볼륨을 못 쓰는 상태(권한 문제)일 수 있다. 죽이지는 않고 크게 남긴다.
        log "경고: 씨앗 데이터를 복사하지 못했습니다. $DATA_DIR 쓰기 권한을 확인하세요."
    fi
else
    log "씨앗 데이터가 없습니다: $SEED_DIR (건너뜀)"
fi

# ── 2) 저장소 기준 data/ 를 볼륨으로 연결 ───────────────────────────────
if [ "$DATA_DIR" != "$REPO_DATA_DIR" ]; then
    if [ -L "$REPO_DATA_DIR" ]; then
        :  # 이미 링크가 있다 (컨테이너 재시작)
    elif [ ! -e "$REPO_DATA_DIR" ]; then
        ln -s "$DATA_DIR" "$REPO_DATA_DIR"
        log "링크 생성: $REPO_DATA_DIR → $DATA_DIR"
    elif [ -d "$REPO_DATA_DIR" ] && rmdir "$REPO_DATA_DIR" 2>/dev/null; then
        # 빈 디렉터리일 때만 치운다. 내용이 있으면 아래 경고로 빠진다.
        ln -s "$DATA_DIR" "$REPO_DATA_DIR"
        log "링크 생성: $REPO_DATA_DIR → $DATA_DIR"
    else
        log "경고: $REPO_DATA_DIR 에 내용이 있어 링크를 만들지 않았습니다."
        log "      앱이 DATA_DIR 을 읽지 않는 버전이면 데이터가 볼륨 밖에 쌓일 수 있습니다."
    fi
fi

# ── 3) 실행 ────────────────────────────────────────────────────────────
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

log "uvicorn 시작: 0.0.0.0:${PORT} (DATA_DIR=${DATA_DIR})"
# 워커는 1개로 둔다. 저장소가 파일(JSON)이라 여러 프로세스가 같은 파일을 쓰면
# 원자적 교체(os.replace)만으로는 순서를 보장하지 못한다.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --app-dir "$APP_DIR" \
    --workers 1
