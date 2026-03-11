#!/usr/bin/env python3
"""
build_timeline.py — Build a non-destructive DaVinci Resolve timeline from selected segments.

Each segment becomes a separate clip item on the timeline referencing the original source
file with in/out points. All cut points remain adjustable in Resolve's Edit page.

Usage:
    python build_timeline.py /path/to/video.mp4 /path/to/segments.json
    python build_timeline.py /path/to/video.mp4 /path/to/segments.json --timeline-name "My Cut"
"""

import json
import os
import subprocess
import sys
from fractions import Fraction
from pathlib import Path


def setup_resolve_env():
    """Set up environment variables and Python path for Resolve scripting API."""
    import platform
    if platform.system() == "Darwin":
        api_path = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
        lib_path = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
    elif platform.system() == "Windows":
        api_path = os.path.join(os.environ.get("PROGRAMDATA", "C:\\ProgramData"),
                                "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting")
        lib_path = os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"),
                                "Blackmagic Design", "DaVinci Resolve", "fusionscript.dll")
    else:  # Linux
        api_path = "/opt/resolve/Developer/Scripting"
        lib_path = "/opt/resolve/libs/fusionscript.so"

    modules_path = os.path.join(api_path, "Modules")
    os.environ["RESOLVE_SCRIPT_API"] = api_path
    os.environ["RESOLVE_SCRIPT_LIB"] = lib_path
    if modules_path not in sys.path:
        sys.path.insert(0, modules_path)


def connect_to_resolve():
    setup_resolve_env()
    try:
        import DaVinciResolveScript as dvr
        resolve = dvr.scriptapp("Resolve")
        if resolve is None:
            print("ERROR: Could not connect to DaVinci Resolve. Make sure Resolve is running.", file=sys.stderr)
            sys.exit(1)
        return resolve
    except ImportError as e:
        print(f"ERROR: Could not import DaVinci Resolve scripting module: {e}", file=sys.stderr)
        sys.exit(1)


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
        print(f"Warning: ffprobe failed ({e}), will use clip property", file=sys.stderr)
    return 0.0


# Map exact fps fractions to Resolve's timeline setting strings
_FPS_SETTING = {
    23.976: "23.976", 24.0: "24", 25.0: "25",
    29.97: "29.97",  30.0: "30", 47.952: "47.952",
    48.0: "48",      50.0: "50", 59.94: "59.94",
    60.0: "60",
}


