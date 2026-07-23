#!/usr/bin/env bash
# Build EnPu core sidecar with PyInstaller (issue #8 PoC).
# Output: core/dist/enpu-core(.exe)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE="${ROOT}/core"

is_windows() {
  case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW*|MSYS*|CYGWIN*) return 0 ;;
    *) return 1 ;;
  esac
}

echo "========================================"
echo " EnPu core sidecar build (PyInstaller)"
echo "========================================"

cd "${CORE}"

if is_windows; then
  PY="${CORE}/.venv/Scripts/python.exe"
  PIP="${CORE}/.venv/Scripts/pip.exe"
else
  PY="${CORE}/.venv/bin/python"
  PIP="${CORE}/.venv/bin/pip"
fi

if [[ ! -x "${PY}" && ! -f "${PY}" ]]; then
  echo "[build] creating venv..."
  python -m venv .venv
fi

echo "[build] installing runtime + pyinstaller..."
"${PIP}" install -q -U pip
# Lightweight set for mock sidecar (opencv still used by preprocess)
"${PIP}" install -q -r requirements.txt
"${PIP}" install -q "pyinstaller>=6.0,<7"

echo "[build] running PyInstaller (enpu-core.spec)..."
"${PY}" -m PyInstaller --noconfirm --clean enpu-core.spec

OUT=""
if [[ -f "${CORE}/dist/enpu-core.exe" ]]; then
  OUT="${CORE}/dist/enpu-core.exe"
elif [[ -f "${CORE}/dist/enpu-core" ]]; then
  OUT="${CORE}/dist/enpu-core"
fi

if [[ -z "${OUT}" ]]; then
  echo "[error] build finished but binary not found under core/dist/"
  exit 1
fi

echo ""
echo "[ok] sidecar built: ${OUT}"
if is_windows; then
  # size in MB via powershell-ish
  ls -lh "${OUT}" || true
  powershell.exe -NoProfile -Command "(Get-Item -LiteralPath '$(cygpath -w "${OUT}" 2>/dev/null || echo "${OUT}")').Length / 1MB" 2>/dev/null || true
else
  ls -lh "${OUT}"
fi

echo ""
echo "Smoke test (mock engine):"
echo "  ${OUT} --engine mock --host 127.0.0.1 --port 8765"
echo "Then: curl http://127.0.0.1:8765/health"
echo "========================================"
