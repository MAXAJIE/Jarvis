"""Creates the single operator's credentials and prints one TOTP URI.

Run it, scan the URI with an authenticator, and paste nothing back here: the
script writes the hash and the secret into .env, which is gitignored.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

import pyotp

from apps.api.auth import hash_password
from apps.api.config import ENV_FILE, REPO_ROOT, ensure_secret_key, get_settings


def upsert_env(key: str, value: str) -> None:
    path: Path = REPO_ROOT / ENV_FILE
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for index, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[index] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    settings = get_settings()
    if settings.operator_password_hash:
        print("credentials already exist in .env; remove OPERATOR_PASSWORD_HASH first")
        return 1
    password = sys.stdin.readline().strip() if not sys.stdin.isatty() else ""
    if not password:
        import getpass

        password = getpass.getpass("operator password: ")
        if password != getpass.getpass("repeat: "):
            print("passwords do not match")
            return 2
    if len(password) < 12:
        print("use at least 12 characters")
        return 3

    secret = pyotp.random_base32()
    upsert_env("OPERATOR_PASSWORD_HASH", hash_password(password))
    upsert_env("OPERATOR_TOTP_SECRET", secret)
    upsert_env("OPERATOR_EMAIL", settings.operator_email)
    ensure_secret_key()
    _ = secrets
    print("\nAdd this to your authenticator app:")
    print(pyotp.TOTP(secret).provisioning_uri(name=settings.operator_email, issuer_name="Jarvis"))
    print("\nWrote OPERATOR_PASSWORD_HASH, OPERATOR_TOTP_SECRET to .env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
