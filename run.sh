#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3.12 -m venv .venv
    .venv/bin/pip install faster-whisper
fi

.venv/bin/python3 build_timeline.py "$@"