def refine_end_frames(clip_list: list, video_path: str, fps: float,
                      min_slack_s: float = 0.15,
                      target_slack_s: float = 0.35) -> list:
    """For each clip, extract a short window from the SOURCE VIDEO straddling
    the cut point, transcribe it, and extend endFrame if a word is being cut off.
    This is more reliable than concatenation because we check the actual source audio.
    """
    import tempfile
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("Warning: faster-whisper not available, skipping refinement.", file=sys.stderr)
        return clip_list

    model = WhisperModel("large-v3", device="cpu", compute_type="int8")
    look_back_s = 1.0   # how far before the cut to start the window
    look_ahead_s = 4.0  # how far after the cut to search for cut-off words

    print("\nRefinement report:", file=sys.stderr)
    refined = []
    for i, entry in enumerate(clip_list):
        cut_s = entry["endFrame"] / fps  # current cut point in source video time

        win_start = max(0.0, cut_s - look_back_s)
        win_end = cut_s + look_ahead_s

        tmp_wav = None
        words = []
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_wav = f.name
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{win_start:.6f}", "-to", f"{win_end:.6f}",
                 "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000",
                 "-ac", "1", tmp_wav],
                capture_output=True, timeout=30,
            )
            raw_segs, _ = model.transcribe(
                tmp_wav, language="en", word_timestamps=True,
                vad_filter=False, no_speech_threshold=0.8, beam_size=1,
            )
            for seg in raw_segs:
                for w in getattr(seg, "words", None) or []:
                    # Convert window-relative timestamps to source-video timestamps
                    words.append({
                        "word": getattr(w, "word", "").strip(),
                        "start": float(getattr(w, "start", 0)) + win_start,
                        "end":   float(getattr(w, "end",   0)) + win_start,
                    })
        finally:
            if tmp_wav:
                try: os.unlink(tmp_wav)
                except OSError: pass

        # Words that straddle the cut (started before, end after)
        straddling = [w for w in words if w["start"] < cut_s < w["end"]]
        # Words that end very close after the cut (within 0.4s — probably clipped)
        close_after = [w for w in words if cut_s <= w["end"] <= cut_s + 0.4]
        # Slack: gap between last heard word before cut and the cut point
        before = [w for w in words if w["end"] <= cut_s]
        slack = (cut_s - before[-1]["end"]) if before else 999.0

        needs_extend = bool(straddling or close_after) or slack < min_slack_s

        if needs_extend:
            entry = dict(entry)
            if straddling or close_after:
                # Walk forward from the cut to find the first natural pause (gap > 300ms).
                # This captures full phrases like "become one of the world's..." rather than
                # stopping at the first straddling word.
                after_cut = sorted([w for w in words if w["start"] >= cut_s - 0.1],
                                   key=lambda w: w["start"])
                phrase_end_s = None
                for j in range(len(after_cut) - 1):
                    if after_cut[j]["end"] > cut_s:
                        gap = after_cut[j + 1]["start"] - after_cut[j]["end"]
                        if gap > 0.3:
                            phrase_end_s = after_cut[j]["end"]
                            break
                if phrase_end_s is None and after_cut:
                    phrase_end_s = max(w["end"] for w in after_cut)
                new_end_s = (phrase_end_s or cut_s) + target_slack_s
            else:
                new_end_s = cut_s + target_slack_s

            new_end_frame = int(new_end_s * fps)
            if i + 1 < len(clip_list):
                new_end_frame = min(new_end_frame, clip_list[i + 1]["startFrame"] - 1)

            if new_end_frame > entry["endFrame"]:
                extend_ms = (new_end_frame - entry["endFrame"]) / fps * 1000
                if straddling or close_after:
                    phrase_words = " ".join(w["word"] for w in after_cut
                                           if w["end"] <= new_end_s).strip()
                    issue = f"phrase: \"{phrase_words[-40:]}\" → pause"
                else:
                    issue = f"slack {slack*1000:.0f}ms"
                print(f"  Clip {i+1}: ⚠ extended +{extend_ms:.0f}ms ({issue})", file=sys.stderr)
                entry["endFrame"] = new_end_frame
            else:
                print(f"  Clip {i+1}: ✓ OK", file=sys.stderr)
        else:
            heard_tail = " ".join(w["word"] for w in before[-3:]).strip()
            print(f"  Clip {i+1}: ✓ OK (slack {slack*1000:.0f}ms, ends: \"{heard_tail}\")",
                  file=sys.stderr)

        refined.append(entry)

    return refined


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

    # Detect source fps — used for all frame calculations
    src_fps = get_source_fps(video_path)
    if src_fps <= 0:
        src_fps = 24.0
        print(f"Warning: Could not detect source fps, defaulting to {src_fps}", file=sys.stderr)
    print(f"Source fps: {src_fps}", file=sys.stderr)

    print(f"Connecting to DaVinci Resolve...", file=sys.stderr)
    resolve = connect_to_resolve()

    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject()
    if project is None:
        print("ERROR: No project open in DaVinci Resolve. Please open a project first.", file=sys.stderr)
        return False

    print(f"Project: {project.GetName()}", file=sys.stderr)

    # Use source fps for all frame calculations
    fps = src_fps

    # Import video into media pool
    media_pool = project.GetMediaPool()
    print(f"Importing: {Path(video_path).name}", file=sys.stderr)
    imported = media_pool.ImportMedia([video_path])

    if not imported:
        print("ERROR: Failed to import media. Check the file path and format.", file=sys.stderr)
        return False

    clip = imported[0]
    print(f"Imported: {clip.GetName()}", file=sys.stderr)

    # Delete any existing timeline with this name to start fresh
    for i in range(project.GetTimelineCount(), 0, -1):
        existing = project.GetTimelineByIndex(i)
        if existing and existing.GetName() == timeline_name:
            media_pool.DeleteTimelines([existing])
            print(f"Deleted existing timeline '{timeline_name}'", file=sys.stderr)
            break

    # Set project fps to match source BEFORE creating the timeline.
    # This only succeeds when there are no other timelines (fresh project).
    fps_key = min(_FPS_SETTING, key=lambda k: abs(k - fps))
    fps_setting = _FPS_SETTING[fps_key]
    result = project.SetSetting("timelineFrameRate", fps_setting)
    print(f"Set project fps to {fps_setting}: {result}", file=sys.stderr)

    # Create an empty timeline — project fps was already set to match source above.
    print(f"Creating empty timeline '{timeline_name}'...", file=sys.stderr)
    timeline = media_pool.CreateEmptyTimeline(timeline_name)
    if not timeline:
        print(f"ERROR: Could not create timeline '{timeline_name}'", file=sys.stderr)
        return False

    project.SetCurrentTimeline(timeline)
    tl_fps = timeline.GetSetting("timelineFrameRate")
    print(f"Timeline created: {timeline_name} @ {tl_fps} fps", file=sys.stderr)

    # Merge adjacent segments (gap < 0.5s) into single clips to avoid mid-sentence cuts
    merged = [dict(segments[0])]
    for seg in segments[1:]:
        gap = seg["start"] - merged[-1]["end"]
        if gap < 0.5:
            merged[-1]["end"] = seg["end"]
            merged[-1]["text"] = (merged[-1].get("text", "") + " " + seg.get("text", "")).strip()
        else:
            merged.append(dict(seg))
    if len(merged) < len(segments):
        print(f"Merged {len(segments)} segments → {len(merged)} clips (removed {len(segments)-len(merged)} mid-sentence cuts)", file=sys.stderr)

    # Build clip list — startFrame/endFrame in source clip's native fps
    end_pad_s = 0.25  # 250ms end pad to avoid clipping word endings
    end_pad_frames = int(end_pad_s * fps)
    clip_list = []
    for i, seg in enumerate(merged):
        start_frame = int(seg["start"] * fps)
        raw_end_frame = int(seg["end"] * fps)
        # Cap end pad so it doesn't bleed into the next clip's start
        if i + 1 < len(merged):
            next_start_frame = int(merged[i + 1]["start"] * fps)
            end_frame = min(raw_end_frame + end_pad_frames, next_start_frame - 1)
        else:
            end_frame = raw_end_frame + end_pad_frames
        if end_frame <= start_frame:
            end_frame = start_frame + 1
        clip_list.append({
            "mediaPoolItem": clip,
            "startFrame": start_frame,
            "endFrame": end_frame,
        })

    if refine:
        print(f"Refining end frames ({len(clip_list)} clips)...", file=sys.stderr)
        clip_list = refine_end_frames(clip_list, video_path, fps)

    print(f"Appending {len(clip_list)} clips to timeline...", file=sys.stderr)
    result = media_pool.AppendToTimeline(clip_list)
    if not result:
        print("ERROR: AppendToTimeline failed.", file=sys.stderr)
        return False

    total_dur = sum(seg["end"] - seg["start"] for seg in segments)
    print(f"Done! Timeline '{timeline_name}' built with {len(clip_list)} clips ({total_dur:.1f}s total)", file=sys.stderr)
    print(f"Switch to the Edit page in DaVinci Resolve to review your cut.", file=sys.stderr)

    # Switch to Edit page
    resolve.OpenPage("edit")

    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build a DaVinci Resolve timeline from selected segments.")
    parser.add_argument("video_path", help="Path to the source video file")
    parser.add_argument("segments_json", help="Path to JSON file with selected segments")
    parser.add_argument("--timeline-name", default=None, help="Name for the new timeline (default: video_stem_autocut)")
    parser.add_argument("--no-refine", action="store_true", help="Skip Whisper end-frame refinement pass (faster)")
    args = parser.parse_args()

    with open(args.segments_json) as f:
        data = json.load(f)

    # Accept either a list of segments directly, or a dict with a "segments" key
    if isinstance(data, list):
        segments = data
    elif isinstance(data, dict) and "segments" in data:
        segments = data["segments"]
    else:
        print("ERROR: segments_json must be a list of segments or {\"segments\": [...]}", file=sys.stderr)
        sys.exit(1)

    success = build_timeline(args.video_path, segments, args.timeline_name,
                             refine=not args.no_refine)
    sys.exit(0 if success else 1)
