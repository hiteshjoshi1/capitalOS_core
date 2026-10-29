"""Set a user's password from the home machine (#72), for when it's forgotten.

Run through `make user-set-password USERNAME=<name>`. The password is read from the
terminal (never the command line, so it stays out of shell history) and every session
of that user is signed out.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.passwords import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, set_user_password


def main() -> int:
    parser = argparse.ArgumentParser(description="Set a CapitalOS user's password.")
    parser.add_argument("username")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT id, username FROM users WHERE LOWER(username) = LOWER(:username)"),
            {"username": args.username.strip()},
        ).mappings().one_or_none()
        if row is None:
            print(f"No user named {args.username!r}.", file=sys.stderr)
            return 1

        password = getpass.getpass(f"New password for {row['username']}: ")
        if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
            print(f"The password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters.", file=sys.stderr)
            return 1
        if getpass.getpass("Again: ") != password:
            print("The passwords don't match; nothing changed.", file=sys.stderr)
            return 1

        signed_out = set_user_password(
            db, user_id=int(row["id"]), new_password=password, revoke_reason="password_reset"
        )
        db.commit()
        print(f"Password set for {row['username']}; signed out {signed_out} session(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
