"""사내 배포용 사용자 계정 관리 (계약서 1장 · 0917.md §4-5).

    backend/.venv/Scripts/python.exe scripts/manage_users.py list
    backend/.venv/Scripts/python.exe scripts/manage_users.py add hong --role editor --name 홍길동
    backend/.venv/Scripts/python.exe scripts/manage_users.py passwd hong
    backend/.venv/Scripts/python.exe scripts/manage_users.py disable hong
    backend/.venv/Scripts/python.exe scripts/manage_users.py enable hong
    backend/.venv/Scripts/python.exe scripts/manage_users.py role hong viewer

규칙
- **비밀번호는 프롬프트로만 받는다.** 인자·환경변수로 받지 않는다 — 인자는 셸 기록(`history`)과
  프로세스 목록(`ps`)에 그대로 남는다. 두 번 입력받아 오타도 거른다.
- `list` 는 해시를 출력하지 않는다. 화면·터미널 기록에 해시가 남을 이유가 없다.
- 계정 파일은 `data/private/users.json` 이다. `data/private/` 는 통째로 .gitignore 대상이라
  커밋되지 않는다 — 그래도 **절대 커밋하지 마라**(계약서 7장).
- 계정을 지우는 명령은 두지 않았다. 끄기(`disable`) · 다시 켜기(`enable`)만 한다 — 누가 있었는지는 남아야 한다.
- 역할 바꾸기는 `role <아이디> <admin|editor|viewer>`(44차 OPS-07 — 예전에는 계정 파일을 손으로 고쳤다). 바로 적용된다.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services import user_service  # noqa: E402


def _prompt_new_password() -> str:
    """새 비밀번호를 두 번 받아 확인한다. 화면에 찍지 않는다."""
    first = getpass.getpass("새 비밀번호: ")
    second = getpass.getpass("새 비밀번호 확인: ")
    if first != second:
        raise user_service.UserError("두 번 입력한 비밀번호가 다릅니다.")
    return user_service.validate_password(first)


#: 역할 한국어(45차 L9 — 「editor」만 보였다). 명령에 적는 값은 영어 그대로다.
ROLE_WORDS = {"admin": "관리자", "editor": "편집자", "viewer": "열람자"}


def _role(role: str) -> str:
    return f"{ROLE_WORDS.get(role, role)}({role})"


def _where() -> str:
    """계정 파일 위치. 가능하면 저장소 기준 상대 경로로 보여 준다."""
    path = user_service.USERS_FILE
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def cmd_add(args: argparse.Namespace) -> int:
    user = user_service.validate_user_id(args.user)
    role = user_service.validate_role(args.role)
    # 45차 L9 — 이미 있는 아이디면 **묻기 전에** 끝낸다(비밀번호를 두 번 친 뒤에야 실패했다). 진짜 판정은 add_user 가 다시 한다.
    if user_service.find_user(user) is not None:
        raise user_service.UserError(f"이미 있는 아이디입니다: {user} — 역할은 role · 비밀번호는 passwd · 끈 계정은 enable")
    password = _prompt_new_password()
    record = user_service.add_user(user, password, role=role, display_name=args.name)
    print(f"계정을 만들었습니다: {record.user} ({record.display_name} · {_role(record.role)})")
    print(f"저장 위치: {_where()}")
    return 0


def cmd_passwd(args: argparse.Namespace) -> int:
    # 없는 아이디면 **묻기 전에** 끝낸다. 새 비밀번호를 두 번 치고 나서 「없는 아이디입니다」를
    # 보는 것은 시간 낭비다. 진짜 판정은 아래 set_password 가 다시 한다.
    if user_service.find_user(args.user) is None:
        raise user_service.UserError(f"없는 아이디입니다: {args.user}")
    password = _prompt_new_password()
    record = user_service.set_password(args.user, password)
    print(f"비밀번호를 바꿨습니다: {record.user}")
    return 0


def cmd_disable(args: argparse.Namespace) -> int:
    record = user_service.set_active(args.user, False)
    print(f"계정을 껐습니다: {record.user}")
    print(f"다시 켜려면: enable {record.user}")
    return 0


def cmd_enable(args: argparse.Namespace) -> int:
    record = user_service.set_active(args.user, True)
    print(f"계정을 다시 켰습니다: {record.user} ({_role(record.role)})")
    return 0


def cmd_role(args: argparse.Namespace) -> int:
    record = user_service.set_role(args.user, args.role)
    print(f"역할을 바꿨습니다: {record.user} → {_role(record.role)}")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    records = user_service.load_users()
    if not records:
        print(f"등록된 사용자가 없습니다. ({_where()} 없음 또는 비어 있음)")
    else:
        print(f"등록된 사용자 {len(records)}명 ({_where()})")
        print(f"{'아이디':<20}{'표시이름':<16}{'역할':<16}{'상태':<8}생성(UTC)")
        for record in records:
            state = "사용" if record.active else "정지"
            created = record.created_at[:19] if record.created_at else "-"
            # 비밀번호 해시는 출력하지 않는다 (계약서 7장).
            print(f"{record.user:<20}{record.display_name:<16}{_role(record.role):<16}{state:<8}{created}")
    if user_service.demo_account_enabled():
        # 아이디·비밀번호 값은 찍지 않는다. 「켜져 있다」는 사실만 알린다.
        print("환경변수 DEMO_USER/DEMO_PASSWORD 로 공용 계정이 함께 인정됩니다(역할: admin).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="계정 만들기 (비밀번호는 프롬프트로 입력)")
    add.add_argument("user", help="아이디 (영문 소문자·숫자로 시작, 2~32자)")
    add.add_argument(
        "--role",
        default=user_service.DEFAULT_ROLE,
        choices=list(user_service.ROLES),
        help=f"역할 — admin(관리자) · editor(편집자) · viewer(열람자) · 기본 {user_service.DEFAULT_ROLE}",
    )
    add.add_argument("--name", default=None, help="화면에 보일 이름 (기본: 아이디와 같음)")
    add.set_defaults(func=cmd_add)

    passwd = sub.add_parser("passwd", help="비밀번호 바꾸기 (프롬프트로 입력)")
    passwd.add_argument("user", help="아이디")
    passwd.set_defaults(func=cmd_passwd)

    disable = sub.add_parser("disable", help="계정 끄기 (기록은 남긴다 · 다시 켜기는 enable)")
    disable.add_argument("user", help="아이디")
    disable.set_defaults(func=cmd_disable)

    enable = sub.add_parser("enable", help="끈 계정 다시 켜기")
    enable.add_argument("user", help="아이디")
    enable.set_defaults(func=cmd_enable)

    role = sub.add_parser("role", help="역할 바꾸기 — admin(관리자) · editor(편집자) · viewer(열람자)")
    role.add_argument("user", help="아이디")
    role.add_argument("role", choices=list(user_service.ROLES), help="새 역할 — admin(관리자) · editor(편집자) · viewer(열람자)")
    role.set_defaults(func=cmd_role)

    listing = sub.add_parser("list", help="계정 목록 (해시는 출력하지 않는다)")
    listing.set_defaults(func=cmd_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except user_service.UserError as exc:
        # 값이 아니라 사유만 나온다(UserError 는 값을 담지 않는다).
        print(f"실패: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\n취소했습니다.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
