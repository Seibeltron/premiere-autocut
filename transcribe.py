#!/usr/bin/env python3
"""
transcribe.py — Word-accurate transcription using faster-whisper.
Outputs JSON to stdout: {segments, words, total_duration, method}

Usage:
    python transcribe.py /path/to/video.mp4
    python transcribe.py /path/to/video.mp4 > transcript.json
"""

import json
import sys
from pathlib import Path
from typing import Dict, List


WORD_PAD_S = 0.05  # 50ms padding on each word boundary


def _pad_words(words: List[Dict]) -> List[Dict]:
    return [
        {**w, "start": max(0.0, w["start"] - WORD_PAD_S), "end": w["end"] + WORD_PAD_S}
        for w in words
    ]


def _words_to_segments(words: List[Dict], pause_gap: float = 0.7) -> List[Dict]:
    if not words:
        return []
    segments = []
    cur = [words[0]]
    for w in words[1:]:
        gap = w["start"] - cur[-1]["end"]
        ends_sentence = cur[-1].get("word", "").strip().endswith((".", "!", "?"))
        if gap >= pause_gap or ends_sentence:
            segments.append(_finalize_segment(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        segments.append(_finalize_segment(cur))
    return segments


def _finalize_segment(words: List[Dict]) -> Dict:
    return {
        "start": words[0]["start"],
        "end": words[-1]["end"],
        "text": " ".join(w["word"] for w in words).strip(),
        "words": words,
    }


def build_segments(raw_segments: List[Dict], min_dur: float = 1.0, max_dur: float = 15.0) -> List[Dict]:
    if not raw_segments:
        return []

    # Merge short segments
    merged = []
    buf = raw_segments[0].copy()
    for seg in raw_segments[1:]:
        if buf["end"] - buf["start"] < min_dur:
            buf["end"] = seg["end"]
            buf["text"] = (buf["text"] + " " + seg["text"]).strip()
            buf["words"] = buf.get("words", []) + seg.get("words", [])
        else:
            merged.append(buf)
            buf = seg.copy()
    merged.append(buf)

    # Split long segments at the biggest pause gap
    final = []
    for seg in merged:
        dur = seg["end"] - seg["start"]
        words = seg.get("words", [])
        if dur > max_dur and len(words) >= 4:
            best_idx, best_gap = -1, 0.0
            for i in range(1, len(words)):
                g = words[i]["start"] - words[i - 1]["end"]
                if g > best_gap:
                    best_gap, best_idx = g, i
            if best_idx > 0 and best_gap > 0.15:
                lw, rw = words[:best_idx], words[best_idx:]
                final.append({"start": seg["start"], "end": lw[-1]["end"],
                               "text": " ".join(w["word"] for w in lw).strip(), "words": lw})
                final.append({"start": rw[0]["start"], "end": seg["end"],
                               "text": " ".join(w["word"] for w in rw).strip(), "words": rw})
                continue
        final.append(seg)

    output = []
    for seg in final:
        words = seg.get("words", [])
        s = words[0]["start"] if words else seg["start"]
        e = words[-1]["end"] if words else seg["end"]
        output.append({
            "start": s,
            "end": e,
            "duration": e - s,
            "text": seg.get("text", ""),
            "words": words,
            "word_count": len(words),
        })
    return output


def score_segments(
    segments: List[Dict],
    total_duration: float,
    keywords: List[str] = None,
    keyword_boost: float = 1.5,
) -> List[Dict]:
    scored = []
    for idx, seg in enumerate(segments):
        words = seg.get("words", [])
        dur = max(seg["duration"], 1e-6)

        # Confidence
        confidence = (sum(float(w.get("probability", 0.8)) for w in words) / len(words)) if words else 0.6

        # Density (words per second, normalised to ~3 wps)
        density = min(len(words) / dur / 3.0, 1.0)

        # Keyword hits
        kw_hits = 0
        kw_score = 0.0
        if keywords:
            lower = seg.get("text", "").lower()
            kw_hits = sum(lower.count(k.lower()) for k in keywords)
            kw_score = min(kw_hits * keyword_boost / 3.0, 1.0)

        # Position bonus (favour first 15% and last 10%)
        mid = (seg["start"] + seg["end"]) / 2.0
        rel = mid / max(total_duration, 1e-6)
        position = 1.0 if rel <= 0.15 else (0.8 if rel >= 0.90 else 0.4)

        score = 0.35 * confidence + 0.25 * density + 0.25 * kw_score + 0.15 * position

        scored.append({
            **seg,
            "score": score,
            "confidence": confidence,
            "density_wps": len(words) / dur,
            "keyword_hits": kw_hits,
        })
    return scored


def transcribe(video_path: str) -> Dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return {"error": "faster-whisper not installed. Run: pip install faster-whisper"}

    model = WhisperModel("large-v3", device="cpu", compute_type="int8")
    raw_segments, _info = model.transcribe(
        video_path,
        beam_size=1,
        language="en",
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=400),
        word_timestamps=True,
    )

    all_words = []
    raw = []
    for seg in raw_segments:
        words = []
        for w in getattr(seg, "words", None) or []:
            words.append({
                "word": getattr(w, "word", ""),
                "start": float(getattr(w, "start", 0.0)),
                "end": float(getattr(w, "end", 0.0)),
                "probability": float(getattr(w, "probability", 0.8) or 0.8),
            })
        all_words.extend(words)
        raw.append({"start": float(seg.start), "end": float(seg.end),
                    "text": seg.text.strip(), "words": words})

    if not raw:
        return {"error": "No speech detected"}

    all_words = _pad_words(all_words)

    # Re-assign padded words back into raw segments
    idx = 0
    for seg in raw:
        n = len(seg["words"])
        seg["words"] = all_words[idx:idx + n]
        if seg["words"]:
            seg["start"] = seg["words"][0]["start"]
            seg["end"] = seg["words"][-1]["end"]
        idx += n

    segments = build_segments(raw)
    total_dur = max((w["end"] for w in all_words), default=0.0)
    segments = score_segments(segments, total_dur)

    return {
        "segments": segments,
        "words": all_words,
        "total_duration": total_dur,
        "method": "faster-whisper",
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python transcribe.py <video_path>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    if not Path(path).exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    print(f"Transcribing: {path}", file=sys.stderr)
    result = transcribe(path)

    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    seg_count = len(result["segments"])
    dur = result["total_duration"]
    print(f"Done: {seg_count} segments, {dur:.1f}s total", file=sys.stderr)

    json.dump(result, sys.stdout, indent=2)
    print()  # trailing newline
