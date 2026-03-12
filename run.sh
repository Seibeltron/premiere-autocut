#!/usr/bin/env bash
# resolve-autocut launcher
# Auto-creates a Python venv with required dependencies on first run.
#
# Usage:
#   ./run.sh <video> <segments.json> [--timeline-name "Name"] [--no-refine]
#   ./run.sh --transcribe <video> [--no-cache]
#   ./run.sh --select <transcript.json> --topic "Focus topic" --duration <seconds> [-o segments.json]
#   ./run.sh --trim <segments.json> <transcript.json> [--context "note"] [--keep "phrase"] [-o trimmed.json]
set -e
cd "$(dirname "$0")"

PYTHON=python3.12

# Auto-create venv if missing
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    $PYTHON -m venv .venv
    .venv/bin/pip install --quiet --upgrade pip
    .venv/bin/pip install --quiet openai
fi

# Install openai if missing (e.g. venv existed from before)
if ! .venv/bin/python3 -c "import openai" 2>/dev/null; then
    echo "Installing openai..."
    .venv/bin/pip install --quiet openai
fi

# Route sub-commands
case "$1" in
    --transcribe)
        shift
        exec .venv/bin/python3 transcribe.py "$@"
        ;;
    --select)
        shift
        exec .venv/bin/python3 segment_select.py "$@"
        ;;
    --trim)
        shift
        exec .venv/bin/python3 trim_pass.py "$@"
        ;;
    *)
        # Default: build timeline
        exec .venv/bin/python3 build_timeline.py "$@"
        ;;
esac
