#!/usr/bin/env bash
# EnPu one-click stop: kill processes started by start.sh (and free common ports)
# Usage:
#   ./scripts/stop.sh
#   ./scripts/stop.sh --ports-only   # only free 8765/1420, ignore pid file
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${ROOT}/scripts/.run"
PID_FILE="${RUN_DIR}/pids.env"
CORE_PORT="${ENPU_CORE_PORT:-8765}"
VITE_PORT="${ENPU_VITE_PORT:-1420}"
PORTS_ONLY=0

for arg in "$@"; do
  case "${arg}" in
    --ports-only) PORTS_ONLY=1 ;;
    -h|--help)
      echo "Usage: $0 [--ports-only]"
      exit 0
      ;;
  esac
done

is_windows() {
  case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW*|MSYS*|CYGWIN*) return 0 ;;
    *) return 1 ;;
  esac
}

kill_pid() {
  local pid="$1"
  local label="${2:-pid}"
  if [[ -z "${pid}" || ! "${pid}" =~ ^[0-9]+$ ]]; then
    return 0
  fi
  if ! kill -0 "${pid}" 2>/dev/null; then
    # Windows Git Bash: kill -0 may not work for all; try tasklist
    if is_windows; then
      if ! tasklist //FI "PID eq ${pid}" 2>/dev/null | grep -q "${pid}"; then
        echo "[skip] ${label}=${pid} not running"
        return 0
      fi
    else
      echo "[skip] ${label}=${pid} not running"
      return 0
    fi
  fi

  echo "[stop] ${label}=${pid}"
  if is_windows; then
    taskkill //PID "${pid}" //T //F >/dev/null 2>&1 || kill -TERM "${pid}" 2>/dev/null || true
    sleep 0.3
    taskkill //PID "${pid}" //T //F >/dev/null 2>&1 || kill -KILL "${pid}" 2>/dev/null || true
  else
    # process group if started with job control
    kill -TERM "${pid}" 2>/dev/null || true
    sleep 0.4
    if kill -0 "${pid}" 2>/dev/null; then
      kill -KILL "${pid}" 2>/dev/null || true
    fi
    # children that might reparent
    pkill -P "${pid}" 2>/dev/null || true
  fi
}

pids_on_port() {
  local port="$1"
  if is_windows; then
    # netstat: TCP  127.0.0.1:8765  ... LISTENING  1234
    netstat -ano 2>/dev/null \
      | tr -d '\r' \
      | grep -E "[:.]${port}[[:space:]].*LISTENING" \
      | awk '{print $NF}' \
      | sort -u
    return 0
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true
    return 0
  fi
  if command -v ss >/dev/null 2>&1 && command -v fuser >/dev/null 2>&1; then
    fuser -n tcp "${port}" 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+$' || true
    return 0
  fi
  return 0
}

kill_port() {
  local port="$1"
  local pids
  pids="$(pids_on_port "${port}" || true)"
  if [[ -z "${pids}" ]]; then
    echo "[port] :${port} free"
    return 0
  fi
  local pid
  for pid in ${pids}; do
    kill_pid "${pid}" "port:${port}"
  done
}

echo "========================================"
echo " EnPu stop"
echo "========================================"

if [[ "${PORTS_ONLY}" -eq 0 && -f "${PID_FILE}" ]]; then
  echo "[pids] reading ${PID_FILE}"
  # shellcheck disable=SC1090
  set -a
  # only KEY=value lines
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ -z "${line}" || "${line}" =~ ^# ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    case "${key}" in
      CORE_PID|VITE_PID|TAURI_PID)
        kill_pid "${val}" "${key}"
        ;;
    esac
  done <"${PID_FILE}"
  set +a
  rm -f "${PID_FILE}"
else
  if [[ "${PORTS_ONLY}" -eq 1 ]]; then
    echo "[mode] --ports-only"
  else
    echo "[pids] no pid file (will free ports only)"
  fi
fi

# Always free default ports (covers orphans / child processes)
kill_port "${CORE_PORT}"
kill_port "${VITE_PORT}"

# Extra: common Tauri process name (best-effort)
if is_windows; then
  taskkill //IM enpu-desktop.exe //F >/dev/null 2>&1 || true
else
  pkill -f 'enpu-desktop|target/debug/enpu' 2>/dev/null || true
fi

echo ""
echo "Stopped (core :${CORE_PORT}, vite :${VITE_PORT})."
echo "========================================"
