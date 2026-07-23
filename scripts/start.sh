#!/usr/bin/env bash
# EnPu one-click start: recognition core + Vite + desktop (Tauri)
# Usage:
#   ./scripts/start.sh
#   ENPU_UI=both ./scripts/start.sh     # default: core + vite + desktop window
#   ENPU_UI=vite ./scripts/start.sh     # core + browser UI only
#   ENPU_UI=desktop ./scripts/start.sh  # core + vite + desktop (alias of both)
#   ENPU_UI=tauri ./scripts/start.sh    # same as desktop
#   ENPU_UI=none ./scripts/start.sh     # core only
#   ENPU_RECOGNIZE_ENGINE=mock ./scripts/start.sh
#   ENPU_DESKTOP_MODE=exe ./scripts/start.sh   # prefer prebuilt enpu-desktop.exe
#   ENPU_DESKTOP_MODE=dev ./scripts/start.sh   # prefer `tauri dev` (hot reload)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${ROOT}/scripts/.run"
LOG_DIR="${RUN_DIR}/logs"
PID_FILE="${RUN_DIR}/pids.env"
CORE_DIR="${ROOT}/core"
DESKTOP_DIR="${ROOT}/desktop"

CORE_HOST="${ENPU_CORE_HOST:-127.0.0.1}"
CORE_PORT="${ENPU_CORE_PORT:-8765}"
VITE_PORT="${ENPU_VITE_PORT:-1420}"
# default: both (vite + desktop app) — what most people expect from one-click start
UI_MODE="${ENPU_UI:-both}"
ENGINE="${ENPU_RECOGNIZE_ENGINE:-paddleocr}"
# exe = launch prebuilt binary (fast); dev = tauri dev (hot reload); auto = exe if present else dev
DESKTOP_MODE="${ENPU_DESKTOP_MODE:-auto}"

mkdir -p "${LOG_DIR}"

is_windows() {
  case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW*|MSYS*|CYGWIN*) return 0 ;;
    *) return 1 ;;
  esac
}

to_win_path() {
  local p="$1"
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$p"
  else
    # /d/foo -> d:\foo
    echo "$p" | sed -e 's|^/\([a-zA-Z]\)/|\1:\\|' -e 's|/|\\|g'
  fi
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
    local tmp="${PID_FILE}.tmp"
    grep -v "^${key}=" "${PID_FILE}" >"${tmp}" || true
    mv "${tmp}" "${PID_FILE}"
  fi
  echo "${key}=${pid}" >>"${PID_FILE}"
}

process_running() {
  local name="$1"
  if is_windows; then
    tasklist 2>/dev/null | tr -d '\r' | grep -qi "${name}"
    return $?
  fi
  pgrep -f "${name}" >/dev/null 2>&1
}

