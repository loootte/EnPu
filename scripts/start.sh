#!/usr/bin/env bash
# EnPu one-click start: recognition core + Vite + desktop (Tauri)
#
# - Background services run WITHOUT console windows
# - Closing the desktop app auto-stops core + UI
#
# Usage:
#   ./scripts/start.sh
#   ENPU_UI=vite|both|none ./scripts/start.sh
#   ENPU_DESKTOP_MODE=auto|exe|dev ./scripts/start.sh
#   ENPU_RECOGNIZE_ENGINE=mock|paddleocr ./scripts/start.sh
#   ENPU_AUTO_STOP=0 ./scripts/start.sh
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
UI_MODE="${ENPU_UI:-both}"
ENGINE="${ENPU_RECOGNIZE_ENGINE:-paddleocr}"
DESKTOP_MODE="${ENPU_DESKTOP_MODE:-auto}"
AUTO_STOP="${ENPU_AUTO_STOP:-1}"

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
    echo "$p" | sed -e 's|^/\([a-zA-Z]\)/|\1:\\|' -e 's|/|\\|g'
  fi
}

ps_quote() {
  local s="$1"
  s="${s//\'/\'\'}"
  printf "%s" "$s"
}

core_python() {
  if is_windows; then
    if [[ -f "${CORE_DIR}/.venv/Scripts/python.exe" ]]; then
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

# Start via hidden cmd.exe with shell redirection (avoids PowerShell file-lock hangs).
# Args: workdir(win) log(win) command_line(for cmd /c)
win_start_hidden_cmd() {
  local workdir_win="$1"
  local log_win="$2"
  local cmdline="$3"
  local ps
  ps=$(
    cat <<EOF
\$wd = '$(ps_quote "${workdir_win}")'
\$log = '$(ps_quote "${log_win}")'
\$inner = '$(ps_quote "${cmdline}")'
# /c runs then exits; WindowStyle Hidden = no console UI
\$p = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', \$inner) -WorkingDirectory \$wd -WindowStyle Hidden -PassThru
Write-Output \$p.Id
EOF
  )
  powershell.exe -NoProfile -WindowStyle Hidden -Command "${ps}" 2>/dev/null | tr -d '\r' | tail -n 1
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
  echo "[core] starting uvicorn (${ENGINE}) — no console"
  local log="${LOG_DIR}/core.log"
  : >"${log}" || true

  local pid
  if is_windows; then
    local w_py w_core w_log
    w_py="$(to_win_path "${py}")"
    w_core="$(to_win_path "${CORE_DIR}")"
    w_log="$(to_win_path "${log}")"
    # cmd redirection is fine under Hidden window
    local cmd
    cmd="set ENPU_RECOGNIZE_ENGINE=${ENGINE}&& \"${w_py}\" -m uvicorn app.main:app --host ${CORE_HOST} --port ${CORE_PORT} >> \"${w_log}\" 2>&1"
    pid="$(win_start_hidden_cmd "${w_core}" "${w_log}" "${cmd}")"
  else
    pid="$(
      cd "${CORE_DIR}"
      export ENPU_RECOGNIZE_ENGINE="${ENGINE}"
      nohup "${py}" -m uvicorn app.main:app --host "${CORE_HOST}" --port "${CORE_PORT}" \
        >>"${log}" 2>&1 &
      echo $!
    )"
  fi

  if [[ -z "${pid:-}" || ! "${pid}" =~ ^[0-9]+$ ]]; then
    echo "[error] failed to start core (see ${log})"
    exit 1
  fi
  write_pid CORE_PID "${pid}"
  echo "[core] pid=${pid}  log=${log}"
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
}

start_vite() {
  if port_in_use "${VITE_PORT}"; then
    echo "[vite] already running on :${VITE_PORT}"
    return 0
  fi
  ensure_npm
  echo "[vite] starting http://localhost:${VITE_PORT} — no console"
  local log="${LOG_DIR}/vite.log"
  : >"${log}" || true

  local pid
  if is_windows; then
    local w_desk w_log
    w_desk="$(to_win_path "${DESKTOP_DIR}")"
    w_log="$(to_win_path "${log}")"
    # Use npm.cmd via cmd (hidden). Avoid PowerShell exclusive log locks.
    local cmd
    cmd="npm run dev -- --host localhost --port ${VITE_PORT} >> \"${w_log}\" 2>&1"
    pid="$(win_start_hidden_cmd "${w_desk}" "${w_log}" "${cmd}")"
  else
    pid="$(
      cd "${DESKTOP_DIR}"
      nohup npm run dev -- --host localhost --port "${VITE_PORT}" \
        >>"${log}" 2>&1 &
      echo $!
    )"
  fi

  if [[ -z "${pid:-}" || ! "${pid}" =~ ^[0-9]+$ ]]; then
    echo "[error] failed to start vite (see ${log})"
    exit 1
  fi
  write_pid VITE_PID "${pid}"
  echo "[vite] pid=${pid}  log=${log}"
  wait_http "http://localhost:${VITE_PORT}/" "vite" 40 || true
}

