#!/usr/bin/env python3
"""
build_timeline.py — Build a non-destructive Adobe Premiere Pro timeline from selected segments.

Each segment becomes a separate clip item on the timeline referencing the original source
file with in/out points. All cut points remain adjustable in Premiere's timeline.

Communicates with Premiere Pro via the MCP Bridge (CEP) file protocol.
Requires: Premiere Pro open, MCP Bridge panel open with bridge started at /tmp/premiere-mcp-bridge.

Usage:
    python build_timeline.py /path/to/video.mp4 /path/to/segments.json
    python build_timeline.py /path/to/video.mp4 /path/to/segments.json --timeline-name "My Cut"
    python build_timeline.py /path/to/video.mp4 /path/to/segments.json --no-refine
"""

import json
import os
import subprocess
import sys
import time
import uuid
from fractions import Fraction
from pathlib import Path


BRIDGE_DIR = os.environ.get("PREMIERE_TEMP_DIR", "/tmp/premiere-mcp-bridge")
BRIDGE_TIMEOUT = 60  # seconds to wait for Premiere to respond
TICKS_PER_SEC = 254016000000  # Premiere Pro internal time base


# ---------------------------------------------------------------------------
# Bridge communication
# ---------------------------------------------------------------------------

def execute_extendscript(script: str, timeout: int = BRIDGE_TIMEOUT) -> dict:
    """Write an ExtendScript command to the bridge dir and wait for the response."""
    Path(BRIDGE_DIR).mkdir(parents=True, exist_ok=True)
    cmd_id = str(uuid.uuid4())
    cmd_file = os.path.join(BRIDGE_DIR, f"command-{cmd_id}.json")
    resp_file = os.path.join(BRIDGE_DIR, f"response-{cmd_id}.json")

    # Helpers + IIFE wrapper (ExtendScript forbids top-level return)
    helpers = """
function __secondsToTicks(s) { return String(Math.round(s * 254016000000)); }
function __findSequenceByName(name) {
  for (var i = 0; i < app.project.sequences.numSequences; i++) {
    if (app.project.sequences[i].name === name) return app.project.sequences[i];
  }
  return null;
}
"""
    full_script = helpers + "(function(){\n" + script + "\n})();"

    with open(cmd_file, "w") as f:
        json.dump({"id": cmd_id, "script": full_script,
                   "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")}, f)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(resp_file):
            try:
                with open(resp_file) as f:
                    result = json.load(f)
                os.unlink(resp_file)
                return result
            except (json.JSONDecodeError, OSError):
                pass
        time.sleep(0.2)

    try:
        os.unlink(cmd_file)
    except OSError:
        pass
    raise TimeoutError(
        f"No response from Premiere Pro after {timeout}s.\n"
        f"Make sure:\n"
        f"  1. Premiere Pro is open\n"
        f"  2. Window > Extensions > MCP Bridge (CEP) panel is open\n"
        f"  3. Temp directory is set to {BRIDGE_DIR}\n"
        f"  4. Bridge is started (click 'Start Bridge')"
    )


# ---------------------------------------------------------------------------
# FPS detection
# ---------------------------------------------------------------------------

