#!/usr/bin/env python3
"""Trigger a LorvenLax run from CI and wait for the real result.

Environment:
  LORVENLAX_URL         e.g. https://lorvenlax.example.com   (required)
  LORVENLAX_TOKEN       project API token (llx_...)           (required)
  LORVENLAX_PROJECT_ID  project id                            (required)
  LORVENLAX_SUITE_ID    suite to run, or
  LORVENLAX_TEST_IDS    comma-separated test case ids
  LORVENLAX_BROWSER     chromium | firefox | webkit (default chromium)
  LORVENLAX_ENVIRONMENT_ID, LORVENLAX_RETRIES, LORVENLAX_WORKERS (optional)
  LORVENLAX_IDEMPOTENCY_KEY  e.g. the pipeline id, so a retried job does not start a second run
  LORVENLAX_ALLURE_DIR  if set, Allure results are extracted here

Exit code: 0 when every test passed, 1 when any failed, 2 on errors.
Standard library only, so it runs on any CI image with Python 3.8+.
"""

import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile


def env(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        sys.exit(f"error: {name} is not set")
    return value


BASE = env("LORVENLAX_URL", required=True).rstrip("/")
TOKEN = env("LORVENLAX_TOKEN", required=True)
PROJECT = env("LORVENLAX_PROJECT_ID", required=True)


def call(method, path, body=None, raw=False):
    req = urllib.request.Request(f"{BASE}/api{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
            return data if raw else json.loads(data or b"null")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:1000]
        print(f"error: {method} {path} returned {exc.code}: {detail}", file=sys.stderr)
        sys.exit(2)


def main():
    body = {
        "browser": env("LORVENLAX_BROWSER", "chromium"),
        "retries": int(env("LORVENLAX_RETRIES", "0")),
        "workers": int(env("LORVENLAX_WORKERS", "2")),
        "trigger": "ci",
    }
    if env("LORVENLAX_SUITE_ID"):
        body["suite_id"] = env("LORVENLAX_SUITE_ID")
    if env("LORVENLAX_TEST_IDS"):
        body["test_case_ids"] = [t.strip() for t in env("LORVENLAX_TEST_IDS").split(",") if t.strip()]
    if not body.get("suite_id") and not body.get("test_case_ids"):
        sys.exit("error: set LORVENLAX_SUITE_ID or LORVENLAX_TEST_IDS")
    if env("LORVENLAX_ENVIRONMENT_ID"):
        body["environment_id"] = env("LORVENLAX_ENVIRONMENT_ID")
    if env("LORVENLAX_IDEMPOTENCY_KEY"):
        body["idempotency_key"] = env("LORVENLAX_IDEMPOTENCY_KEY")

    run = call("POST", f"/projects/{PROJECT}/executions", body)
    print(f"LorvenLax run {run['id']} started ({run['total']} tests, {run['browser']})")
    deadline = time.time() + 60 * 60
    while run["status"] in ("queued", "running", "cancelling"):
        if time.time() > deadline:
            sys.exit("error: run did not finish within 60 minutes")
        time.sleep(5)
        run = call("GET", f"/executions/{run['id']}")
    print(f"Result: {run['status']} - {run['passed']}/{run['total']} passed, {run['failed']} failed, {run['flaky']} flaky")
    for r in run.get("results", []):
        if r["status"] not in ("passed", "flaky"):
            label = (r.get("failure") or {}).get("label") or "Unknown"
            print(f"  FAILED  {r['test_title']}  [{label}]")
            if r.get("error_message"):
                print("          " + r["error_message"].splitlines()[0][:200])
    print(f"Details: {BASE}/runs/{run['id']}")

    allure_dir = env("LORVENLAX_ALLURE_DIR")
    if allure_dir:
        data = call("GET", f"/executions/{run['id']}/report?format=allure", raw=True)
        zipfile.ZipFile(io.BytesIO(data)).extractall(allure_dir)
        print(f"Allure results written to {allure_dir}")
    sys.exit(0 if run["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
