#!/usr/bin/env bash
# 서버 한 판 켜기 · 되돌리기(42차 · prompt_32 3-G). 노트북 scripts/deploy_server.ps1 이 부른다.
#
#   bash ~/bidpilot/releases/<해시>/deploy/server/activate.sh                 # 새 판: 의존성 · 빌드 → current 바꾸기 → 재시작 → health
#   bash ~/bidpilot/current/deploy/server/activate.sh --rollback               # 이전 판(PREVIOUS)으로 current 를 되돌리고 재시작
#   bash ~/bidpilot/current/deploy/server/activate.sh --rollback <판 폴더>     # 그 판으로(시험용 가짜 판으로 검사가 멈추는지 볼 때)
#   bash ~/bidpilot/current/deploy/server/activate.sh --check                  # 판마다 묶음 검사 · 비밀 값 파일 수(값은 출력하지 않음)
#
# health 가 안 살아나면 이전 판으로 저절로 되돌린다. 데이터(~/bidpilot-data) · 설정(~/bidpilot/.env)은 건드리지 않는다.
set -euo pipefail
umask 077
BASE="$HOME/bidpilot"
export PATH="$HOME/.nvm/versions/node/v22.23.4/bin:$HOME/.local/bin:$PATH"
log() { echo "[$(date +%T)] $*"; }

switch_to() { ln -sfn "$1" "$BASE/current.tmp" && mv -Tf "$BASE/current.tmp" "$BASE/current"; }

restart() {
  mkdir -p "$HOME/.config/systemd/user"
  cp "$BASE/current/deploy/server/bidpilot-api.service" "$BASE/current/deploy/server/bidpilot-web.service" "$HOME/.config/systemd/user/"
  systemctl --user daemon-reload
  systemctl --user enable -q bidpilot-api bidpilot-web
  systemctl --user restart bidpilot-api bidpilot-web
}

# 백엔드 health 가 ok(판을 주면 그 판)이고 로그인 화면이 200 이면 산 것이다. 2분까지 기다린다.
healthy() {
  local want="${1:-}" body code
  for _ in $(seq 1 40); do
    body="$(curl -fsS -m 5 http://127.0.0.1:18310/health 2>/dev/null || true)"
    code="$(curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:18320/login || true)"
    if echo "$body" | grep -q '"status":"ok"' && [ "$code" = "200" ] && { [ -z "$want" ] || echo "$body" | grep -q "\"version\":\"$want\""; }; then
      return 0
    fi
    sleep 3
  done
  return 1
}

# 화면 묶음 검사(43차 SEC-01) — 새 판을 켤 때와 **되돌릴 때 모두** 한다. 걸리면 까닭 한 줄을 내고 1.
#  - 브라우저 묶음에 localhost:8110 이 있으면 로그인 뒤 화면이 사용자 PC 의 8110 을 불러 데이터 화면이 모두 깨진다(42차 마지막 검토).
#  - 로그인 게이트를 지나는 업로드 상한이 20MB 보다 작으면(기본 10MB) 회사자료 업로드가 잘린다(next.config proxyClientMaxBodySize).
check_bundle() {
  local dir="$1" size
  if [ ! -d "$dir/frontend/.next/static" ]; then
    echo "화면 빌드가 없습니다($(basename "$dir"))"
    return 1
  fi
  if grep -rlq "localhost:8110" "$dir/frontend/.next/static"; then
    echo "화면 묶음에 localhost:8110 이 남았습니다 — 로그인 뒤 데이터 화면이 깨지는 판입니다($(basename "$dir"))"
    return 1
  fi
  size="$(grep -o '"proxyClientMaxBodySize": *[0-9]*' "$dir/frontend/.next/required-server-files.json" 2>/dev/null | grep -o '[0-9]*$' || true)"
  if [ -z "$size" ] || [ "$size" -lt 20971520 ]; then
    echo "업로드 상한이 20MB 보다 작습니다(${size:-설정 없음} 바이트) — 회사자료 업로드가 잘리는 판입니다($(basename "$dir"))"
    return 1
  fi
  return 0
}

