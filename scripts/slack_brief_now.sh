#!/usr/bin/env bash
# 회사 서버(ksh) 평일 아침 슬랙 브리핑(2.6.0) — collect_now.sh 와 같은 꼴.
#
#   bash ~/bidpilot/current/scripts/slack_brief_now.sh               # 지금 한 번 보낸다(시험 · --force — 평일 · 하루 한 번 검사를 건너뜀)
#   bash ~/bidpilot/current/scripts/slack_brief_now.sh --scheduled   # cron(평일 07:40 · 09:40 · 11:40) — 하루 한 번 · 오늘 목록을 받은 뒤
#   bash ~/bidpilot/current/scripts/slack_brief_now.sh --preview     # 보내지 않고 글만 화면에
#
# 슬랙 주소는 .env 의 SLACK_WEBHOOK_URL(비밀 · 600) — 없으면 보내지 않고 로그에 「꺼 둠」 한 줄.
# 결과는 $DATA_DIR/private/logs/slack_brief.log 에 JSON 한 줄(주소는 싣지 않음) · 오류는 slack_brief.err.
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
cd "$APP/backend" || exit 1
case "${1:-}" in
  --preview) exec .venv/bin/python ../scripts/send_slack_brief.py ;;
  --scheduled) MODE="--run" ;;
  "") MODE="--run --force" ;;
  *)
    # 모르는 인자(--help · 오타)를 「지금 보내기」로 받지 않는다 — 회사 채널에 글이 가는 일이라서
    echo "쓰는 법: slack_brief_now.sh            지금 한 번 보내기(시험)" >&2
    echo "        slack_brief_now.sh --preview  보내지 않고 글만 보기" >&2
    echo "        slack_brief_now.sh --scheduled  cron(평일 · 하루 한 번)" >&2
    exit 2 ;;
esac
# shellcheck disable=SC2086
.venv/bin/python ../scripts/send_slack_brief.py $MODE --json >> "$LOG/slack_brief.log" 2>> "$LOG/slack_brief.err"
code=$?
if [ -t 1 ]; then
  if [ $code -eq 0 ]; then
    echo "끝났습니다 — 로그 마지막 줄: $(tail -n 1 "$LOG/slack_brief.log" | cut -c1-200)"
  else
    echo "보내기 실패(종료 코드 $code) — $LOG/slack_brief.log 마지막 줄 · $LOG/slack_brief.err 를 보세요"
  fi
fi
exit $code
