"""Print the operator's current 6-digit login code.

The login form wants a code, not the secret. The secret lives in `.env` as
``OPERATOR_TOTP_SECRET``; this turns it into the number the form expects, and says
how long that number has left so a stale code is obvious rather than mysterious.

    .venv/Scripts/python.exe -m scripts.totp              # current code
    .venv/Scripts/python.exe -m scripts.totp --uri        # add to an authenticator app
    .venv/Scripts/python.exe -m scripts.totp --watch      # refresh until Ctrl-C
"""

from __future__ import annotations

import argparse
import sys
import time

import pyotp

from apps.api.config import get_settings

PERIOD_S = 30


def _remaining() -> int:
    return PERIOD_S - int(time.time()) % PERIOD_S


def main() -> int:
    parser = argparse.ArgumentParser(description="current TOTP code for this operator")
    parser.add_argument("--uri", action="store_true", help="print the otpauth:// URI")
    parser.add_argument("--watch", action="store_true", help="refresh every 30 s")
    args = parser.parse_args()

    settings = get_settings()
    secret = settings.operator_totp_secret
    if not secret:
        print("OPERATOR_TOTP_SECRET is empty in .env; run scripts/setup_operator.py first")
        return 1

    totp = pyotp.TOTP(secret)
    if args.uri:
        # Same string an authenticator app reads from a QR code. Treat it as a
        # password: it is the long-lived secret, not a one-time code.
        print(totp.provisioning_uri(name=settings.operator_email, issuer_name="Jarvis"))
        return 0

    if not args.watch:
        code = totp.now()
        print(f"{code}   ({_remaining()}s left)")
        return 0

    try:
        while True:
            code = totp.now()
            print(f"\r{code}   {_remaining():2d}s left", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main())
