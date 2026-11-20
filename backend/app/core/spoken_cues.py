# -*- coding: utf-8 -*-
"""Subtitles for a clip that keeps the video model's own voices, taken from what the clip actually says.

A clip with native sound speaks its lines where the model put them, not where an estimate from
reading speed would put them, and now and then with words of its own. The subtitles of such a clip
are therefore made from its audio:

* With speech recognition configured (ElevenLabs Scribe), the clip is transcribed with word times.
  Each script sentence is matched to the stretch of speech that says it and shown exactly while it
  is spoken; the script's own wording is kept when the speech says it (recognition gets homophones
  wrong), a stretch of speech that matches no script sentence is shown as heard, and a script
  sentence nobody says gets no subtitle.
* Without it, the clip's voice activity is measured locally (ffmpeg) and the script sentences are
  laid over the stretches where someone is speaking, in order, so a subtitle appears while mouths
  move rather than over silence.

Times are seconds into the untrimmed clip; :func:`trimmed` moves them to a trimmed one.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from difflib import SequenceMatcher
from typing import Any

from app.core import usage_ledger

logger = logging.getLogger(__name__)

# A sentence ends at CJK or Latin terminal punctuation; spaces separate the dialogue cell's lines.
_SENTENCE_END = re.compile(r"(?<=[。！？!?…])\s*|\s+")
_NOT_TEXT = re.compile(r"[\s\W_]+", re.UNICODE)
_CJK = re.compile(r"[㐀-鿿]")
# Speech recognition joins words into one stretch until the speaker changes, a sentence ends or
# the speaker pauses this long.
SEGMENT_PAUSE_S = 0.6
# How alike a stretch of speech and a script sentence must be to count as the same line.
MATCH_AT = 0.5
# A subtitle shows a little before the voice and stays a little after it, and at least this long.
LEAD_S = 0.1
HOLD_S = 0.35
MIN_SHOW_S = 1.0
# Voice activity: speech-band energy within this many dB of the clip's loudest moment.
VOICE_BELOW_PEAK_DB = 20.0
VOICE_FLOOR_DB = -45.0
VOICE_MIN_PAUSE_S = 0.3
VOICE_MIN_SPAN_S = 0.2

Cue = dict[str, Any]


def sentences(text: str) -> list[str]:
    """The subtitle line split the way the compositor splits it: one sentence per cue."""
    return [part.strip() for part in _SENTENCE_END.split(str(text or "").strip()) if part and part.strip()]


def _plain(text: str) -> str:
    return _NOT_TEXT.sub("", str(text or "")).lower()


def _alike(a: str, b: str) -> float:
    a, b = _plain(a), _plain(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _join(parts: Iterable[str]) -> str:
    """Words of a transcript: CJK runs together, Latin words keep a space."""
    out = ""
    for part in parts:
        part = str(part or "").strip()
        if not part:
            continue
        if out and not (_CJK.search(out[-1]) or _CJK.search(part[0])) and out[-1].isalnum() and part[0].isalnum():
            out += " "
        out += part
    return out


def speech_segments(words: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Stretches of continuous speech in a word-timed transcript: text, start, end."""
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for word in words:
        if str(word.get("type") or "word") != "word":
            continue
        text = str(word.get("text") or "").strip()
        start, end = float(word.get("start") or 0.0), float(word.get("end") or word.get("start") or 0.0)
        if not text:
            continue
        speaker = word.get("speaker_id")
        if current is not None and (
            start - current["end"] > SEGMENT_PAUSE_S
            or (speaker is not None and current["speaker"] is not None and speaker != current["speaker"])
            or re.search(r"[。！？!?…]$", current["words"][-1])
        ):
            segments.append(current)
            current = None
        if current is None:
            current = {"start": start, "end": end, "speaker": speaker, "words": []}
        current["words"].append(text)
        current["end"] = max(current["end"], end)
    if current is not None:
        segments.append(current)
    return [{"text": _join(item["words"]), "start": item["start"], "end": item["end"]} for item in segments]


