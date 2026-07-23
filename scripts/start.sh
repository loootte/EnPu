#!/usr/bin/env bash
# EnPu one-click start: recognition core + frontend UI
# Usage:
#   ./scripts/start.sh
#   ENPU_UI=vite ./scripts/start.sh      # default: Vite only (http://localhost:1420)
#   ENPU_UI=tauri ./scripts/start.sh     # Tauri window (needs Rust/MSVC on Windows)
#   ENPU_UI=both ./scripts/start.sh
#   ENPU_RECOGNIZE_ENGINE=mock ./scripts/start.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${ROOT}/scripts/.run"
LOG_DIR="${RUN_DIR}/logs"
PID_FILE="${RUN_DIR}/pids.env"
CORE_DIR="${ROOT}/core"
DESKTOP_DIR="${ROOT}/desktop"

CORE_HOST="${ENPU_CORE_HOST:-127.0.0.1}"
CORE_PORT="${ENPU_CORE_PORT:-8765}"
UI_MODE="${ENPU_UI:-vite}"   # vite | tauri | both | none
ENGINE="${ENPU_RECOGNIZE_ENGINE:-paddleocr}"

mkdir -p "${LOG_DIR}"

is_windows() {
  case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW*|MSYS*|CYGWIN*) return 0 ;;
    *) return 1 ;;
  esac
}

core_python() {
  if is_windows; then
    if [[ -x "${CORE_DIR}/.venv/Scripts/python.exe" ]]; then
      echo "${CORE_DIR}/.venv/Scripts/python.exe"
      return
    fi
  else
    if [[ -x "${CORE_DIR}/.venv/bin/python" ]]; then
      echo "${CORE_DIR}/.venv/bin/python"
      return
    fi
  fi
  return 1
}

ensure_core_venv() {
  if core_python >/dev/null 2>&1; then
    return 0
  fi
  echo "[core] creating venv..."
  (cd "${CORE_DIR}" && python -m venv .venv)
  local py
  py="$(core_python)"
  echo "[core] pip install -r requirements.txt (may take a while)..."
  "${py}" -m pip install -q -U pip
  "${py}" -m pip install -q -r "${CORE_DIR}/requirements.txt"
}

port_in_use() {
  local port="$1"
  if is_windows; then
    netstat -ano 2>/dev/null | tr -d '\r' | grep -E "[:.]${port}[[:space:]].*LISTENING" >/dev/null 2>&1
    return $?
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | grep -q ":${port} "
    return $?
  fi
  return 1
}

wait_http() {
  local url="$1"
  local name="$2"
  local retries="${3:-40}"
  local i
  for ((i = 1; i <= retries; i++)); do
    if curl -fsS --max-time 1 "${url}" >/dev/null 2>&1; then
      echo "[ok] ${name} ready: ${url}"
      return 0
    fi
    sleep 0.5
  done
  echo "[warn] ${name} not ready yet: ${url}"
  return 1
}

write_pid() {
  local key="$1"
  local pid="$2"
  touch "${PID_FILE}"
  if grep -q "^${key}=" "${PID_FILE}" 2>/dev/null; then
    # portable sed in-place for git-bash/linux
    local tmp="${PID_FILE}.tmp"
    grep -v "^${key}=" "${PID_FILE}" >"${tmp}" || true
    mv "${tmp}" "${PID_FILE}"
  fi
  echo "${key}=${pid}" >>"${PID_FILE}"
}

start_core() {
  if port_in_use "${CORE_PORT}"; then
    # If health already ok, reuse
    if curl -fsS --max-time 1 "http://${CORE_HOST}:${CORE_PORT}/health" >/dev/null 2>&1; then
      echo "[core] already running on :${CORE_PORT}"
      return 0
    fi
    echo "[core] port ${CORE_PORT} busy but /health failed — stop first: ./scripts/stop.sh"
    exit 1
  fi

  ensure_core_venv
  local py
  py="$(core_python)"
  echo "[core] starting uvicorn (${ENGINE}) on http://${CORE_HOST}:${CORE_PORT}"
  (
    cd "${CORE_DIR}"
    export ENPU_RECOGNIZE_ENGINE="${ENGINE}"
    # no --reload in daemon mode (more stable for PID tracking)
    "${py}" -m uvicorn app.main:app --host "${CORE_HOST}" --port "${CORE_PORT}"
  ) >"${LOG_DIR}/core.log" 2>&1 &
  local pid=$!
  write_pid CORE_PID "${pid}"
  echo "[core] pid=${pid}  log=${LOG_DIR}/core.log"
  wait_http "http://${CORE_HOST}:${CORE_PORT}/health" "core" 60 || true
}

ensure_npm() {
  if [[ ! -d "${DESKTOP_DIR}/node_modules" ]]; then
    echo "[ui] npm install..."
    (cd "${DESKTOP_DIR}" && npm install)
  fi
}

start_vite() {
  if port_in_use 1420; then
    echo "[vite] already running on :1420"
    return 0
  fi
  ensure_npm
  echo "[vite] starting http://localhost:1420"
  (
    cd "${DESKTOP_DIR}"
    npm run dev -- --host localhost --port 1420
  ) >"${LOG_DIR}/vite.log" 2>&1 &
  local pid=$!
  write_pid VITE_PID "${pid}"
  echo "[vite] pid=${pid}  log=${LOG_DIR}/vite.log"
  wait_http "http://localhost:1420/" "vite" 40 || true
}

start_tauri() {
  ensure_npm
  if ! command -v rustc >/dev/null 2>&1; then
    # common rustup path
    if [[ -x "${HOME}/.cargo/bin/rustc" ]]; then
      export PATH="${HOME}/.cargo/bin:${PATH}"
    fi
  fi
  if ! command -v rustc >/dev/null 2>&1; then
    echo "[tauri] rustc not found — skip Tauri (install rustup, or use ENPU_UI=vite)"
    return 0
  fi
  echo "[tauri] starting (first build may take minutes)..."
  (
    cd "${DESKTOP_DIR}"
    # Prefer existing Vite if up; empty beforeDevCommand via env is not standard —
    # use normal tauri dev (starts its own vite unless already conflicting).
    npm run tauri dev
  ) >"${LOG_DIR}/tauri.log" 2>&1 &
  local pid=$!
  write_pid TAURI_PID "${pid}"
  echo "[tauri] pid=${pid}  log=${LOG_DIR}/tauri.log"
}

# --- main ---
echo "========================================"
echo " EnPu start"
echo " root: ${ROOT}"
echo " ui:   ${UI_MODE}"
echo "========================================"

: >"${PID_FILE}"
start_core

case "${UI_MODE}" in
  vite)
    start_vite
    ;;
  tauri)
    start_tauri
    ;;
  both)
    start_vite
    start_tauri
    ;;
  none)
    echo "[ui] skipped (ENPU_UI=none)"
    ;;
  *)
    echo "[error] unknown ENPU_UI=${UI_MODE} (use vite|tauri|both|none)"
    exit 1
    ;;
esac

echo ""
echo "Started."
echo "  Core:  http://${CORE_HOST}:${CORE_PORT}/health"
echo "  Docs:  http://${CORE_HOST}:${CORE_PORT}/docs"
if [[ "${UI_MODE}" == "vite" || "${UI_MODE}" == "both" ]]; then
  echo "  UI:    http://localhost:1420"
fi
echo "  PIDs:  ${PID_FILE}"
echo "  Logs:  ${LOG_DIR}/"
echo "Stop with:  ./scripts/stop.sh"
echo "========================================"
