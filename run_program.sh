#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$ROOT_DIR/source_files"
PYTHON_EXE=""

find_python() {
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    PYTHON_EXE="$ROOT_DIR/.venv/bin/python"
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    PYTHON_EXE="$(command -v python3)"
    return 0
  fi

  return 1
}

if ! find_python; then
  echo "Python 3 not found."
  echo "Install Python 3 and run this script again."
  exit 1
fi

cd "$SOURCE_DIR"

if ! "$PYTHON_EXE" -c "import serial, minimalmodbus, PyQt5, pyqtgraph, numpy" >/dev/null 2>&1; then
  echo "Required Python packages are missing for:"
  echo "$PYTHON_EXE"
  echo "Run \"$ROOT_DIR/install_requirements.sh\" first."
  exit 1
fi

exec "$PYTHON_EXE" pps_GUI_program.py
