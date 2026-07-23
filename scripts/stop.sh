#!/usr/bin/env bash
# EnPu one-click stop: kill processes started by start.sh (and free common ports)
# Usage:
#   ./scripts/stop.sh
#   ./scripts/stop.sh --ports-only
#   ./scripts/stop.sh --from-watcher   # called when desktop closes (same as full stop)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${ROOT}/scripts/.run"
PID_FILE="${RUN_DIR}/pids.env"
LOG_DIR="${RUN_DIR}/logs"
CORE_PORT="${ENPU_CORE_PORT:-8765}"
VITE_PORT="${ENPU_VITE_PORT:-1420}"
PORTS_ONLY=0
FROM_WATCHER=0

for arg in "$@"; do
  case "${arg}" in
    --ports-only) PORTS_ONLY=1 ;;
    --from-watcher) FROM_WATCHER=1 ;;
    -h|--help)
      echo "Usage: $0 [--ports-only] [--from-watcher]"
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
  # Never kill ourselves
  if [[ "${pid}" == "$$" || "${pid}" == "${PPID}" ]]; then
    return 0
  fi

  local alive=0
  if kill -0 "${pid}" 2>/dev/null; then
    alive=1
  elif is_windows && tasklist //FI "PID eq ${pid}" 2>/dev/null | grep -q "${pid}"; then
    alive=1
  fi
  if [[ "${alive}" -eq 0 ]]; then
    echo "[skip] ${label}=${pid} not running"
    return 0
  fi

  echo "[stop] ${label}=${pid}"
  if is_windows; then
    taskkill //PID "${pid}" //T //F >/dev/null 2>&1 || true
    sleep 0.2
    taskkill //PID "${pid}" //T //F >/dev/null 2>&1 || true
  else
    kill -TERM "${pid}" 2>/dev/null || true
    sleep 0.3
    kill -KILL "${pid}" 2>/dev/null || true
    pkill -P "${pid}" 2>/dev/null || true
  fi
}

pids_on_port() {
  local port="$1"
  if is_windows; then
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

mkdir -p "${LOG_DIR}"
if [[ "${FROM_WATCHER}" -eq 1 ]]; then
  echo "[stop] triggered by desktop close watcher" | tee -a "${LOG_DIR}/watcher.log"
fi

echo "========================================"
echo " EnPu stop"
echo "========================================"

WATCHER_TO_KILL=""

if [[ "${PORTS_ONLY}" -eq 0 && -f "${PID_FILE}" ]]; then
  echo "[pids] reading ${PID_FILE}"
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ -z "${line}" || "${line}" =~ ^# ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    case "${key}" in
      CORE_PID|VITE_PID|TAURI_PID|DESKTOP_PID)
        kill_pid "${val}" "${key}"
        ;;
      WATCHER_PID)
        # Kill watcher last (and not if we are the watcher tree awkwardly)
        WATCHER_TO_KILL="${val}"
        ;;
    esac
  done <"${PID_FILE}"
  rm -f "${PID_FILE}"
else
  if [[ "${PORTS_ONLY}" -eq 1 ]]; then
    echo "[mode] --ports-only"
  else
    echo "[pids] no pid file"
  fi
fi

kill_port "${CORE_PORT}"
kill_port "${VITE_PORT}"

if is_windows; then
  taskkill //IM enpu-desktop.exe //F >/dev/null 2>&1 || true
else
  pkill -f 'enpu-desktop|target/debug/enpu' 2>/dev/null || true
fi

# Watcher last
if [[ -n "${WATCHER_TO_KILL}" && "${FROM_WATCHER}" -eq 0 ]]; then
  kill_pid "${WATCHER_TO_KILL}" "WATCHER_PID"
fi

# Cleanup helper files
rm -f "${RUN_DIR}/start_tauri.bat" "${RUN_DIR}/desktop-watcher.ps1" 2>/dev/null || true

echo ""
echo "Stopped (core :${CORE_PORT}, vite :${VITE_PORT}, desktop)."
echo "========================================"
