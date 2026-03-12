# 🎬 Premiere Autocut — Setup Guide

Hey! Here's how to get the AI video editor running. One terminal command and a few clicks in Premiere — that's it.

**Before you start:**
- Adobe Premiere Pro installed
- Claude Code VS Code extension installed
- Homebrew installed (https://brew.sh — if you don't have it)

---

## Step 1 — Get your API key

Go to **https://openai-proxy.shopify.io/dashboard** → click **Generate Key** → copy it (you'll paste it in the next step)

---

## Step 2 — Open Terminal and run:

```
git clone https://github.com/Seibeltron/premiere-autocut.git ~/premiere-autocut
bash ~/premiere-autocut/install.sh
```

The script will ask for your API key, then handle everything else automatically (FFmpeg, Python 3.12, CEP extension install, debug mode).

---

## Step 3 — Start the bridge in Premiere Pro

1. Quit and **relaunch Premiere Pro** (required after installing the extension)
2. Open your project
3. Go to **Window > Extensions > MCP Bridge (CEP)**
4. Set **Temp Directory** to: `/tmp/premiere-mcp-bridge`
5. Click **Save Configuration** → **Start Bridge**

> You'll need to do steps 3–5 each time you start a new Premiere session.

---

## Step 4 — Open VS Code and start cutting

```
source ~/.zshrc
code ~/premiere-autocut
```

Open the Claude panel and type something like:

```
Autocut /path/to/my-video.mp4, target 3 minutes
```

Drag your video into the chat to get the path. Claude will transcribe it, show you a topic menu, and ask which parts you want — then build the timeline in Premiere automatically.

---

Ping me if anything goes sideways!
