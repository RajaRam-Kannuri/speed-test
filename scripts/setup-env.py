#!/usr/bin/env python3
"""Create or complete the .env settings file with generated secret keys and passwords.

Usage (from the project folder):  python3 scripts/setup-env.py
- If .env does not exist, it is created from .env.example.
- If .env exists, blank or placeholder secrets are filled in; values you already set are kept.
- --force regenerates all four secrets (only do this before the first start: the database
  password and encryption key must not change once data exists).
Standard library only, so it works on any computer with Python 3.
"""

import base64
import os
import secrets
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, ".env")
PLACEHOLDERS = {"", "change-me", "change-me-too"}

generators = {
    "LLX_SECRET_KEY": lambda: secrets.token_urlsafe(48),
    # A Fernet key is 32 random bytes, URL-safe base64 encoded.
    "LLX_ENCRYPTION_KEY": lambda: base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(18),
    "MINIO_ROOT_PASSWORD": lambda: secrets.token_urlsafe(18),
}
force = "--force" in sys.argv

source = TARGET if os.path.exists(TARGET) else os.path.join(ROOT, ".env.example")
with open(source) as fh:
    lines = fh.readlines()

seen, filled, out = set(), [], []
for line in lines:
    key, sep, value = line.partition("=")
    key = key.strip()
    if sep and not line.lstrip().startswith("#") and key in generators:
        seen.add(key)
        if force or value.strip() in PLACEHOLDERS:
            line = f"{key}={generators[key]()}\n"
            filled.append(key)
    out.append(line)
for key in generators:  # keys missing entirely from an older .env
    if key not in seen:
        out.append(f"{key}={generators[key]()}\n")
        filled.append(key)

with open(TARGET, "w") as fh:
    fh.writelines(out)

if filled:
    print(f"{'Created' if source != TARGET else 'Updated'} .env: generated {', '.join(filled)}.")
else:
    print(".env already has all secret keys and passwords. Nothing changed.")
print("Optional: to use Claude, open .env and paste your key after LLX_ANTHROPIC_API_KEY=")