def get_source_fps(video_path: str) -> float:
    """Read the source file's native frame rate using ffprobe."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", video_path],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(out.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                r = stream.get("r_frame_rate", "")
                if "/" in r:
                    num, den = r.split("/")
                    return float(Fraction(int(num), int(den)))
    except Exception as e:
        print(f"Warning: ffprobe failed ({e}), defaulting to 29.97fps", file=sys.stderr)
    return 29.97


# ---------------------------------------------------------------------------
# OpenAI Whisper end-time refinement
# ---------------------------------------------------------------------------

def _get_openai_client():
    """Return an OpenAI client using env vars, or None if unavailable."""
    try:
        from openai import OpenAI
    except ImportError:
        return None
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    base_url = os.environ.get("OPENAI_BASE_URL", "https://proxy.shopify.ai/v1")
    return OpenAI(api_key=api_key, base_url=base_url)


def _refine_one_clip(args: tuple) -> tuple:
    """Transcribe the window around a single clip's cut point and extend if a word is cut off.
    Designed to run in a thread pool.

    Returns: (index, updated_entry_dict, status_message)
    """
    i, entry, next_start_s, video_path, fps, min_slack_s, target_slack_s, client = args

    cut_s = entry["end"]
    win_start = max(0.0, cut_s - 1.0)
    win_end = cut_s + 4.0

    import tempfile
    tmp_mp3 = None
    words = []
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_mp3 = f.name
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{win_start:.6f}", "-to", f"{win_end:.6f}",
             "-i", video_path, "-vn", "-acodec", "libmp3lame", "-ab", "64k",
             "-ac", "1", "-ar", "16000", tmp_mp3],
            capture_output=True, timeout=30,
        )
        with open(tmp_mp3, "rb") as f:
            response = client.audio.transcriptions.create(
                model="whisper-1", file=f,
                response_format="verbose_json",
                timestamp_granularities=["word"],
                language="en",
            )
        for w in getattr(response, "words", None) or []:
            words.append({
                "word": w.word,
                "start": float(w.start) + win_start,
                "end": float(w.end) + win_start,
            })
    except Exception as e:
        return i, dict(entry), f"⚠ error: {e}"
    finally:
        if tmp_mp3:
            try:
                os.unlink(tmp_mp3)
            except OSError:
                pass

    straddling = [w for w in words if w["start"] < cut_s < w["end"]]
    close_after = [w for w in words if cut_s <= w["end"] <= cut_s + 0.4]
    before = [w for w in words if w["end"] <= cut_s]
    slack = (cut_s - before[-1]["end"]) if before else 999.0

    needs_extend = bool(straddling or close_after) or slack < min_slack_s
    entry = dict(entry)

    if needs_extend:
        if straddling or close_after:
            after_cut = sorted(
                [w for w in words if w["start"] >= cut_s - 0.1],
                key=lambda w: w["start"],
            )
            phrase_end_s = None
            for j in range(len(after_cut) - 1):
                if after_cut[j]["end"] > cut_s and after_cut[j + 1]["start"] - after_cut[j]["end"] > 0.3:
                    phrase_end_s = after_cut[j]["end"]
                    break
            if phrase_end_s is None and after_cut:
                phrase_end_s = max(w["end"] for w in after_cut)
            new_end_s = (phrase_end_s or cut_s) + target_slack_s
        else:
            new_end_s = cut_s + target_slack_s

        if next_start_s is not None and next_start_s > entry["end"]:
            new_end_s = min(new_end_s, next_start_s - 0.01)

        if new_end_s > entry["end"]:
            extend_ms = (new_end_s - entry["end"]) * 1000
            if straddling or close_after:
                after_cut = sorted(
                    [w for w in words if w["start"] >= cut_s - 0.1],
                    key=lambda w: w["start"],
                )
                phrase_words = " ".join(
                    w["word"] for w in after_cut if w["end"] <= new_end_s
                ).strip()
                msg = f"⚠ extended +{extend_ms:.0f}ms (phrase: \"{phrase_words[-40:]}\" → pause)"
            else:
                msg = f"⚠ extended +{extend_ms:.0f}ms (slack {slack*1000:.0f}ms)"
            entry["end"] = new_end_s
        else:
            msg = "✓ OK"
    else:
        heard_tail = " ".join(w["word"] for w in before[-3:]).strip()
        msg = f"✓ OK (slack {slack*1000:.0f}ms, ends: \"{heard_tail}\")"

    return i, entry, msg


def refine_end_times(clip_list: list, video_path: str, fps: float,
                     min_slack_s: float = 0.15,
                     target_slack_s: float = 0.35) -> list:
    """Parallel refinement: for each clip, call OpenAI Whisper on the cut-point window
    and extend end time to the next natural phrase pause if a word is being cut off.
    """
    client = _get_openai_client()
    if client is None:
        print("Warning: OpenAI not available (check OPENAI_API_KEY), skipping refinement.",
              file=sys.stderr)
        return clip_list

    from concurrent.futures import ThreadPoolExecutor, as_completed

    args_list = []
    for i, entry in enumerate(clip_list):
        next_start = clip_list[i + 1]["start"] if i + 1 < len(clip_list) else None
        args_list.append((i, entry, next_start, video_path, fps, min_slack_s, target_slack_s, client))

    print(f"\nRefining {len(clip_list)} clips in parallel...", file=sys.stderr)
    results = [None] * len(clip_list)

    with ThreadPoolExecutor(max_workers=min(6, len(clip_list))) as pool:
        futures = {pool.submit(_refine_one_clip, a): a[0] for a in args_list}
        for future in as_completed(futures):
            i, entry, msg = future.result()
            results[i] = (entry, msg)

    print("\nRefinement report:", file=sys.stderr)
    refined = []
    for i, (entry, msg) in enumerate(results):
        print(f"  Clip {i+1}: {msg}", file=sys.stderr)
        refined.append(entry)

    return refined


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------

def build_timeline(video_path: str, segments: list, timeline_name: str = None,
                   refine: bool = True) -> bool:
    video_path = str(Path(video_path).resolve())
    if not Path(video_path).exists():
        print(f"ERROR: Video file not found: {video_path}", file=sys.stderr)
        return False
    if not segments:
        print("ERROR: No segments provided.", file=sys.stderr)
        return False

    if timeline_name is None:
        timeline_name = Path(video_path).stem + "_autocut"

    src_fps = get_source_fps(video_path)
    print(f"Source fps: {src_fps:.3f}", file=sys.stderr)

    # Merge adjacent segments (gap < 0.5s) to avoid mid-sentence cuts
    merged = [dict(segments[0])]
    for seg in segments[1:]:
        gap = seg["start"] - merged[-1]["end"]
        if 0 <= gap < 0.5:
            merged[-1]["end"] = seg["end"]
            merged[-1]["text"] = (merged[-1].get("text", "") + " " + seg.get("text", "")).strip()
        else:
            merged.append(dict(seg))
    if len(merged) < len(segments):
        print(f"Merged {len(segments)} segments → {len(merged)} clips "
              f"(removed {len(segments)-len(merged)} micro-gaps)", file=sys.stderr)

    # Add 250ms end pad, capped at next clip's start to avoid overlap
    end_pad_s = 0.25
    clip_list = []
    for i, seg in enumerate(merged):
        end = seg["end"] + end_pad_s
        if i + 1 < len(merged):
            next_start = merged[i + 1]["start"]
            if next_start > seg["end"]:
                end = min(end, next_start - 0.01)
        if end <= seg["start"]:
            end = seg["start"] + 0.1
        clip_list.append({"start": seg["start"], "end": end, "text": seg.get("text", "")})

    # Skip refine if segments already came from trim_pass (already word-aligned)
    has_trim_notes = any("trim_note" in seg for seg in segments)
    if has_trim_notes and refine:
        print("Segments from trim_pass detected — skipping refine pass (already word-aligned).",
              file=sys.stderr)
        refine = False

    if refine:
        print(f"Refining end times ({len(clip_list)} clips)...", file=sys.stderr)
        clip_list = refine_end_times(clip_list, video_path, src_fps)

    print(f"\nConnecting to Premiere Pro bridge ({BRIDGE_DIR})...", file=sys.stderr)

    # Single ExtendScript that imports, creates sequence, and places all clips
    clips_json = json.dumps([{"start": c["start"], "end": c["end"]} for c in clip_list])

    script = f"""
