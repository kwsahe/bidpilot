#!/usr/bin/env bash
# 매일 03:00 — 회사 서버 data/private 백업(42차). ~/bidpilot-backups/private-YYYY-MM-DD.tar.gz · 14일 보관.
# 되살리기는 docs/deploy_server.md 「백업 되살리기」 · 확인은 `tail -n 3 ~/bidpilot-backups/backup.log`.
# 실패하면 backup.log 에 「FAIL 날짜 · 단계 · 이유 한 줄」을 남긴다(44차 OPS-05).
# 45차 SEC-R37-01 — ERR trap 은 `.env` 읽기 실패(특수 내장 명령) · 빈 DATA_DIR(set -u 확장 오류)에서 돌지 않아 FAIL 줄 없이 끝났다.
# 이제 EXIT trap 이 끝에 성공 표시(DONE=1)가 없으면 언제나 FAIL 줄을 남기고 임시 파일을 지운다.
set -eu
umask 077
DEST="$HOME/bidpilot-backups"
mkdir -p "$DEST"
STEP="설정 읽기"
ERR="$(mktemp)"
OUT=""
DONE=0
finish() {
  local code=$?
  if [ "$DONE" != 1 ]; then
    local why
    why="$(tr '\n' ' ' < "$ERR" 2>/dev/null | cut -c1-160)"
    echo "$(date '+%F %T') FAIL ${STEP} — ${why:-종료 코드 $code}" >> "$DEST/backup.log"
    if [ -n "$OUT" ]; then rm -f "$OUT.part"; fi
    if [ "$code" = 0 ]; then code=1; fi
  fi
  rm -f "$ERR"
  exit "$code"
}
trap finish EXIT
ENV_FILE="$HOME/bidpilot/.env"
if [ ! -r "$ENV_FILE" ]; then
  echo ".env 를 읽을 수 없음($ENV_FILE)" > "$ERR"
  exit 1
fi
set -a
. "$ENV_FILE" 2>"$ERR"
set +a
if [ -z "${DATA_DIR:-}" ]; then
  echo "DATA_DIR 이 .env 에 없음" > "$ERR"
  exit 1
fi
if [ ! -d "$DATA_DIR/private" ]; then
  echo "자료 폴더 없음($DATA_DIR/private)" > "$ERR"
  exit 1
fi
STEP="묶기(tar)"
OUT="$DEST/private-$(date +%F).tar.gz"
tar czf "$OUT.part" -C "$DATA_DIR" --exclude=private/.cache --exclude=private/.locks private 2>"$ERR"
mv -f "$OUT.part" "$OUT"
STEP="옛 백업 정리"
find "$DEST" -maxdepth 1 -name 'private-*.tar.gz' -mtime +13 -delete 2>"$ERR"
echo "$(date '+%F %T') $(du -h "$OUT" | cut -f1) $OUT" >> "$DEST/backup.log"
DONE=1
