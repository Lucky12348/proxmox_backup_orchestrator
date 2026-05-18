from __future__ import annotations

from getpass import getpass
import sys

from passlib.hash import bcrypt


BCRYPT_MAX_PASSWORD_BYTES = 72


def main() -> int:
    password = getpass("Password: ")
    confirmation = getpass("Confirm password: ")

    if password != confirmation:
        print("Passwords do not match.", file=sys.stderr)
        return 1

    password_bytes = password.encode("utf-8")
    if len(password_bytes) > BCRYPT_MAX_PASSWORD_BYTES:
        print(
            "Password is too long for bcrypt: "
            f"{len(password_bytes)} bytes. Maximum is {BCRYPT_MAX_PASSWORD_BYTES} bytes.",
            file=sys.stderr,
        )
        return 1

    print(f"AUTH_PASSWORD_HASH={bcrypt.hash(password)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
