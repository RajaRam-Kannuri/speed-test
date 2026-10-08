#!/usr/bin/env bash
# Start/stop the local development stack (API, worker, sample app, frontend) using PID files.
# Usage: scripts/dev-services.sh start|stop|restart [api|worker|sample|web]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/.dev"; mkdir -p "$RUN"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/opt/pw-browsers}"

start_one() {
  local name="$1"; shift
  if [[ -f "$RUN/$name.pid" ]] && kill -0 "$(cat "$RUN/$name.pid")" 2>/dev/null; then echo "$name already running"; return; fi
  local dir="$1"; shift
  # The child writes its own PID (= its session/process-group id) before exec, so stop can kill the whole group.
  ( cd "$dir" && setsid bash -c 'echo $$ > "$0"; exec "$@"' "$RUN/$name.pid" "$@" > "$RUN/$name.log" 2>&1 < /dev/null & )
  sleep 0.5
  echo "started $name (log: .dev/$name.log)"
}

stop_one() {
  local name="$1"
  if [[ -f "$RUN/$name.pid" ]]; then
    local pid; pid="$(cat "$RUN/$name.pid")"
    kill -TERM -- "-$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    kill -KILL -- "-$pid" 2>/dev/null || true
    rm -f "$RUN/$name.pid"; echo "stopped $name"
  fi
}

start_svc() {
  case "$1" in
    api) start_one api "$ROOT/backend" python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 ;;
    worker) start_one worker "$ROOT/backend" celery -A app.worker.celery_app worker -l info -c 2 -Q lorvenlax ;;
    sample) start_one sample "$ROOT/sample-app" python3 -m uvicorn app:app --host 0.0.0.0 --port 8100 ;;
    web) start_one web "$ROOT/frontend" npm run start -- -p 3000 ;;
  esac
}

cmd="${1:-start}"; shift || true
services=("${@:-api worker sample}"); read -r -a services <<< "${services[*]}"
for s in "${services[@]}"; do
  case "$cmd" in
    start) start_svc "$s" ;;
    stop) stop_one "$s" ;;
    restart) stop_one "$s"; sleep 1; start_svc "$s" ;;
  esac
done