start_core() {
  if port_in_use "${CORE_PORT}"; then
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

ensure_cargo_path() {
  if command -v rustc >/dev/null 2>&1; then
    return 0
  fi
  if [[ -x "${HOME}/.cargo/bin/rustc" ]]; then
    export PATH="${HOME}/.cargo/bin:${PATH}"
  fi
  # Windows user profile
  if is_windows && [[ -x "/c/Users/${USER}/.cargo/bin/rustc" ]]; then
    export PATH="/c/Users/${USER}/.cargo/bin:${PATH}"
  fi
}

start_vite() {
  if port_in_use "${VITE_PORT}"; then
    echo "[vite] already running on :${VITE_PORT}"
    return 0
  fi
  ensure_npm
  echo "[vite] starting http://localhost:${VITE_PORT}"
  (
    cd "${DESKTOP_DIR}"
    npm run dev -- --host localhost --port "${VITE_PORT}"
  ) >"${LOG_DIR}/vite.log" 2>&1 &
  local pid=$!
  write_pid VITE_PID "${pid}"
  echo "[vite] pid=${pid}  log=${LOG_DIR}/vite.log"
  wait_http "http://localhost:${VITE_PORT}/" "vite" 40 || true
}

write_tauri_override() {
  # Let external Vite own :1420; Tauri only opens the native window.
  cat >"${DESKTOP_DIR}/tauri.dev.override.json" <<EOF
{
  "build": {
    "beforeDevCommand": "",
    "devUrl": "http://localhost:${VITE_PORT}"
  }
}
EOF
}

desktop_exe_path() {
  local p
  for p in \
    "${DESKTOP_DIR}/src-tauri/target/debug/enpu-desktop.exe" \
    "${DESKTOP_DIR}/src-tauri/target/release/enpu-desktop.exe" \
    "${DESKTOP_DIR}/src-tauri/target/debug/enpu-desktop" \
    "${DESKTOP_DIR}/src-tauri/target/release/enpu-desktop"
  do
    if [[ -f "${p}" ]]; then
      echo "${p}"
      return 0
    fi
  done
  return 1
}

start_desktop_exe() {
  local exe
  if ! exe="$(desktop_exe_path)"; then
    return 1
  fi
  if process_running "enpu-desktop"; then
    echo "[desktop] enpu-desktop already running"
    return 0
  fi
  echo "[desktop] launching prebuilt binary: ${exe}"
  if is_windows; then
    local wexe
    wexe="$(to_win_path "${exe}")"
    # start detaches a GUI process on Windows
    cmd.exe //c start "" "${wexe}" >/dev/null 2>&1 || true
  else
    "${exe}" >"${LOG_DIR}/desktop.log" 2>&1 &
    write_pid DESKTOP_PID $!
  fi
  sleep 1
  if process_running "enpu-desktop"; then
    echo "[ok] desktop window process detected"
    return 0
  fi
  echo "[warn] desktop binary launched but process not detected yet"
  return 0
}

start_desktop_dev() {
  ensure_npm
  ensure_cargo_path
  write_tauri_override

  if process_running "enpu-desktop"; then
    echo "[desktop] enpu-desktop already running"
    return 0
  fi

  if ! command -v rustc >/dev/null 2>&1 && ! desktop_exe_path >/dev/null 2>&1; then
    echo "[desktop] rustc not found and no prebuilt enpu-desktop — skip desktop window"
    echo "         Install Rust (https://rustup.rs) + VS C++ tools, then: cd desktop && npm run tauri build -- --debug"
    return 0
  fi

  echo "[desktop] starting Tauri dev window (log: ${LOG_DIR}/tauri.log)..."
  if is_windows; then
    local bat="${RUN_DIR}/start_tauri.bat"
    local desk_win log_win
    desk_win="$(to_win_path "${DESKTOP_DIR}")"
    log_win="$(to_win_path "${LOG_DIR}/tauri.log")"
    local vsdev="C:\\Program Files (x86)\\Microsoft Visual Studio\\2022\\BuildTools\\Common7\\Tools\\VsDevCmd.bat"
    cat >"${bat}" <<EOF
@echo off
setlocal
if exist "${vsdev}" call "${vsdev}" -arch=x64 >nul 2>&1
set PATH=%USERPROFILE%\\.cargo\\bin;%PATH%
cd /d "${desk_win}"
echo [tauri] cwd=%CD% >> "${log_win}"
echo [tauri] starting... >> "${log_win}"
call npx tauri dev --config tauri.dev.override.json >> "${log_win}" 2>&1
echo [tauri] exited %ERRORLEVEL% >> "${log_win}"
EOF
    # Detach so start.sh can return; GUI app keeps running
    cmd.exe //c start "EnPu-Tauri" /MIN cmd.exe //c "$(to_win_path "${bat}")" >/dev/null 2>&1 || true
    echo "[desktop] tauri dev launched via VsDevCmd (may take a minute on first compile)"
  else
    (
      cd "${DESKTOP_DIR}"
      npm run tauri dev -- --config tauri.dev.override.json
    ) >"${LOG_DIR}/tauri.log" 2>&1 &
    write_pid TAURI_PID $!
    echo "[desktop] tauri pid=$!  log=${LOG_DIR}/tauri.log"
  fi

  # Wait briefly for window process
  local i
  for ((i = 1; i <= 30; i++)); do
    if process_running "enpu-desktop"; then
      echo "[ok] desktop window is up"
      return 0
    fi
    sleep 1
  done
  echo "[warn] desktop not detected yet — check ${LOG_DIR}/tauri.log"
  echo "       You can still use the browser UI: http://localhost:${VITE_PORT}"
}

start_desktop() {
  # Always keep Vite for live UI / Tauri devUrl
  start_vite

  local mode="${DESKTOP_MODE}"
  if [[ "${mode}" == "auto" ]]; then
    if desktop_exe_path >/dev/null 2>&1; then
      mode="exe"
    else
      mode="dev"
    fi
  fi

  case "${mode}" in
    exe)
      if start_desktop_exe; then
        return 0
      fi
      echo "[desktop] no prebuilt exe — falling back to tauri dev"
      start_desktop_dev
      ;;
    dev)
      start_desktop_dev
      ;;
    *)
      echo "[error] unknown ENPU_DESKTOP_MODE=${mode} (use auto|exe|dev)"
      exit 1
      ;;
  esac
}

# --- main ---
# normalize aliases
case "${UI_MODE}" in
  desktop|app|window) UI_MODE="both" ;;
  tauri) UI_MODE="both" ;; # tauri implies vite + window for stable devUrl
esac

echo "========================================"
echo " EnPu start"
echo " root:    ${ROOT}"
echo " ui:      ${UI_MODE}"
echo " desktop: ${DESKTOP_MODE}"
echo "========================================"

: >"${PID_FILE}"
start_core

case "${UI_MODE}" in
  vite)
    start_vite
    ;;
  both)
    start_desktop
    ;;
  none)
    echo "[ui] skipped (ENPU_UI=none)"
    ;;
  *)
    echo "[error] unknown ENPU_UI=${UI_MODE} (use both|vite|none)"
    echo "        tip: both = core + Vite + desktop window (default)"
    exit 1
    ;;
esac

echo ""
echo "Started."
echo "  Core:     http://${CORE_HOST}:${CORE_PORT}/health"
echo "  Docs:     http://${CORE_HOST}:${CORE_PORT}/docs"
if [[ "${UI_MODE}" == "vite" || "${UI_MODE}" == "both" ]]; then
  echo "  Web UI:   http://localhost:${VITE_PORT}"
fi
if [[ "${UI_MODE}" == "both" ]]; then
  echo "  Desktop:  EnPu window (enpu-desktop)"
fi
echo "  PIDs:     ${PID_FILE}"
echo "  Logs:     ${LOG_DIR}/"
echo "Stop with:  ./scripts/stop.sh"
echo "========================================"