write_tauri_override() {
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
    echo "[desktop] already running"
    return 0
  fi
  echo "[desktop] launching window (no console host)"
  if is_windows; then
    local wexe wdesk
    wexe="$(to_win_path "${exe}")"
    wdesk="$(to_win_path "${DESKTOP_DIR}")"
    local ps pid
    ps=$(
      cat <<EOF
\$p = Start-Process -FilePath '$(ps_quote "${wexe}")' -WorkingDirectory '$(ps_quote "${wdesk}")' -WindowStyle Normal -PassThru
Write-Output \$p.Id
EOF
    )
    pid="$(powershell.exe -NoProfile -WindowStyle Hidden -Command "${ps}" | tr -d '\r' | tail -n 1)"
    if [[ -n "${pid}" && "${pid}" =~ ^[0-9]+$ ]]; then
      write_pid DESKTOP_PID "${pid}"
      echo "[desktop] pid=${pid}"
    fi
  else
    nohup "${exe}" >>"${LOG_DIR}/desktop.log" 2>&1 &
    write_pid DESKTOP_PID $!
  fi
  sleep 1
  if process_running "enpu-desktop"; then
    echo "[ok] desktop window up"
    return 0
  fi
  echo "[warn] desktop process not detected yet"
  return 0
}

start_desktop_dev() {
  ensure_npm
  ensure_cargo_path
  write_tauri_override

  if process_running "enpu-desktop"; then
    echo "[desktop] already running"
    return 0
  fi
  if ! command -v rustc >/dev/null 2>&1 && ! desktop_exe_path >/dev/null 2>&1; then
    echo "[desktop] no rustc and no prebuilt exe — skip window"
    return 0
  fi

  echo "[desktop] starting tauri dev host — no console"
  local log="${LOG_DIR}/tauri.log"
  : >"${log}" || true

  if is_windows; then
    local w_desk w_log
    w_desk="$(to_win_path "${DESKTOP_DIR}")"
    w_log="$(to_win_path "${log}")"
    local vsdev="C:\\Program Files (x86)\\Microsoft Visual Studio\\2022\\BuildTools\\Common7\\Tools\\VsDevCmd.bat"
    local cmd
    if [[ -f "/c/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/Common7/Tools/VsDevCmd.bat" ]]; then
      cmd="call \"${vsdev}\" -arch=x64 >nul 2>&1 && set PATH=%USERPROFILE%\\.cargo\\bin;%PATH% && cd /d \"${w_desk}\" && npx tauri dev --config tauri.dev.override.json >> \"${w_log}\" 2>&1"
    else
      cmd="set PATH=%USERPROFILE%\\.cargo\\bin;%PATH% && cd /d \"${w_desk}\" && npx tauri dev --config tauri.dev.override.json >> \"${w_log}\" 2>&1"
    fi
    local pid
    pid="$(win_start_hidden_cmd "${w_desk}" "${w_log}" "${cmd}")"
    if [[ -n "${pid}" && "${pid}" =~ ^[0-9]+$ ]]; then
      write_pid TAURI_PID "${pid}"
      echo "[desktop] tauri host pid=${pid}  log=${log}"
    fi
  else
    local pid
    pid="$(
      cd "${DESKTOP_DIR}"
      nohup npm run tauri dev -- --config tauri.dev.override.json \
        >>"${log}" 2>&1 &
      echo $!
    )"
    write_pid TAURI_PID "${pid}"
    echo "[desktop] tauri pid=${pid}"
  fi

  local i
  for ((i = 1; i <= 45; i++)); do
    if process_running "enpu-desktop"; then
      echo "[ok] desktop window up"
      return 0
    fi
    sleep 1
  done
  echo "[warn] desktop not detected — see ${log}"
}