# 판 폴더의 화면 빌드에 .env 비밀 값이 든 파일 수(43차 BUILD-01). **값은 출력하지 않는다** — 수만.
secret_files() {
  local dir="$1" pattern count
  [ -d "$dir/frontend/.next" ] || { echo 0; return; }
  pattern="$(mktemp)"
  # 이름에 SECRET · TOKEN · PASSWORD · KEY 가 든 칸의 값(8자 이상)만 — 값은 이 임시 파일(600)에만 두고 바로 지운다
  sed -n 's/^\([A-Z0-9_]*\(SECRET\|TOKEN\|PASSWORD\|KEY\)[A-Z0-9_]*\)=\(.*\)$/\3/p' "$BASE/.env" 2>/dev/null \
    | sed 's/^["'"'"']//; s/["'"'"']$//' | awk 'length($0) >= 8' > "$pattern" || true
  if [ -s "$pattern" ]; then
    count="$(grep -rlF -f "$pattern" "$dir/frontend/.next" 2>/dev/null | wc -l || true)"
  else
    count=0
  fi
  rm -f "$pattern"
  echo "${count:-0}"
}

if [ "${1:-}" = "--check" ]; then
  for dir in "$BASE"/releases/*/; do
    dir="${dir%/}"
    if reason="$(check_bundle "$dir")"; then reason="묶음 검사 통과"; fi
    echo "$(basename "$dir") · $reason · 비밀 값 파일 $(secret_files "$dir")"
  done
  exit 0
fi

if [ "${1:-}" = "--rollback" ]; then
  TARGET="${2:-$(cat "$BASE/PREVIOUS" 2>/dev/null || true)}"
  [ -n "$TARGET" ] && [ -d "$TARGET" ] || { log "되돌릴 이전 판이 없습니다"; exit 1; }
  TARGET="$(readlink -f "$TARGET")"
  # 43차 SEC-01 — 되돌릴 판도 묶음 검사를 한다. 걸리면 되돌리지 않고 멈춘다(망가진 판으로 가서 「되돌림 · 0」으로 끝났다).
  if ! reason="$(check_bundle "$TARGET")"; then
    log "되돌리지 않습니다 — $reason. 지금 켜진 판은 그대로입니다"
    exit 3
  fi
  NOW="$(readlink -f "$BASE/current")"
  switch_to "$TARGET"
  restart
  if ! healthy ""; then
    log "되돌린 판이 안 살아납니다 — 원래 판 $(basename "$NOW") 으로 다시 돌립니다"
    switch_to "$NOW"
    restart
    exit 1
  fi
  echo "$NOW" > "$BASE/PREVIOUS"
  basename "$TARGET" > "$BASE/RELEASE"
  log "되돌림 — $(basename "$TARGET")"
  exit 0
fi

NEW="$(cd "$(dirname "$0")/../.." && pwd)"
HASH="$(cat "$NEW/RELEASE")"
VER="$(sed -n 's/^APP_VERSION = "\(.*\)"$/\1/p' "$NEW/backend/app/main.py")"

log "백엔드 의존성(고정 판 · requirements.lock.txt)"
cd "$NEW/backend"
uv venv -q --python 3.12 .venv
uv pip install -q --python .venv/bin/python -r requirements.lock.txt

log "화면 의존성 · 빌드(로그 $NEW/build.log)"
cd "$NEW/frontend"
npm ci --no-audit --no-fund --loglevel=error > "$NEW/build.log" 2>&1
# 43차 BUILD-01 — 빌드에는 **필요한 값만** 넘긴다(.env 를 통째로 읽히면 세션 비밀 · 토큰 · 서비스키가 빌드 캐시에 남았다).
# 화면이 읽는 값 중 빌드 때 묶음에 들어가는 것은 NEXT_PUBLIC_* 뿐이고, 로그인 · 중계 값은 실행 때 서비스가 .env 로 읽는다.
# NEXT_PUBLIC_BACKEND_URL 은 빈 값으로 고정한다 — 정의하지 않으면 브라우저 묶음에 기본값 http://localhost:8110 이 박힌다(42차).
ORG_ID="$(sed -n 's/^NEXT_PUBLIC_DEFAULT_ORGANIZATION_ID=//p' "$BASE/.env" 2>/dev/null | tail -n 1 | sed "s/^[\"']//; s/[\"']\$//")"
if ! env -i HOME="$HOME" PATH="$PATH" LANG=C.UTF-8 NODE_ENV=production NODE_OPTIONS=--max-old-space-size=2048 \
       NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_BACKEND_URL="" ${ORG_ID:+NEXT_PUBLIC_DEFAULT_ORGANIZATION_ID="$ORG_ID"} \
       node node_modules/next/dist/bin/next build >> "$NEW/build.log" 2>&1; then
  log "빌드 실패 — 지금 켜진 판은 그대로입니다. $NEW/build.log 를 보세요"
  exit 1
fi
# 빌드 캐시는 실행에 쓰지 않는다 — 지운다(옛 판에 남은 캐시도 · 43차 BUILD-01)
rm -rf "$NEW/frontend/.next/cache"
for old in "$BASE"/releases/*/; do rm -rf "${old%/}/frontend/.next/cache"; done
if ! reason="$(check_bundle "$NEW")"; then
  log "$reason — 켜지 않습니다(지금 켜진 판은 그대로)"
  exit 1
