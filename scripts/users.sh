#!/usr/bin/env bash
# 회사 서버(ksh) 계정 관리(42차) — scripts/manage_users.py 를 서버 설정(~/bidpilot/.env)으로 부른다. 비밀번호는 화면에 두 번 묻는다(인자로 받지 않음).
#
#   bash ~/bidpilot/current/scripts/users.sh list
#   bash ~/bidpilot/current/scripts/users.sh add <아이디> --role admin --name "<이름>"     # 역할: admin(관리자) · editor(편집자) · viewer(열람자)
#   bash ~/bidpilot/current/scripts/users.sh passwd <아이디>
#   bash ~/bidpilot/current/scripts/users.sh disable <아이디>                 # 끄기(기록은 남김)
#   bash ~/bidpilot/current/scripts/users.sh enable <아이디>                  # 다시 켜기
#   bash ~/bidpilot/current/scripts/users.sh role <아이디> <admin|editor|viewer>   # 역할 바꾸기
set -eu
umask 077
APP="$(cd "$(dirname "$0")/.." && pwd)"
set -a
. "${BIDPILOT_ENV_FILE:-$HOME/bidpilot/.env}"
set +a
# 게이트 스위치일 뿐 계정이 아니다 — 목록에 「공용 계정이 함께 인정됩니다」로 나오지 않게(백엔드도 보지 않음 · bidpilot-api.service)
unset DEMO_USER DEMO_PASSWORD
exec "$APP/backend/.venv/bin/python" "$APP/scripts/manage_users.py" "$@"
