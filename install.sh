#!/usr/bin/env bash
# premiere-autocut installer
# Installs the CEP bridge extension into Premiere Pro and enables debug mode.
set -e

CEP_DIR="$HOME/Library/Application Support/Adobe/CEP/extensions/MCPBridgeCEP"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "=== premiere-autocut installer ==="
echo ""

# ---- 1. Check dependencies ----
echo "Checking dependencies..."

if ! command -v python3.12 &>/dev/null; then
  echo "  ✗ Python 3.12 not found. Install with: brew install python@3.12"
  MISSING=1
else
  echo "  ✓ Python 3.12"
fi

if ! command -v ffmpeg &>/dev/null; then
  echo "  ✗ FFmpeg not found. Install with: brew install ffmpeg"
  MISSING=1
else
  echo "  ✓ FFmpeg"
fi

if [ -z "$OPENAI_API_KEY" ]; then
  echo "  ✗ OPENAI_API_KEY not set. Add to your ~/.zshrc: export OPENAI_API_KEY=sk-..."
  MISSING=1
else
  echo "  ✓ OPENAI_API_KEY"
fi

if [ "${MISSING}" = "1" ]; then
  echo ""
  echo "Fix the above issues and re-run install.sh."
  exit 1
fi

echo ""

# ---- 2. Install CEP extension ----
echo "Installing MCP Bridge (CEP) extension..."
mkdir -p "$CEP_DIR"
cp -r "$SCRIPT_DIR/cep-extension/." "$CEP_DIR/"
echo "  ✓ Installed to: $CEP_DIR"

# ---- 3. Enable CEP debug mode (required for unsigned extensions) ----
echo "Enabling CEP debug mode..."
defaults write com.adobe.CSXS.10 PlayerDebugMode 1
defaults write com.adobe.CSXS.11 PlayerDebugMode 1
defaults write com.adobe.CSXS.12 PlayerDebugMode 1
echo "  ✓ CEP debug mode enabled"

# ---- 4. Create temp directory ----
mkdir -p /tmp/premiere-mcp-bridge
echo "  ✓ Bridge temp dir: /tmp/premiere-mcp-bridge"

# ---- 5. Bootstrap Python venv ----
echo ""
echo "Setting up Python environment..."
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
  python3.12 -m venv "$SCRIPT_DIR/.venv"
  "$SCRIPT_DIR/.venv/bin/pip" install --quiet --upgrade pip
fi
"$SCRIPT_DIR/.venv/bin/pip" install --quiet openai
echo "  ✓ Python venv ready"

echo ""
echo "=== Installation complete ==="
echo ""
echo "Next steps:"
echo "  1. Quit and relaunch Adobe Premiere Pro"
echo "  2. Open your project"
echo "  3. Go to Window > Extensions > MCP Bridge (CEP)"
echo "  4. Set Temp Directory to: /tmp/premiere-mcp-bridge"
echo "  5. Click Save Configuration, then Start Bridge"
echo ""
echo "Then tell Claude: autocut /path/to/video.mp4 3 minutes"
echo ""