def _align(lines: Sequence[str], heard: Sequence[Mapping[str, Any]]) -> list[tuple[list[int], list[int]]]:
    """Pair script sentences with stretches of speech, in order: one to one, two sentences said in one
    breath, one sentence said with a pause in it, or either side left unpaired."""
    n, m = len(lines), len(heard)
    best: list[list[float]] = [[float("-inf")] * (m + 1) for _ in range(n + 1)]
    step: list[list[tuple[int, int] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0
    texts = [str(item["text"]) for item in heard]
    for i in range(n + 1):
        for j in range(m + 1):
            here = best[i][j]
            if here == float("-inf"):
                continue
            moves: list[tuple[int, int, float]] = [(1, 0, 0.0), (0, 1, 0.0)]
            for di, dj in ((1, 1), (2, 1), (1, 2)):
                if i + di <= n and j + dj <= m:
                    score = _alike("".join(lines[i:i + di]), "".join(texts[j:j + dj]))
                    if score >= MATCH_AT:
                        # Every pairing is worth the same plus how alike it is: joining a neighbour on
                        # only pays when the joined text matches better than the single one.
                        moves.append((di, dj, score + 1.0))
            for di, dj, gain in moves:
                if i + di <= n and j + dj <= m and here + gain > best[i + di][j + dj]:
                    best[i + di][j + dj] = here + gain
                    step[i + di][j + dj] = (di, dj)
    pairs: list[tuple[list[int], list[int]]] = []
    i, j = n, m
    while i or j:
        di, dj = step[i][j] or (1, 0)
        pairs.append((list(range(i - di, i)), list(range(j - dj, j))))
        i, j = i - di, j - dj
    pairs.reverse()
    return pairs


def _shown(raw: list[tuple[str, float, float]], duration: float | None) -> list[Cue]:
    """Speech times turned into display times: a touch early, held a moment, never overlapping."""
    raw = sorted((item for item in raw if item[0].strip()), key=lambda item: item[1])
    cues: list[Cue] = []
    for index, (text, start, end) in enumerate(raw):
        begin = max(0.0, start - LEAD_S, cues[-1]["end"] if cues else 0.0)
        limit = raw[index + 1][1] - LEAD_S if index + 1 < len(raw) else float("inf")
        if duration:
            limit = min(limit, duration)
        finish = min(max(end + HOLD_S, begin + MIN_SHOW_S), limit)
        if finish - begin < 0.05:
            continue
        cues.append({"text": text, "start": round(begin, 3), "end": round(finish, 3)})
    return cues


def from_transcript(subtitle: str, words: Sequence[Mapping[str, Any]], duration: float | None = None) -> list[Cue]:
    """Cues from a word-timed transcript, keeping the script's wording where the speech says it."""
    lines = sentences(subtitle)
    heard = speech_segments(words)
    raw: list[tuple[str, float, float]] = []
    for line_ids, heard_ids in _align(lines, heard):
        if not heard_ids:
            continue  # a script sentence nobody says gets no subtitle
        start, end = heard[heard_ids[0]]["start"], heard[heard_ids[-1]]["end"]
        if not line_ids:
            raw.append((_join(heard[k]["text"] for k in heard_ids), start, end))  # said, but not in the script
            continue
        # Two sentences in one breath: split the stretch by how much of it each sentence is.
        sizes = [max(1, len(_plain(lines[k]))) for k in line_ids]
        at = start
        for k, size in zip(line_ids, sizes):
            stop = at + (end - start) * size / sum(sizes)
            raw.append((lines[k], at, stop))
            at = stop
    return _shown(raw, duration)


def from_voice(subtitle: str, spans: Sequence[tuple[float, float]], duration: float | None = None) -> list[Cue]:
    """Cues laid over the stretches where someone speaks, in order and in proportion to each sentence."""
    from app.core.screenwriting.speech_rate import line_seconds

    lines = sentences(subtitle)
    spans = [(float(a), float(b)) for a, b in spans if b > a]
    if not lines or not spans:
        return []
    if len(spans) == len(lines):
        return _shown([(line, a, b) for line, (a, b) in zip(lines, spans)], duration)
    weights = [max(0.1, line_seconds(line)) for line in lines]
    voiced = sum(b - a for a, b in spans)

    def real_time(position: float) -> float:
        """A point on the speaking-only clock back on the clip's clock."""
        for a, b in spans:
            if position <= b - a + 1e-9:
                return a + position
            position -= b - a
        return spans[-1][1]

    raw, spoken = [], 0.0
    for line, weight in zip(lines, weights):
        share = voiced * weight / sum(weights)
        raw.append((line, real_time(spoken + 1e-6), real_time(spoken + share)))
        spoken += share
    return _shown(raw, duration)


def trimmed(cues: Sequence[Mapping[str, Any]], start: float, end: float | None) -> list[tuple[str, float, float]]:
    """Cues of the untrimmed clip on the clock of the trimmed one; cues cut away by the trim are dropped."""
    out: list[tuple[str, float, float]] = []
    for cue in cues:
        a, b = float(cue.get("start") or 0.0), float(cue.get("end") or 0.0)
        if end is not None:
            b = min(b, float(end))
        a = max(a, float(start or 0.0))
        if b - a < 0.3:
            continue
        out.append((str(cue.get("text") or ""), round(a - float(start or 0.0), 3), round(b - float(start or 0.0), 3)))
    return out


# ---------------------------------------------------------------------------- reading the clip


def _run(cmd: list[str], timeout: float = 120) -> str:
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    return done.stderr or ""


def voice_spans(path: str, ffmpeg: str) -> list[tuple[float, float]]:
    """Where someone is speaking in the clip: speech-band energy close to the clip's loudest moment."""
    band = "highpass=f=180,lowpass=f=3800"
    level = re.search(r"max_volume:\s*(-?[\d.]+) dB", _run([ffmpeg, "-nostdin", "-i", path, "-vn", "-af", f"{band},volumedetect", "-f", "null", "-"]))
    if not level:
        return []
    threshold = max(VOICE_FLOOR_DB, float(level.group(1)) - VOICE_BELOW_PEAK_DB)
    log = _run([ffmpeg, "-nostdin", "-i", path, "-vn", "-af", f"{band},silencedetect=noise={threshold:.1f}dB:d={VOICE_MIN_PAUSE_S}", "-f", "null", "-"])
    total = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", log)
    length = int(total.group(1)) * 3600 + int(total.group(2)) * 60 + float(total.group(3)) if total else None
    if length is None:
        return []
    spans, cursor, silent = [], 0.0, False
    for kind, value in re.findall(r"silence_(start|end):\s*(-?[\d.]+)", log):
        if kind == "start":
            spans.append((cursor, float(value)))
            silent = True
        else:
            cursor, silent = float(value), False
    if not silent and cursor < length:
        spans.append((cursor, length))
    return [(round(a, 3), round(b, 3)) for a, b in spans if b - a >= VOICE_MIN_SPAN_S]


def transcribe(path: str, ffmpeg: str, *, speakers: int | None = None) -> list[dict[str, Any]] | None:
    """Word-timed transcript of the clip's voice from ElevenLabs Scribe; ``None`` when it is not available."""
    from app.core.providers.elevenlabs import ElevenLabsClient

    if not recognition_available():
        return None
    handle, audio = tempfile.mkstemp(suffix=".mp3")
    os.close(handle)
    started = time.monotonic()
    try:
        subprocess.run([ffmpeg, "-nostdin", "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", audio],
                       capture_output=True, timeout=120, stdin=subprocess.DEVNULL, check=True)
        client = ElevenLabsClient()
        try:
            with open(audio, "rb") as file:
                result = client.transcribe(file, filename="clip.mp3", diarize=bool(speakers and speakers > 1), num_speakers=speakers)
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001 - without a transcript the clip is timed from its voice instead
        usage_ledger.record("audio", provider="elevenlabs", model="scribe_v2", status="failed", error=type(exc).__name__,
                            duration_ms=int((time.monotonic() - started) * 1000))
        logger.warning("[Subtitles] 原声识别失败，改按人声起止排字幕: %s", type(exc).__name__)
        return None
    finally:
        try:
            os.remove(audio)
        except OSError:
            pass
    words = [dict(word) for word in result.get("words") or [] if isinstance(word, Mapping)]
    seconds = max((float(word.get("end") or 0.0) for word in words), default=0.0)
    usage_ledger.record("audio", provider="elevenlabs", model="scribe_v2", status="success",
                        units={"seconds": round(seconds, 2)}, duration_ms=int((time.monotonic() - started) * 1000))
    return words


def recognition_available() -> bool:
    """Speech recognition is on: an ElevenLabs connection with a Scribe model enabled, or a key in the environment."""
    from app.platform.runtime_models import runtime_model_registry

    saved = runtime_model_registry.first("elevenlabs", "audio")
    if saved is not None:
        return bool(saved.api_key.strip()) and any("scribe" in model for model in saved.model_ids)
    return bool(os.getenv("ELEVENLABS_API_KEY", "").strip())


def for_clip(
    path: str, subtitle: str, *, ffmpeg: str, video_url: str, duration: float | None = None, speakers: int | None = None,
    listen: Callable[..., list[dict[str, Any]] | None] = transcribe,
) -> dict[str, Any] | None:
    """The clip's subtitle cues from its own sound, with what they were made from; ``None`` when nothing was heard."""
    if not sentences(subtitle):
        return None
    words = listen(path, ffmpeg, speakers=speakers)
    if words:
        cues = from_transcript(subtitle, words, duration)
        if cues:
            return {"video_url": video_url, "source": "transcript", "cues": cues,
                    "heard": _join(item["text"] for item in speech_segments(words))}
    spans = voice_spans(path, ffmpeg)
    cues = from_voice(subtitle, spans, duration)
    return {"video_url": video_url, "source": "voice", "cues": cues} if cues else None




# ---------------------------------------------------------------------------- stage 6


def _speaker_count(dialogue: str) -> int | None:
    names = {name for name in re.findall(r"(?:^|\s)([^\s：:（(]{1,12})(?:（[^）]*）)?[：:]", str(dialogue or ""))}
    return len(names) or None


def clip_cues(shot: Mapping[str, Any]) -> dict[str, Any] | None:
    """Cues for one native-sound clip of stage 5, from its own sound; ``None`` when it has no line or no sound."""
    from app.core import media_compositor
    from app.core.spoken_lines import spoken_lines

    url = str(shot.get("video_url") or "")
    subtitle = " ".join(spoken_lines([str(shot.get("dialogue") or "")]))
    ffmpeg = media_compositor._ffmpeg()
    if not url or not ffmpeg or not sentences(subtitle) or not media_compositor.media_available(url):
        return None
    path, temporary = media_compositor.local_media_path(url), None
    try:
        if not path:
            handle, temporary = tempfile.mkstemp(suffix=".mp4")
            os.close(handle)
            if not media_compositor._download(url, temporary):
                return None
            path = temporary
        duration = media_compositor._probe_duration(path)
        return for_clip(path, subtitle, ffmpeg=ffmpeg, video_url=url, duration=duration, speakers=_speaker_count(str(shot.get("dialogue") or "")))
    except Exception as exc:  # noqa: BLE001 - a clip that cannot be read keeps the estimated subtitle timing
        logger.warning("[Subtitles] 片段 %s 的原声字幕没排成: %s", url[-40:], type(exc).__name__)
        return None
    finally:
        if temporary:
            try:
                os.remove(temporary)
            except OSError:
                pass


def cues_for_shots(shots: Sequence[Any], native: Sequence[bool], *, workers: int = 4) -> list[dict[str, Any] | None]:
    """One entry per shot, in order: the cues of each native-sound clip with a line, ``None`` for the rest."""
    from concurrent.futures import ThreadPoolExecutor
    import contextvars

    wanted = [index for index, shot in enumerate(shots) if index < len(native) and native[index] and isinstance(shot, Mapping)]
    found: list[dict[str, Any] | None] = [None] * len(shots)
    if not wanted:
        return found
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(wanted)))) as pool:
        # Each call carries this project's context, so a transcription is booked to it.
        futures = {index: pool.submit(contextvars.copy_context().run, clip_cues, shots[index]) for index in wanted}
        for index, future in futures.items():
            found[index] = future.result()
    return found


def for_timeline_clip(record: Any, clip: Mapping[str, Any]) -> list[Cue] | None:
    """The cues stage 6 made for this clip, when they are still about its footage and its words were not edited."""
    if not isinstance(record, Mapping) or clip.get("subtitle_edited"):
        return None
    if str(record.get("video_url") or "") != str(clip.get("video_url") or ""):
        return None
    cues = [dict(cue) for cue in record.get("cues") or [] if isinstance(cue, Mapping)]
    return cues or None


__all__ = [
    "clip_cues", "cues_for_shots", "for_clip", "for_timeline_clip", "from_transcript", "from_voice", "recognition_available",
    "sentences", "speech_segments", "transcribe", "trimmed", "voice_spans",
]
