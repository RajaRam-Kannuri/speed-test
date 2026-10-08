#!/usr/bin/env python3
"""Create the .env settings file with freshly generated secret keys and passwords.

Usage (from the project folder):  python3 scripts/setup-env.py
Standard library only, so it works on any computer with Python 3.
"""

import base64
import os
import secrets
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, ".env")

if os.path.exists(TARGET) and "--force" not in sys.argv:
    print(".env already exists, so nothing was changed. Run with --force to replace it.")
    sys.exit(0)

values = {
    "LLX_SECRET_KEY": secrets.token_urlsafe(48),
    # A Fernet key is 32 random bytes, URL-safe base64 encoded.
    "LLX_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "POSTGRES_PASSWORD": secrets.token_urlsafe(18),
    "MINIO_ROOT_PASSWORD": secrets.token_urlsafe(18),
}

lines = []
with open(os.path.join(ROOT, ".env.example")) as fh:
    for line in fh:
        key = line.split("=", 1)[0].strip()
        lines.append(f"{key}={values[key]}\n" if key in values and not line.startswith("#") else line)

with open(TARGET, "w") as fh:
    fh.writelines(lines)
print("Created .env with new secret keys and passwords.")
print("Optional: to use Claude, open .env and paste your key after LLX_ANTHROPIC_API_KEY=")
