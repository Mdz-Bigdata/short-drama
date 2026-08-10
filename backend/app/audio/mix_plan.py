"""Editable audio mix manifest with BGM ducking and delivery loudness limits."""

from __future__ import annotations

import math

from app.schema.advanced import AudioMixPlan, AudioMixRequest, DialogueWindow


class AudioMixPlanner:
    @staticmethod
    def _windows(request: AudioMixRequest) -> list[DialogueWindow]:
        intervals = sorted(
            (track.start_ms, track.start_ms + track.duration_ms, track.id)
            for track in request.tracks if track.kind in {"dialogue", "voiceover"}
        )
        windows: list[DialogueWindow] = []
        for start, end, track_id in intervals:
            if windows and start <= windows[-1].end_ms + 80:
                windows[-1].end_ms = max(windows[-1].end_ms, end)
                windows[-1].track_ids.append(track_id)
            else:
                windows.append(DialogueWindow(start_ms=start, end_ms=end, track_ids=[track_id]))
        return windows

    def plan(self, request: AudioMixRequest) -> AudioMixPlan:
        filters: list[str] = []
        dialogue_labels: list[str] = []
        bgm_labels: list[str] = []
        other_labels: list[str] = []
        for index, track in enumerate(request.tracks):
            gain = math.pow(10.0, track.gain_db / 20.0)
            fade_out_start = max(0.0, (track.duration_ms - track.fade_out_ms) / 1000.0)
            label = f"t{index}"
            filters.append(
                f"[{index}:a]atrim=duration={track.duration_ms / 1000:.3f},asetpts=PTS-STARTPTS,"
                f"volume={gain:.6f},afade=t=in:st=0:d={track.fade_in_ms / 1000:.3f},"
                f"afade=t=out:st={fade_out_start:.3f}:d={track.fade_out_ms / 1000:.3f},"
                f"adelay={track.start_ms}|{track.start_ms}[{label}]"
            )
            if track.kind in {"dialogue", "voiceover"}:
                dialogue_labels.append(f"[{label}]")
            elif track.kind == "bgm":
                bgm_labels.append(f"[{label}]")
            else:
                other_labels.append(f"[{label}]")

        mixed_labels: list[str] = []
        if dialogue_labels:
            if len(dialogue_labels) == 1:
                filters.append(f"{dialogue_labels[0]}anull[dialogue]")
            else:
                filters.append(
                    f"{''.join(dialogue_labels)}amix=inputs={len(dialogue_labels)}:duration=longest:normalize=0[dialogue]"
                )
            mixed_labels.append("[dialogue]")
        if bgm_labels:
            if len(bgm_labels) == 1:
                filters.append(f"{bgm_labels[0]}anull[bgmraw]")
            else:
                filters.append(
                    f"{''.join(bgm_labels)}amix=inputs={len(bgm_labels)}:duration=longest:normalize=0[bgmraw]"
                )
            if dialogue_labels:
                filters.append(
                    "[bgmraw][dialogue]sidechaincompress=threshold=0.04:ratio=8:attack=20:release=350:makeup=1[bgmduck]"
                )
                mixed_labels.append("[bgmduck]")
            else:
                mixed_labels.append("[bgmraw]")
        mixed_labels.extend(other_labels)
        if len(mixed_labels) == 1:
            filters.append(f"{mixed_labels[0]}anull[premaster]")
        else:
            filters.append(
                f"{''.join(mixed_labels)}amix=inputs={len(mixed_labels)}:duration=longest:normalize=0[premaster]"
            )
        filters.append(
            f"[premaster]loudnorm=I={request.target_lufs}:TP={request.true_peak_db}:LRA=11,"
            f"alimiter=limit={math.pow(10.0, request.true_peak_db / 20.0):.6f}[mixout]"
        )
        return AudioMixPlan(
            duration_ms=request.duration_ms,
            tracks=request.tracks,
            dialogue_windows=self._windows(request),
            target_lufs=request.target_lufs,
            true_peak_db=request.true_peak_db,
            ffmpeg_filter_complex=";".join(filters),
        )
