#!/usr/bin/env bash
# 회사 서버(ksh) 「지금 받기」 — 노트북 scripts\지금_받기.bat 과 같다(42차 · prompt_32 3-B).
#
#   bash ~/bidpilot/current/scripts/collect_now.sh               # 지금 받기 — 「하루 한 번」 검사를 건너뜀(--force) · 받기 잠금은 지킴
#   bash ~/bidpilot/current/scripts/collect_now.sh --scheduled   # cron(매일 07:30) — 하루 한 번 검사를 지킴
#
# 결과는 $DATA_DIR/private/logs/collect_daily.log 에 JSON 한 줄(화면 「받은 때 한 줄」이 읽는다) · 오류는 collect_daily.err.
# 종료 코드는 collect_daily.py 그대로 — 0 정상(오늘 이미 받음 포함) · 1 조회 실패 · 3 이미 받는 중 · 4 네트워크 없음.
set -u
umask 077
APP="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${BIDPILOT_ENV_FILE:-$HOME/bidpilot/.env}"
if [ ! -r "$ENV_FILE" ]; then
  echo "설정 파일이 없습니다: $ENV_FILE" >&2
  exit 1
fi
set -a
. "$ENV_FILE"
set +a
LOG="${DATA_DIR:?설정에 DATA_DIR 이 없습니다}/private/logs"
mkdir -p "$LOG"
FORCE="--force"
[ "${1:-}" = "--scheduled" ] && FORCE=""
cd "$APP/backend" || exit 1
# shellcheck disable=SC2086
.venv/bin/python ../scripts/collect_daily.py --run --json $FORCE >> "$LOG/collect_daily.log" 2>> "$LOG/collect_daily.err"
code=$?
if [ -t 1 ]; then
  case $code in
    0) echo "끝났습니다 — 로그 마지막 줄: $(tail -n 1 "$LOG/collect_daily.log" | cut -c1-160)" ;;
    3) echo "이미 받는 중입니다 — 잠시 뒤 다시 실행하세요" ;;
    4) echo "인터넷 연결이 없어 받지 않았습니다 — 연결을 확인하고 다시 실행하세요" ;;
    *) echo "받기 실패(종료 코드 $code) — $LOG/collect_daily.err 를 보세요" ;;
  esac
fi
exit $code
