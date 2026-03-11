# Resolve Autocut

AI-powered DaVinci Resolve timeline builder. Tell Claude what video to cut and what topics to focus on — it transcribes the video, selects the best segments, and builds a ready-to-edit timeline in Resolve.

---

## What It Does

1. Transcribes your video with word-accurate timestamps
2. Claude reads the transcript, summarizes it, and identifies topic categories
3. You pick which topics to include and set a target duration
4. Claude scores and selects the best segments
5. A DaVinci Resolve timeline is built automatically — each segment becomes an editable clip

The source video is **never modified**. All cuts are fully adjustable in Resolve's Edit page.

---

## Requirements

- **DaVinci Resolve** must be running with a project open
- **FFmpeg** installed (`brew install ffmpeg`)
- **Python 3.12+** installed (`brew install python@3.12`)
- The `.venv` is created automatically on first run (no manual setup needed)

---

## How to Use

### Step 1 — Open Claude Code in VS Code

Open the `resolve-autocut` folder in VS Code, then open the Claude panel (the `>_` icon in the sidebar or press `Cmd+Shift+P` → "Claude").

### Step 2 — Tell Claude to autocut your video

Type something like:

```
Autocut /path/to/my-video.mp4, focus on the product demo and Q&A sections, target 2 minutes
```

Or drag your video file into the chat to get its path.

Claude will:
- Run the transcription (this takes a minute or two depending on video length)
- Show you a summary and list of topic categories it found
- Ask which topics you want to keep

### Step 3 — Review and confirm

Claude will show you the selected segments with start/end times and text previews. You can ask it to add, remove, or swap segments before building.

### Step 4 — Timeline appears in Resolve

Once confirmed, Claude runs `build_timeline.py` and the timeline appears in DaVinci Resolve automatically. Switch to the Edit page to review your cut.

---

## Running Manually (Command Line)

If you prefer to run the scripts directly from the VS Code terminal (`Ctrl+`` ` `` or Terminal → New Terminal):

```bash
cd ~/resolve-autocut

# Transcribe a video
.venv/bin/python3 transcribe.py /path/to/video.mp4 > /tmp/transcript.json

# Build a timeline from a segments JSON file
./run.sh /path/to/video.mp4 /tmp/segments.json

# Custom timeline name
./run.sh /path/to/video.mp4 /tmp/segments.json --timeline-name "Q3 Highlights"

# Skip the word-boundary refinement pass (faster, slightly less precise)
./run.sh /path/to/video.mp4 /tmp/segments.json --no-refine
```

---

## What the Refinement Pass Does

After selecting segments, the script checks each clip's cut point against the source audio. If a word is being cut off mid-syllable, it automatically extends the clip to the next natural pause in speech. You'll see a report like:

```
Clip 1: ✓ OK (slack 320ms, ends: "all the headlines.")
Clip 3: ⚠ extended +2836ms (phrase: "geographies at an insane pace." → pause)
Clip 6: ⚠ extended +3670ms (phrase: "world's biggest brands in a decade or less." → pause)
```

---

## Troubleshooting

**"Could not connect to DaVinci Resolve"**
→ Make sure Resolve is open and a project is loaded before running the script.

**"No project open in DaVinci Resolve"**
→ Open or create a project in Resolve (File → New Project), then re-run.

**Timeline frame rate is wrong**
→ The script auto-detects the source video's frame rate and sets the project fps before creating the timeline. This only works on a fresh project with no existing timelines. If you have other timelines in the project, create a new project in Resolve first.

**Refinement skipped ("faster-whisper not available")**
→ Run using `.venv/bin/python3` or `./run.sh` rather than your system Python. The venv has faster-whisper installed; system Python does not.

**Audio missing from clips**
→ Do not pass `mediaType` in the clip dict — this is a known Resolve API quirk where `mediaType: 1` means video-only (not video+audio as documented). The scripts are already set up correctly.