try {{
  var videoPath = {json.dumps(video_path)};
  var timelineName = {json.dumps(timeline_name)};
  var clips = {clips_json};
  var TICKS = 254016000000;

  // ---- Find or import media ----
  var fileName = videoPath.split("/").pop();
  var projectItem = null;

  function walkItems(parent) {{
    for (var i = 0; i < parent.children.numItems; i++) {{
      var child = parent.children[i];
      if (child.type === ProjectItemType.BIN) {{
        var found = walkItems(child);
        if (found) return found;
      }} else {{
        try {{
          if (child.getMediaPath && child.getMediaPath() === videoPath) return child;
        }} catch(e) {{}}
        if (child.name === fileName && !projectItem) projectItem = child;
      }}
    }}
    return null;
  }}

  var existing = walkItems(app.project.rootItem);
  if (existing) {{
    projectItem = existing;
  }} else {{
    var importOk = app.project.importFiles([videoPath], true, app.project.rootItem, false);
    if (!importOk) return JSON.stringify({{ success: false, error: "importFiles failed for: " + videoPath }});
    projectItem = walkItems(app.project.rootItem);
    if (!projectItem && app.project.rootItem.children.numItems > 0) {{
      projectItem = app.project.rootItem.children[app.project.rootItem.children.numItems - 1];
    }}
  }}

  if (!projectItem) return JSON.stringify({{ success: false, error: "Could not find imported item in project" }});

  // ---- Delete existing sequence with same name ----
  for (var s = app.project.sequences.numSequences - 1; s >= 0; s--) {{
    if (app.project.sequences[s].name === timelineName) {{
      app.project.deleteSequence(app.project.sequences[s]);
      break;
    }}
  }}

  // ---- Create new sequence ----
  var seqId = "autocut-" + (new Date().getTime());
  app.project.createNewSequence(timelineName, seqId);
  var seq = __findSequenceByName(timelineName);
  if (!seq) return JSON.stringify({{ success: false, error: "Could not find created sequence: " + timelineName }});

  app.project.activeSequence = seq;

  // ---- Place clips with source in/out points ----
  var timelinePos = 0;
  var placed = 0;
  for (var i = 0; i < clips.length; i++) {{
    var clip = clips[i];
    var srcIn = clip.start;
    var srcOut = clip.end;
    var dur = srcOut - srcIn;
    if (dur <= 0) continue;

    // Set source in/out on project item for BOTH video (1) and audio (2) before placing
    projectItem.setInPoint(__secondsToTicks(srcIn), 1);
    projectItem.setOutPoint(__secondsToTicks(srcOut), 1);
    projectItem.setInPoint(__secondsToTicks(srcIn), 2);
    projectItem.setOutPoint(__secondsToTicks(srcOut), 2);

    seq.videoTracks[0].overwriteClip(projectItem, timelinePos);

    timelinePos += dur;
    placed++;
  }}

  // Reset source in/out so project item is unmodified
  projectItem.setInPoint("0", 1);
  projectItem.setInPoint("0", 2);

  return JSON.stringify({{
    success: true,
    sequenceName: timelineName,
    clipCount: placed,
    totalDuration: timelinePos,
    mediaItem: projectItem.name
  }});

}} catch(e) {{
  return JSON.stringify({{ success: false, error: e.toString() }});
}}
"""

    print(f"Building timeline '{timeline_name}' with {len(clip_list)} clips...", file=sys.stderr)
    try:
        result = execute_extendscript(script)
    except TimeoutError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return False

    # The bridge wraps the result: check both .result and top-level
    payload = result
    if isinstance(result, dict) and "result" in result:
        payload = result["result"]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            pass

    if isinstance(payload, dict) and payload.get("success"):
        total = payload.get("totalDuration", 0)
        count = payload.get("clipCount", 0)
        print(f"Done! Sequence '{timeline_name}' built: {count} clips, {total:.1f}s total",
              file=sys.stderr)
        print(f"Switch to the Timeline panel in Premiere Pro to review your cut.", file=sys.stderr)
        return True
    else:
        err = payload.get("error", "Unknown error") if isinstance(payload, dict) else str(payload)
        print(f"ERROR from Premiere: {err}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Build a Premiere Pro timeline from selected segments."
    )
    parser.add_argument("video_path", help="Path to the source video file")
    parser.add_argument("segments_json", help="Path to JSON file with selected segments")
    parser.add_argument("--timeline-name", default=None,
                        help="Name for the new sequence (default: video_stem_autocut)")
    parser.add_argument("--no-refine", action="store_true",
                        help="Skip Whisper end-time refinement pass (faster)")
    parser.add_argument("--bridge-dir", default=None,
                        help=f"Bridge temp dir (default: {BRIDGE_DIR})")
    args = parser.parse_args()

    if args.bridge_dir:
        BRIDGE_DIR = args.bridge_dir

    with open(args.segments_json) as f:
        data = json.load(f)

    if isinstance(data, list):
        segments = data
    elif isinstance(data, dict) and "segments" in data:
        segments = data["segments"]
    else:
        print("ERROR: segments_json must be a list or {\"segments\": [...]}", file=sys.stderr)
        sys.exit(1)

    success = build_timeline(args.video_path, segments, args.timeline_name,
                             refine=not args.no_refine)
    sys.exit(0 if success else 1)
