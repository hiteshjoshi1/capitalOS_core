"""Create users and grant/revoke admin from the home machine (#152).

Signup is off by default, so the first account is made here:

    make user-create USERNAME=<name> ADMIN=1   (prompts for the password, never on the command line)
    make user-grant-admin USERNAME=<name>
    make user-revoke-admin USERNAME=<name>

Admins may change shared data: platforms, currencies, the token allowlist and the
market-data refresh.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.services.auth import hash_password
from app.services.passwords import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH


def _find_user(db: Session, username: str):
    return db.execute(
        text("SELECT id, username, COALESCE(is_admin, FALSE) AS is_admin FROM users WHERE LOWER(username) = LOWER(:u)"),
        {"u": username.strip()},
    ).mappings().one_or_none()


def _create(db: Session, username: str, *, admin: bool) -> int:
    username = username.strip()
    if not username:
        print("A username is required.", file=sys.stderr)
        return 1
    if _find_user(db, username) is not None:
        print(f"A user named {username!r} already exists.", file=sys.stderr)
        return 1
    password = getpass.getpass(f"Password for {username}: ")
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        print(f"The password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters.", file=sys.stderr)
        return 1
    if getpass.getpass("Again: ") != password:
        print("The passwords don't match; nothing changed.", file=sys.stderr)
        return 1
    now = datetime.now(tz=timezone.utc)
    user_id = db.execute(
        text(
            """
            INSERT INTO users (username, display_name, is_active, is_admin, created_at, updated_at)
            VALUES (:username, :username, TRUE, :is_admin, :now, :now)
            RETURNING id
            """
        ),
        {"username": username, "is_admin": admin, "now": now},
    ).scalar_one()
    db.execute(
        text(
            """
            INSERT INTO user_credentials (user_id, password_hash, password_algo, password_updated_at)
            VALUES (:user_id, :password_hash, 'argon2id', :now)
            """
        ),
        {"user_id": int(user_id), "password_hash": hash_password(password), "now": now},
    )
    db.commit()
    print(f"Created {username}{' (admin)' if admin else ''}.")
    return 0


def _set_admin(db: Session, username: str, *, admin: bool) -> int:
    row = _find_user(db, username)
    if row is None:
        print(f"No user named {username!r}.", file=sys.stderr)
        return 1
    db.execute(
        text("UPDATE users SET is_admin = :admin, updated_at = :now WHERE id = :id"),
        {"admin": admin, "now": datetime.now(tz=timezone.utc), "id": int(row["id"])},
    )
    db.commit()
    print(f"{row['username']} is {'now' if admin else 'no longer'} an admin.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage CapitalOS users.")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="create a user (prompts for the password)")
    create.add_argument("username")
    create.add_argument("--admin", action="store_true")
    sub.add_parser("grant-admin").add_argument("username")
    sub.add_parser("revoke-admin").add_argument("username")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.command == "create":
            return _create(db, args.username, admin=args.admin)
        return _set_admin(db, args.username, admin=args.command == "grant-admin")
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
