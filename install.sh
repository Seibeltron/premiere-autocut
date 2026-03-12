#!/usr/bin/env bash
# install.sh — One-command setup for premiere-autocut
# Usage: bash install.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC}  $1"; }
err()  { echo -e "${RED}✗${NC} $1"; exit 1; }
step() { echo -e "\n${BOLD}$1${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CEP_DIR="$HOME/Library/Application Support/Adobe/CEP/extensions/MCPBridgeCEP"

echo -e "${BOLD}Premiere Autocut — Setup${NC}"
echo "────────────────────────────────────────"

# ── 1. Homebrew ───────────────────────────────────────────────────────────────
step "1/6  Checking Homebrew..."
if ! command -v brew &>/dev/null; then
  err "Homebrew not found. Install it first: https://brew.sh"
fi
ok "Homebrew found"

# ── 2. FFmpeg ─────────────────────────────────────────────────────────────────
step "2/6  Checking FFmpeg..."
if command -v ffmpeg &>/dev/null; then
  ok "FFmpeg already installed"
else
  echo "    Installing FFmpeg via Homebrew..."
  brew install ffmpeg
  ok "FFmpeg installed"
fi

# ── 3. Python 3.12 ───────────────────────────────────────────────────────────
step "3/6  Checking Python 3.12..."
if command -v python3.12 &>/dev/null; then
  ok "Python 3.12 already installed"
else
  echo "    Installing Python 3.12 via Homebrew..."
  brew install python@3.12
  ok "Python 3.12 installed"
fi

# ── 4. OpenAI API key ─────────────────────────────────────────────────────────
step "4/6  OpenAI API key..."
if [[ -n "$OPENAI_API_KEY" ]]; then
  ok "OPENAI_API_KEY already set"
else
  echo ""
  echo "    Get your key from: https://openai-proxy.shopify.io/dashboard"
  echo "    Click 'Generate Key', then paste it below."
  echo ""
  read -r -p "    Paste your API key: " api_key
  if [[ -z "$api_key" ]]; then
    err "No API key provided. Re-run install.sh after getting your key."
  fi
  echo "" >> ~/.zshrc
  echo "# Shopify OpenAI proxy (added by premiere-autocut)" >> ~/.zshrc
  echo "export OPENAI_API_KEY=\"$api_key\"" >> ~/.zshrc
  echo "export OPENAI_BASE_URL=\"https://proxy.shopify.ai/v1\"" >> ~/.zshrc
  export OPENAI_API_KEY="$api_key"
  export OPENAI_BASE_URL="https://proxy.shopify.ai/v1"
  ok "API key saved to ~/.zshrc"
fi

# ── 5. CEP extension + debug mode ────────────────────────────────────────────
step "5/6  Installing MCP Bridge (CEP) extension..."
mkdir -p "$CEP_DIR"
cp -r "$SCRIPT_DIR/cep-extension/." "$CEP_DIR/"
ok "Installed to: $CEP_DIR"

echo "    Enabling CEP debug mode..."
defaults write com.adobe.CSXS.10 PlayerDebugMode 1
defaults write com.adobe.CSXS.11 PlayerDebugMode 1
defaults write com.adobe.CSXS.12 PlayerDebugMode 1
ok "CEP debug mode enabled"

mkdir -p /tmp/premiere-mcp-bridge
ok "Bridge temp dir: /tmp/premiere-mcp-bridge"

# ── 6. Python venv ────────────────────────────────────────────────────────────
step "6/6  Setting up Python environment..."
cd "$SCRIPT_DIR"
if [[ ! -d ".venv" ]]; then
  python3.12 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet openai
ok "Python environment ready"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "────────────────────────────────────────"
echo -e "${GREEN}${BOLD}Setup complete!${NC}"
echo ""
echo "  Reload your shell:"
echo "    source ~/.zshrc"
echo ""
echo "  Then in Premiere Pro:"
echo "    1. Quit and relaunch Premiere Pro"
echo "    2. Open your project"
echo "    3. Window > Extensions > MCP Bridge (CEP)"
echo "    4. Set Temp Directory to: /tmp/premiere-mcp-bridge"
echo "    5. Click Save Configuration → Start Bridge"
echo ""
echo "  Then open VS Code:"
echo "    code $SCRIPT_DIR"
echo ""
echo "  Tell Claude:"
echo "    Autocut /path/to/your-video.mp4, target 3 minutes"
echo ""
