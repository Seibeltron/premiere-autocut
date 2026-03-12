# Premiere Autocut

AI-powered Adobe Premiere Pro timeline builder. Tell Claude what video to cut and what topics to focus on — it transcribes the video, selects the best segments, and builds a ready-to-edit timeline in Premiere.

---

## What It Does

1. Transcribes your video with word-accurate timestamps
2. Claude reads the transcript, summarizes it, and identifies topic categories
3. You pick which topics to include and set a target duration
4. Claude scores and selects the best segments
5. A Premiere Pro sequence is built automatically — each segment becomes an editable clip

The source video is **never modified**. All cuts are fully adjustable in Premiere's timeline.

---

## Requirements

- **Adobe Premiere Pro** must be running with a project open
- **MCP Bridge (CEP) panel** must be open and started (Window > Extensions > MCP Bridge (CEP))
  - Set Temp Directory to `/tmp/premiere-mcp-bridge`
  - Click **Save Configuration** → **Start Bridge**
- **FFmpeg** installed (`brew install ffmpeg`)
- **Python 3.12+** installed (`brew install python@3.12`)
- The `.venv` is created automatically on first run (no manual setup needed)

---

## How to Use

### Step 1 — Prepare Premiere Pro

1. Open Premiere Pro with a project
2. Open **Window > Extensions > MCP Bridge (CEP)**
3. Set temp dir to `/tmp/premiere-mcp-bridge`, click **Save Configuration** then **Start Bridge**

### Step 2 — Open Claude Code in VS Code

Open the `premiere-autocut` folder in VS Code, then open the Claude panel.

### Step 3 — Tell Claude to autocut your video

Type something like:

```
Autocut /path/to/my-video.mp4, focus on the product demo and Q&A sections, target 2 minutes
```

Claude will:
- Run the transcription (takes a minute or two depending on video length)
- Show you a summary and list of topic categories it found
- Ask which topics you want to keep

### Step 4 — Review and confirm

Claude will show you the selected segments with start/end times and text previews. You can ask it to add, remove, or swap segments before building.

### Step 5 — Timeline appears in Premiere

Once confirmed, Claude runs `build_timeline.py` and the sequence appears in Premiere Pro. Open the Timeline panel to review your cut.

---

## Running Manually (Command Line)

```bash
cd ~/premiere-autocut

# Transcribe a video
./run.sh --transcribe /path/to/video.mp4 > /tmp/transcript.json

# Select segments with GPT-4o
./run.sh --select /tmp/transcript.json --topic "product demo" --duration 120 -o /tmp/segments.json

# (Optional) Tighten in/out points with GPT-4o trim pass
./run.sh --trim /tmp/segments.json /tmp/transcript.json -o /tmp/trimmed.json

# Build the Premiere timeline
./run.sh /path/to/video.mp4 /tmp/segments.json

# Custom sequence name
./run.sh /path/to/video.mp4 /tmp/segments.json --timeline-name "Q3 Highlights"

# Skip the word-boundary refinement pass (faster)
./run.sh /path/to/video.mp4 /tmp/segments.json --no-refine
```

---

## What the Refinement Pass Does

After selecting segments, the script checks each clip's cut point against the source audio. If a word is being cut off mid-syllable, it automatically extends the clip to the next natural pause in speech:

```
Clip 1: ✓ OK (slack 320ms, ends: "all the headlines.")
Clip 3: ⚠ extended +2836ms (phrase: "geographies at an insane pace." → pause)
Clip 6: ⚠ extended +3670ms (phrase: "world's biggest brands in a decade or less." → pause)
```

---

## Troubleshooting

**Bridge times out ("No response from Premiere Pro")**
→ Check that the MCP Bridge CEP panel is open in Premiere and the bridge is started. The temp directory must be `/tmp/premiere-mcp-bridge`.

**"Could not find imported item in project"**
→ Ensure the video file path is absolute and the file is accessible. Try importing it manually into Premiere first.

**Sequence not appearing**
→ After the script completes, click in the Premiere timeline panel to refresh, or look in the Project panel for the new sequence.

**Refinement skipped ("OpenAI not available")**
→ Ensure `OPENAI_API_KEY` is set in your environment, or run with `--no-refine`.