start_desktop() {
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
      if ! start_desktop_exe; then
        echo "[desktop] fallback to tauri dev"
        start_desktop_dev
      fi
      ;;
    dev) start_desktop_dev ;;
    *) echo "[error] ENPU_DESKTOP_MODE=${mode}"; exit 1 ;;
  esac
}

start_desktop_watcher() {
  if [[ "${AUTO_STOP}" != "1" ]]; then
    echo "[watch] auto-stop disabled (ENPU_AUTO_STOP=0)"
    return 0
  fi

  local i found=0
  for ((i = 1; i <= 60; i++)); do
    if process_running "enpu-desktop"; then
      found=1
      break
    fi
    sleep 1
  done
  if [[ "${found}" -ne 1 ]]; then
    echo "[watch] desktop never appeared — watcher not armed"
    return 0
  fi

  echo "[watch] armed: close desktop → stop core + UI"
  local wlog="${LOG_DIR}/watcher.log"
  : >"${wlog}" || true

  if is_windows; then
    local w_root w_log w_ps1
    w_root="$(to_win_path "${ROOT}")"
    w_log="$(to_win_path "${wlog}")"
    w_ps1="$(to_win_path "${ROOT}/scripts/desktop-watcher.ps1")"
    local ps pid
    ps=$(
      cat <<EOF
\$p = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
  '-NoProfile','-WindowStyle','Hidden','-ExecutionPolicy','Bypass',
  '-File','$(ps_quote "${w_ps1}")',
  '-RepoRoot','$(ps_quote "${w_root}")',
  '-LogPath','$(ps_quote "${w_log}")',
  '-CorePort','${CORE_PORT}',
  '-VitePort','${VITE_PORT}'
) -WindowStyle Hidden -PassThru
Write-Output \$p.Id
EOF
    )
    pid="$(powershell.exe -NoProfile -WindowStyle Hidden -Command "${ps}" | tr -d '\r' | tail -n 1)"
    if [[ -n "${pid}" && "${pid}" =~ ^[0-9]+$ ]]; then
      write_pid WATCHER_PID "${pid}"
      echo "[watch] pid=${pid}  log=${wlog}"
    else
      echo "[warn] failed to start watcher"
    fi
  else
    (
      for _ in $(seq 1 120); do
        pgrep -f 'enpu-desktop' >/dev/null 2>&1 && break
        sleep 1
      done
      if ! pgrep -f 'enpu-desktop' >/dev/null 2>&1; then
        echo "[watch] no desktop" >>"${wlog}"
        exit 0
      fi
      echo "[watch] waiting for exit" >>"${wlog}"
      while pgrep -f 'enpu-desktop' >/dev/null 2>&1; do sleep 2; done
      echo "[watch] desktop closed" >>"${wlog}"
      "${ROOT}/scripts/stop.sh" --from-watcher >>"${wlog}" 2>&1 || true
    ) >/dev/null 2>&1 &
    write_pid WATCHER_PID $!
    echo "[watch] pid=$!"
  fi
}

# --- main ---
case "${UI_MODE}" in
  desktop|app|window|tauri) UI_MODE="both" ;;
esac

echo "========================================"
echo " EnPu start"
echo " root:      ${ROOT}"
echo " ui:        ${UI_MODE}"
echo " desktop:   ${DESKTOP_MODE}"
echo " auto-stop: ${AUTO_STOP}"
echo "========================================"

: >"${PID_FILE}"
start_core

case "${UI_MODE}" in
  vite) start_vite ;;
  both)
    start_desktop
    start_desktop_watcher
    ;;
  none) echo "[ui] skipped" ;;
  *)
    echo "[error] ENPU_UI=${UI_MODE} (both|vite|none)"
    exit 1
    ;;
esac

echo ""
echo "Started."
echo "  • Background services: no console windows"
echo "  Core:     http://${CORE_HOST}:${CORE_PORT}/health"
echo "  Docs:     http://${CORE_HOST}:${CORE_PORT}/docs"
if [[ "${UI_MODE}" == "vite" || "${UI_MODE}" == "both" ]]; then
  echo "  Web UI:   http://localhost:${VITE_PORT}"
fi
if [[ "${UI_MODE}" == "both" ]]; then
  echo "  Desktop:  EnPu window"
  if [[ "${AUTO_STOP}" == "1" ]]; then
    echo "  Auto-stop: close desktop → core + UI stop"
  fi
fi
echo "  Logs:     ${LOG_DIR}/"
echo "Manual stop: ./scripts/stop.sh"
echo "========================================"