fi
LEAKS="$(secret_files "$NEW")"
if [ "$LEAKS" != "0" ]; then
  log "빌드 결과에 비밀 값이 든 파일 ${LEAKS}개 — 켜지 않습니다(지금 켜진 판은 그대로)"
  exit 1
fi

PREV="$(readlink -f "$BASE/current" 2>/dev/null || true)"
switch_to "$NEW"
restart
if healthy "$VER"; then
  [ -n "$PREV" ] && [ "$PREV" != "$NEW" ] && echo "$PREV" > "$BASE/PREVIOUS"
  echo "$HASH" > "$BASE/RELEASE"
  # 옛 판은 셋(지금 · 이전 · 그 전)만 남긴다 — 지금 · 이전 판 · PREVIOUS 가 가리키는 판은 지우지 않는다(같은 판을 다시 켜면 PREV = NEW 라
  # PREVIOUS 는 더 옛 판을 가리킨다 · 43차 마지막 검토). 묶음 검사에 걸리는 옛 판은 셋 안이어도 지운다(43차 SEC-01 — 그 판으로는 되돌리지도 않는다).
  KEEP="$(readlink -f "$(cat "$BASE/PREVIOUS" 2>/dev/null)" 2>/dev/null || true)"
  for old in $(ls -1dt "$BASE"/releases/*/ | tail -n +4); do
    old="${old%/}"
    [ "$old" = "$NEW" ] || [ "$old" = "$PREV" ] || [ "$old" = "$KEEP" ] || rm -rf "$old"
  done
  for old in "$BASE"/releases/*/; do
    old="${old%/}"
    if [ "$old" != "$NEW" ] && [ "$old" != "$PREV" ] && ! check_bundle "$old" > /dev/null; then
      rm -rf "$old"
      log "묶음 검사에 걸리는 옛 판을 지움 — $(basename "$old")"
    fi
  done
  log "켜짐 — $HASH (판 $VER)"
  exit 0
fi

log "health 가 안 살아납니다 — 이전 판으로 되돌립니다"
if [ -n "$PREV" ] && [ -d "$PREV" ] && [ "$PREV" != "$NEW" ]; then
  switch_to "$PREV"
  restart
  healthy "" && log "이전 판 $(basename "$PREV") 로 되돌림" || log "이전 판도 안 살아납니다 — journalctl --user -u bidpilot-api -u bidpilot-web"
fi
exit 1
