# -*- coding: utf-8 -*-
"""
本地媒体合成器 (Media Compositor)
- TTS：基于 macOS 内置 `say` 合成真实中文语音 (完全离线)，转码为 mp3。
- 成片合成：用 ffmpeg 将多镜头视频统一为 9:16 竖屏、烧录中文字幕(PIL渲染PNG叠加)、
  拼接为一条片，并混入配音音轨，导出最终 mp4。
所有方法均为防御式实现：任何环节失败都返回 None / 空，由上层平滑回退，绝不抛出中断主流程。
"""
import os
import re
import shutil
import logging
import hashlib
import json
import socket
import subprocess
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

from app import settings
from app.platform.runtime_models import provider_key_available, runtime_model_registry

logger = logging.getLogger("app.core.media_compositor")

# 生成媒体的存储目录 (由 main.py 挂载到 /media 静态路由对外提供访问)
MEDIA_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "generated_media"))
# 对外访问基地址：MEDIA_PUBLIC_BASE_URL，未配置时由 PUBLIC_BASE_URL / BACKEND_PORT 推导
PUBLIC_BASE_URL = settings.media_public_base_url()

# 输出竖屏母版。供应商预览可低分辨率，但最终合成统一为平台标准 FHD。
OUT_W, OUT_H = 1080, 1920
# 母版帧率：各家模型出的片段帧率不一，合成时统一到这个值
OUT_FPS = 30
# 片头标题卡的副标题与无标题时的占位；TITLE_CARD_TAGLINE 可改成自己的厂牌，设为空则不显示
DEFAULT_TITLE_TAGLINE = ""
UNTITLED_FILM = "短剧"
# 片头标题卡时长(秒)
TITLE_DUR = 2.6
# 男声音高比例 (基于 Tingting 女声降调模拟男声；say 输出固定 22050Hz)
SAY_RATE = 22050
MALE_PITCH = 0.82
# 情绪 -> (语速 words/min, 音高系数)，让配音有情绪感染力与节奏变化
EMOTION_PRESETS = {
    "neutral": (180, 1.00),
    "angry":   (208, 1.04),   # 愤怒/激动：快而高亢
    "shout":   (215, 1.06),   # 怒吼/爆发
    "cold":    (162, 0.97),   # 冷峻/讥讽：慢而压低
    "sad":     (148, 0.95),   # 悲伤/绝望：缓慢低沉
    "tense":   (200, 1.01),   # 紧张/急迫
    "happy":   (192, 1.03),   # 喜悦/得意
    "tender":  (168, 1.00),   # 温柔/深情
}


def _ensure_dir():
    os.makedirs(MEDIA_DIR, exist_ok=True)


# 常见安装位置：Homebrew (Apple Silicon / Intel) 与 Linux 发行版
_BINARY_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")
# 字幕与标题卡用的中文字体候选，按平台依次尝试；都没有时用 SUBTITLE_FONT_PATH 指定
_CJK_FONT_CANDIDATES = (
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "C:/Windows/Fonts/msyh.ttc",
)
# macOS `say` 的中文音色；可用 LOCAL_TTS_VOICE 换成本机已安装的其它音色
DEFAULT_LOCAL_TTS_VOICE = "Tingting"


def _which(name: str, fallbacks: Optional[list] = None, *, override: Optional[str] = None) -> Optional[str]:
    """Locate a binary: an explicit path from the environment, then PATH, then the usual install dirs."""
    configured = (os.getenv(override) or "").strip() if override else ""
    if configured:
        return configured if os.path.exists(configured) else None
    p = shutil.which(name)
    if p:
        return p
    for fb in fallbacks or [os.path.join(directory, name) for directory in _BINARY_DIRS]:
        if os.path.exists(fb):
            return fb
    return None


def _ffmpeg() -> Optional[str]:
    return _which("ffmpeg", override="FFMPEG_PATH")


def _ffprobe() -> Optional[str]:
    return _which("ffprobe", override="FFPROBE_PATH")


def _say() -> Optional[str]:
    return _which("say", ["/usr/bin/say"])


def _local_tts_voice() -> str:
    return (os.getenv("LOCAL_TTS_VOICE") or "").strip() or DEFAULT_LOCAL_TTS_VOICE


def _font_path() -> Optional[str]:
    configured = (os.getenv("SUBTITLE_FONT_PATH") or "").strip()
    for p in ([configured] if configured else []) + list(_CJK_FONT_CANDIDATES):
        if os.path.exists(p):
            return p
    return None


def public_url(filename: str) -> str:
    return f"{PUBLIC_BASE_URL.rstrip('/')}/{filename}"


def local_media_path(url: object) -> Optional[str]:
    """本服务 /media 地址(或 /media/ 开头的路径)对应的本地文件；不是本地媒体、文件不存在或越出媒体目录时为 None。"""
    value = str(url or "").strip()
    if not value:
        return None
    base = PUBLIC_BASE_URL.rstrip("/") + "/"
    if value.startswith(base):
        relative = value[len(base):]
    elif value.startswith(settings.MEDIA_PREFIX):
        relative = value[len(settings.MEDIA_PREFIX):]
    else:
        return None
    relative = relative.split("?", 1)[0].split("#", 1)[0]
    root = os.path.realpath(MEDIA_DIR)
    path = os.path.realpath(os.path.join(root, relative))
    if not path.startswith(root + os.sep) or not os.path.isfile(path):
        return None
    return path


#: 内嵌图上限：与模型网关接受的 data URI 大小一致。
INLINE_IMAGE_LIMIT = 14 * 1024 * 1024
_INLINE_TYPES = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"RIFF", "image/webp"))


def inline_local_image(url: object) -> object:
    """本地媒体里的图读成 data URI 交给供应商(它们取不到 localhost)；其它地址原样返回。"""
    path = local_media_path(url)
    if path is None:
        return url
    try:
        with open(path, "rb") as handle:
            data = handle.read(INLINE_IMAGE_LIMIT + 1)
    except OSError:
        return url
    if len(data) > INLINE_IMAGE_LIMIT:
        return url
    mime = next((mime for magic, mime in _INLINE_TYPES if data.startswith(magic)), None)
    if mime is None or (mime == "image/webp" and data[8:12] != b"WEBP"):
        return url
    import base64

    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _synth_clip(text: str, gender: str, out_mp3: str, emotion: str = "neutral", voice: Optional[str] = None) -> bool:
    """合成单句语音到 out_mp3。gender='male' 时降调模拟男声；emotion 控制语速与音高营造情绪与节奏。"""
    say_bin = _say()
    ff = _ffmpeg()
    if not say_bin or not ff or not text.strip():
        return False
    # 情绪 -> (语速 words/min, 音高系数)，营造情绪感染力与节奏
    rate, emo_pitch = EMOTION_PRESETS.get(emotion, EMOTION_PRESETS["neutral"])
    aiff = out_mp3 + ".aiff"
    try:
        subprocess.run([say_bin, "-v", voice or _local_tts_voice(), "-r", str(rate), "-o", aiff, text.strip()[:300]],
                       check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # 综合音高：男声基准降调 × 情绪音高系数
        base_pitch = MALE_PITCH if gender == "male" else 1.0
        pitch = base_pitch * emo_pitch
        if abs(pitch - 1.0) > 0.01:
            af = f"asetrate={SAY_RATE}*{pitch:.4f},atempo={1/pitch:.5f},aresample=44100"
            cmd = [ff, "-y", "-i", aiff, "-af", af, "-codec:a", "libmp3lame", "-q:a", "4", out_mp3]
        else:
            cmd = [ff, "-y", "-i", aiff, "-codec:a", "libmp3lame", "-q:a", "4", out_mp3]
        subprocess.run(cmd, check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return os.path.exists(out_mp3)
    except Exception as e:
        logger.warning(f"[Compositor] 单句配音失败: {str(e)[:120]}")
        return False
    finally:
        if os.path.exists(aiff):
            os.remove(aiff)


def synthesize_dialogue_track(segments, tag: str = "voice") -> Tuple[Optional[str], Optional[str]]:
    """
    多角色配音轨：segments 为 [(台词, 'male'/'female', emotion), ...] (emotion 可省略)，
    按角色性别用不同音色、按情绪调节语速音高逐句合成，句间插 0.35s 停顿后拼接。
    返回 (对外URL, 本地文件路径)。
    """
    ff = _ffmpeg()
    segs = []
    for seg in (segments or []):
        t = re.sub(r"\s+", " ", (seg[0] or "")).strip()
        g = seg[1] if len(seg) > 1 else "female"
        emo = seg[2] if len(seg) > 2 else "neutral"
        if t:
            segs.append((t, g, emo))
    if not ff or not segs:
        return None, None
    _ensure_dir()
    h = hashlib.md5(("|".join(f"{g}:{e}:{t}" for t, g, e in segs)).encode("utf-8")).hexdigest()[:16]
    work = os.path.join(MEDIA_DIR, f"_voice_{tag}_{h}")
    os.makedirs(work, exist_ok=True)
    try:
        parts = []
        for i, (text, gender, emo) in enumerate(segs):
            clip = os.path.join(work, f"line_{i}.mp3")
            if _synth_clip(text, gender, clip, emotion=emo):
                parts.append(clip)
        if not parts:
            return None, None
        # 句间插入短停顿
        sil = os.path.join(work, "sil.mp3")
        subprocess.run([ff, "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "0.35",
                        "-codec:a", "libmp3lame", sil], check=True, timeout=30,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        list_txt = os.path.join(work, "list.txt")
        with open(list_txt, "w", encoding="utf-8") as f:
            for idx, p in enumerate(parts):
                f.write(f"file '{p}'\n")
                if idx != len(parts) - 1:
                    f.write(f"file '{sil}'\n")
        out = os.path.join(MEDIA_DIR, f"{tag}_{h}.mp3")
        subprocess.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", list_txt,
                        "-codec:a", "libmp3lame", "-q:a", "4", out], check=True, timeout=90,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f"[Compositor] 多角色配音轨生成成功 ({len(parts)}句): {out}")
        return public_url(os.path.basename(out)), out
    except Exception as e:
        logger.warning(f"[Compositor] 多角色配音轨失败: {str(e)[:160]}")
        return None, None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _save_provider_audio(audio: bytes, tag: str, extension: str = "mp3") -> Tuple[Optional[str], Optional[str]]:
    """Atomically persist provider audio without ever logging credentials or request bodies."""
    if not audio:
        return None, None
    _ensure_dir()
    digest = hashlib.sha256(audio).hexdigest()[:20]
    filename = f"{tag}_{digest}.{extension}"
    path = os.path.join(MEDIA_DIR, filename)
    if not os.path.exists(path):
        temporary = path + ".tmp"
        with open(temporary, "wb") as stream:
            stream.write(audio)
        os.replace(temporary, path)
    return public_url(filename), path


def _elevenlabs_available() -> bool:
    """模型配置中心保存的 Key 与环境变量里的 Key 都算可用，与 ElevenLabsClient 的取值顺序一致"""
    return provider_key_available("elevenlabs", "audio", "ELEVENLABS_API_KEY")


_ACCOUNT_VOICES: dict[str, Tuple[str, str]] = {}
_speaker_voices: ContextVar[Mapping[str, str]] = ContextVar("speaker_voices", default={})


def _elevenlabs_voices() -> Tuple[str, str]:
    """(女声, 男声) 的 voice_id：.env 写了就用；没写就从这个账号自己的音色库里按性别各挑一个(只查一次)。

    以前没配 .env 时整条配音悄悄退回本地 TTS——模型配置中心明明配好了 ElevenLabs 也用不上。
    """
    female = (os.getenv("ELEVENLABS_VOICE_FEMALE_ID") or "").strip()
    male = (os.getenv("ELEVENLABS_VOICE_MALE_ID") or "").strip()
    if female and male:
        return female, male
    runtime = runtime_model_registry.first("elevenlabs", "audio")
    account = hashlib.sha256(((runtime.api_key if runtime else "") or os.getenv("ELEVENLABS_API_KEY") or "").encode()).hexdigest()[:12]
    if account not in _ACCOUNT_VOICES:
        from app.core.providers.elevenlabs import ElevenLabsClient

        client = ElevenLabsClient()
        try:
            voices = list((client.list_voices(page_size=100) or {}).get("voices") or [])
        finally:
            client.close()
        by_gender: dict[str, str] = {}
        for voice in voices:
            gender = str(((voice.get("labels") or {}) if isinstance(voice, dict) else {}).get("gender") or "").lower()
            if gender in {"female", "male"} and voice.get("voice_id"):
                by_gender.setdefault(gender, str(voice["voice_id"]))
        _ACCOUNT_VOICES[account] = (by_gender.get("female", ""), by_gender.get("male", ""))
        logger.info("[Compositor] ElevenLabs 未在 .env 指定音色，取账号音色库：女声 %s / 男声 %s",
                    _ACCOUNT_VOICES[account][0] or "无", _ACCOUNT_VOICES[account][1] or "无")
    found_female, found_male = _ACCOUNT_VOICES[account]
    return female or found_female or found_male, male or found_male or found_female


def effective_audio_model(tts_model: str) -> Tuple[str, str]:
    """(供应商, 型号)：模型配置中心启用了项目选的配音型号就用它；中心有音频模型、项目型号不在其中时
    用中心的第一个；中心没有音频模型时才按项目 / 配置文件里的型号。与文本、图像、视频同一口径。"""
    model = (tts_model or "").strip()
    runtime = runtime_model_registry.resolve(model, "audio") if model else None
    if runtime is not None:
        return runtime.provider, model
    first = runtime_model_registry.first_for_category("audio")
    if first is not None:
        if model:
            logger.warning("[Compositor] 配音模型 %s 未在模型配置中心启用，改用配置中心的 %s", model, first.model_ids[0])
        return first.provider, first.model_ids[0]
    return ("elevenlabs" if "eleven" in model.lower() else ""), model


@contextmanager
def bind_speaker_voices(voices: Mapping[str, str] | None) -> Iterator[None]:
    """The voices a project has cast, for the dubbing done inside this block (worker threads inherit the context)."""
    token = _speaker_voices.set(dict(voices or {}))
    try:
        yield
    finally:
        _speaker_voices.reset(token)


def synthesize_elevenlabs_dialogue_track(segments, tag: str = "eleven_voice") -> Tuple[Optional[str], Optional[str]]:
    """Generate an emotion-aware multi-speaker track through Text-to-Dialogue."""
    if not _elevenlabs_available():
        return None, None
    try:
        female_voice, male_voice = _elevenlabs_voices()
    except Exception as exc:
        logger.warning("[Compositor] ElevenLabs 音色库读取失败，本条配音改用本地 TTS：%s", type(exc).__name__)
        return None, None
    if not female_voice or not male_voice:
        logger.warning("[Compositor] ElevenLabs 账号里没有可用音色且 .env 未指定；本条配音改用本地 TTS")
        return None, None
    try:
        from app.core.providers.elevenlabs import DialogueLine, ElevenLabsClient

        try:
            voice_map = json.loads(os.getenv("ELEVENLABS_VOICE_MAP", "{}"))
            if not isinstance(voice_map, dict):
                voice_map = {}
        except json.JSONDecodeError:
            voice_map = {}
        cast = _speaker_voices.get()
        lines = []
        for segment in segments or []:
            text = re.sub(r"\s+", " ", (segment[0] or "")).strip()
            if not text:
                continue
            gender = segment[1] if len(segment) > 1 else "female"
            emotion = segment[2] if len(segment) > 2 else "neutral"
            speaker = segment[3] if len(segment) > 3 else ""
            lines.append(DialogueLine(
                voice_id=str(cast.get(speaker) or voice_map.get(speaker) or (male_voice if gender == "male" else female_voice)),
                text=text,
                emotion=emotion,
            ))
        if not lines:
            return None, None
        client = ElevenLabsClient()
        try:
            return _save_provider_audio(client.create_dialogue(lines), tag)
        finally:
            client.close()
    except Exception as exc:
        logger.warning(f"[Compositor] ElevenLabs dialogue unavailable; using fallback: {type(exc).__name__}")
        return None, None


def synthesize_preferred_dialogue_track(
    segments,
    *,
    tts_model: str,
    tag: str = "voice",
) -> Tuple[Optional[str], Optional[str]]:
    """配音按模型配置中心优先(见 :func:`effective_audio_model`)；ElevenLabs 出不了声时才落到本地渲染并记日志。"""
    provider, model = effective_audio_model(tts_model)
    if provider == "elevenlabs" or "eleven" in model.lower():
        url, path = synthesize_elevenlabs_dialogue_track(segments, tag=f"eleven_{tag}")
        if path:
            return url, path
    return synthesize_dialogue_track(segments, tag=tag)


def synthesize_elevenlabs_music(
    prompt: str,
    duration_seconds: float,
    tag: str = "eleven_bgm",
) -> Tuple[Optional[str], Optional[str]]:
    if not _elevenlabs_available():
        return None, None
    try:
        from app.core.providers.elevenlabs import ElevenLabsClient

        client = ElevenLabsClient()
        try:
            audio = client.compose_music(
                prompt,
                duration_seconds=max(3, min(600, duration_seconds)),
                instrumental=True,
            )
            return _save_provider_audio(audio, tag)
        finally:
            client.close()
    except Exception as exc:
        logger.warning(f"[Compositor] ElevenLabs music unavailable; using fallback: {type(exc).__name__}")
        return None, None


def synthesize_elevenlabs_sfx(
    prompt: str,
    duration_seconds: float = 12,
    tag: str = "eleven_sfx",
) -> Tuple[Optional[str], Optional[str]]:
    if not _elevenlabs_available():
        return None, None
    try:
        from app.core.providers.elevenlabs import ElevenLabsClient

        client = ElevenLabsClient()
        try:
            audio = client.sound_effect(prompt, duration_seconds=max(0.5, min(22, duration_seconds)))
            return _save_provider_audio(audio, tag)
        finally:
            client.close()
    except Exception as exc:
        logger.warning(f"[Compositor] ElevenLabs SFX unavailable: {type(exc).__name__}")
        return None, None


def _render_subtitle_png(text: str, out_path: str) -> bool:
    """用 PIL 把中文字幕渲染为 1080x1920 透明 PNG，并避开平台底部 UI。"""
    font_path = _font_path()
    if not font_path:
        return False
    try:
        from PIL import Image, ImageDraw, ImageFont
        font = ImageFont.truetype(font_path, 46)
        img = Image.new("RGBA", (OUT_W, OUT_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        def wrap(t: str) -> List[str]:
            lines, cur = [], ""
            for ch in t:
                if ch == "\n":
                    if cur:
                        lines.append(cur)
                    cur = ""
                    continue
                if (len(cur) >= 16 or d.textlength(cur + ch, font=font) > OUT_W - 120) and cur:
                    lines.append(cur)
                    cur = ch
                else:
                    cur += ch
            if cur:
                lines.append(cur)
            return lines[:3]  # 最多3行

        lines = wrap(text.strip())
        if not lines:
            img.save(out_path)
            return True
        lh = 60
        total = lh * len(lines)
        bottom_ui_safe = max(250, int(OUT_H * 0.13))
        y0 = OUT_H - bottom_ui_safe - total
        for i, ln in enumerate(lines):
            w = d.textlength(ln, font=font)
            x = (OUT_W - w) / 2
            y = y0 + i * lh
            d.rectangle([x - 16, y - 6, x + w + 16, y + 52], fill=(0, 0, 0, 150))
            for dx in (-2, 0, 2):
                for dy in (-2, 0, 2):
                    if dx or dy:
                        d.text((x + dx, y + dy), ln, font=font, fill=(0, 0, 0, 255))
            d.text((x, y), ln, font=font, fill=(255, 255, 255, 255))
        img.save(out_path)
        return True
    except Exception as e:
        logger.warning(f"[Compositor] 字幕渲染失败: {str(e)[:160]}")
        return False


def _title_tagline() -> str:
    configured = os.getenv("TITLE_CARD_TAGLINE")
    return DEFAULT_TITLE_TAGLINE if configured is None else configured.strip()


def _render_title_png(title: str, out_path: str, subtitle: Optional[str] = None) -> bool:
    """渲染片头标题卡 PNG (黑底，主标题大字居中 + 副标题)。"""
    subtitle = _title_tagline() if subtitle is None else subtitle
    font_path = _font_path()
    if not font_path:
        return False
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (OUT_W, OUT_H), (8, 8, 12))
        d = ImageDraw.Draw(img)
        big = ImageFont.truetype(font_path, 64)
        small = ImageFont.truetype(font_path, 34)

        def wrap(t, font, maxw):
            lines, cur = [], ""
            for ch in t:
                if d.textlength(cur + ch, font=font) > maxw and cur:
                    lines.append(cur)
                    cur = ch
                else:
                    cur += ch
            if cur:
                lines.append(cur)
            return lines[:3]

        title = (title or UNTITLED_FILM).strip()
        lines = wrap(title, big, OUT_W - 100)
        lh = 84
        total = lh * len(lines)
        y0 = (OUT_H - total) / 2 - 40
        # 顶部装饰线
        d.rectangle([OUT_W/2 - 60, y0 - 50, OUT_W/2 + 60, y0 - 46], fill=(220, 180, 90))
        for i, ln in enumerate(lines):
            w = d.textlength(ln, font=big)
            x = (OUT_W - w) / 2
            y = y0 + i * lh
            for dx in (-2, 2):
                for dy in (-2, 2):
                    d.text((x + dx, y + dy), ln, font=big, fill=(0, 0, 0))
            d.text((x, y), ln, font=big, fill=(245, 230, 200))
        # 副标题
        sw = d.textlength(subtitle, font=small)
        d.text(((OUT_W - sw) / 2, y0 + total + 30), subtitle, font=small, fill=(150, 150, 160))
        img.save(out_path)
        return True
    except Exception as e:
        logger.warning(f"[Compositor] 标题卡渲染失败: {str(e)[:160]}")
        return False


def _make_bgm(duration: float, out_wav: str) -> bool:
    """用 ffmpeg 正弦音源程序化生成一段电影感低音垫 BGM (A 小调和弦 + 渐入渐出)。"""
    ff = _ffmpeg()
    if not ff or duration <= 0:
        return False
    try:
        d = f"{duration:.2f}"
        # A2(110) + C3(130.81) + E3(164.81) 小调和弦垫，整体低音量、首尾淡入淡出
        cmd = [ff, "-y",
               "-f", "lavfi", "-i", f"sine=frequency=110:duration={d}",
               "-f", "lavfi", "-i", f"sine=frequency=130.81:duration={d}",
               "-f", "lavfi", "-i", f"sine=frequency=164.81:duration={d}",
               "-filter_complex",
               f"[0][1][2]amix=inputs=3,tremolo=f=0.18:d=0.4,afade=t=in:d=1.2,afade=t=out:st={max(0.0,duration-1.5):.2f}:d=1.5,volume=0.9[a]",
               "-map", "[a]", out_wav]
        subprocess.run(cmd, check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return os.path.exists(out_wav)
    except Exception as e:
        logger.warning(f"[Compositor] BGM 生成失败: {str(e)[:120]}")
        return False


def extract_last_frame_b64(video_url_or_path: str) -> Optional[str]:
    """
    抽取视频最后一帧并返回 base64 data URI (image/jpeg)，用于「尾帧链式衔接」：
    把上一镜尾帧作为下一镜的首帧喂给 Seedance，实现镜头无缝连贯 (火山云端可直接读 base64)。
    """
    return _extract_frame_b64(video_url_or_path, "last")


def extract_first_frame_b64(video_url_or_path: str) -> Optional[str]:
    """视频的第一帧，data URI；接缝质检拿它和前一段的末帧比。"""
    return _extract_frame_b64(video_url_or_path, "first")


def _extract_frame_b64(video_url_or_path: str, which: str) -> Optional[str]:
    ff = _ffmpeg()
    if not ff or not video_url_or_path:
        return None
    _ensure_dir()
    import base64 as _b64
    h = hashlib.md5(video_url_or_path.encode("utf-8")).hexdigest()[:16]
    work = os.path.join(MEDIA_DIR, f"_frame_{h}_{which}")
    os.makedirs(work, exist_ok=True)
    try:
        src = video_url_or_path
        if video_url_or_path.startswith("http"):
            src = os.path.join(work, "src.mp4")
            if not _download(video_url_or_path, src):
                return None
        frame = os.path.join(work, "last.jpg")
        # 真正的最后一帧：从结尾前 1 秒起逐帧覆盖写同一个文件，留下的就是末帧。
        # (`-sseof -0.2 -frames:v 1` 给的是结尾前 0.2 秒的那一帧，24fps 下差约 5 帧，接缝处动作会重一下。)
        # 缩到 1280 宽：首帧是要被照着画的，720 宽的参考会把接缝后的画面带糊。
        scale = ["-vf", "scale='min(1280,iw)':-2", "-q:v", "2"]
        if which == "last":
            arguments = ["-sseof", "-1", "-i", src, *scale, "-update", "1", frame]
        else:
            arguments = ["-i", src, *scale, "-frames:v", "1", frame]
        subprocess.run([ff, "-y", *arguments], check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not os.path.exists(frame):
            return None
        with open(frame, "rb") as f:
            b = _b64.b64encode(f.read()).decode("ascii")
        return f"data:image/jpeg;base64,{b}"
    except Exception as e:
        logger.warning(f"[Compositor] 尾帧抽取失败: {str(e)[:120]}")
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _probe_duration(path: str) -> Optional[float]:
    """探测媒体时长(秒)，失败返回 None"""
    ff = _ffprobe()
    if not ff:
        return None
    try:
        out = subprocess.run([ff, "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", path], capture_output=True, text=True, timeout=20)
        return float(out.stdout.strip())
    except Exception:
        return None


def _local_media_source(url: str) -> Optional[str]:
    """Resolve only this app's /media URLs, with traversal protection."""
    media_prefix = settings.MEDIA_PREFIX
    if not url or media_prefix not in url:
        return None
    parsed = urlparse(url)
    # 本机回环地址与配置的对外媒体域名都指向 MEDIA_DIR 里的同一批文件
    if parsed.hostname and parsed.hostname.lower() not in settings.own_media_hostnames(PUBLIC_BASE_URL):
        return None
    relative = parsed.path.split(media_prefix, 1)[-1].lstrip("/")
    root = os.path.realpath(MEDIA_DIR)
    candidate = os.path.realpath(os.path.join(root, relative))
    if candidate == root or not candidate.startswith(root + os.sep):
        return None
    return candidate


def _signed_url_expiry(url: str) -> Optional[float]:
    """签名链接的到期时刻(epoch 秒)：OSS 的 ``Expires``、S3 的 ``X-Amz-Date`` + ``X-Amz-Expires``；不是签名链接为 None。"""
    query = {key.lower(): values[0] for key, values in parse_qs(urlparse(url).query).items() if values}
    if query.get("expires", "").isdigit():
        return float(query["expires"])
    signed_at, lifetime = query.get("x-amz-date", ""), query.get("x-amz-expires", "")
    if lifetime.isdigit():
        try:
            return datetime.strptime(signed_at, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).timestamp() + int(lifetime)
        except ValueError:
            return None
    return None


def media_available(url: str) -> bool:
    """不发请求判断一段媒体还拿不拿得到：本机 /media 文件在不在，远端签名链接过没过期。

    视频服务商回传的成片链接大多是限时签名链接(MiniMax 的 OSS 链接一周左右失效)。
    """
    if not url:
        return False
    local = _local_media_source(url)
    if local:
        return os.path.isfile(local) and os.path.getsize(local) > 1024
    expiry = _signed_url_expiry(url)
    return expiry is None or expiry > time.time()


def _validate_public_media_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("remote media must use HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("credentials in media URLs are forbidden")
    for address in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM):
        if not settings.is_public_address(address[4][0]):
            raise ValueError("private or local media hosts are forbidden")


def _download(url: str, dst: str, timeout: int = 90, retries: int = 3) -> bool:
    # 本机自产片段(分镜拼接产物等 PUBLIC_BASE_URL 下的文件)直接从磁盘拷贝，
    # 不走 HTTP 回环：避免合成时依赖服务端口可达、省去一次自我下载往返，也更快更稳。
    local = _local_media_source(url)
    if local:
        if os.path.isfile(local) and os.path.getsize(local) > 1024:
            try:
                shutil.copyfile(local, dst)
                return True
            except Exception as e:
                logger.warning(f"[Compositor] 本地片段拷贝失败: {type(e).__name__}")
                return False
    maximum_bytes = int(os.getenv("MAX_REMOTE_VIDEO_BYTES", str(2 * 1024 * 1024 * 1024)))
    import time
    for attempt in range(retries):
        try:
            import requests
            current = url
            for _ in range(4):
                _validate_public_media_url(current)
                r = requests.get(
                    current, timeout=timeout, stream=True, allow_redirects=False,
                    proxies={"http": None, "https": None},
                )
                if r.status_code in {301, 302, 303, 307, 308}:
                    location = r.headers.get("location")
                    if not location:
                        raise ValueError("redirect missing location")
                    current = urljoin(current, location)
                    continue
                r.raise_for_status()
                total = 0
                with open(dst, "wb") as f:
                    for chunk in r.iter_content(1024 * 1024):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > maximum_bytes:
                            raise ValueError("remote video exceeds configured size limit")
                        f.write(chunk)
                return os.path.getsize(dst) > 1024
            raise ValueError("too many media redirects")
        except Exception as e:
            if os.path.exists(dst):
                os.remove(dst)
            logger.warning(f"[Compositor] 下载片段失败(第{attempt+1}次): {type(e).__name__}")
        if attempt < retries - 1:
            time.sleep(2)
    return False


def keep_clip(video_url: Optional[str], tag: str = "shotav") -> Optional[str]:
    """A provider's clip as a local file with its own sound: provider links expire. On failure, the link as it was."""
    if not video_url or not video_url.startswith("http") or _local_media_source(video_url):
        return video_url
    _ensure_dir()
    name = f"{tag}_{hashlib.md5(video_url.encode('utf-8')).hexdigest()[:16]}.mp4"
    if _download(video_url, os.path.join(MEDIA_DIR, name)):
        return public_url(name)
    return video_url


def _clip_sound(ff: str, raw: str, trim: Optional[Tuple[float, Optional[float]]], target: str) -> Optional[str]:
    """The part of a clip's own sound that stays after its trim; None when it has no sound to give."""
    start, end = trim if trim else (0.0, None)
    start = float(start or 0)
    length = ["-t", f"{max(0.0, float(end) - start):.3f}"] if end is not None else []
    cmd = [ff, "-y", "-ss", f"{start:.3f}", "-i", raw, *length, "-vn", "-c:a", "aac", target]
    try:
        subprocess.run(cmd, check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as error:  # noqa: BLE001 - a clip with no audio stream is an ordinary case
        logger.info(f"[Compositor] 片段没有可用的原声: {type(error).__name__}")
        return None
    return target if os.path.exists(target) and os.path.getsize(target) > 256 else None


def attach_audio_to_clip(video_url: str, voice_path: Optional[str] = None,
                         bgm: bool = True, tag: str = "shotav") -> Optional[str]:
    """
    给单条镜头视频挂上音轨（台词配音 + 轻量氛围 BGM 垫），返回带声音的本地视频对外 URL。
    用于步骤5逐镜预览：让分镜视频自带音轨可听、播放器静音键可点开切换。
    - 视频流直接 copy 不重编码 (快)，仅追加 aac 音轨。
    - 无配音也无 BGM、或任一环节失败时，原样返回传入的 video_url (绝不中断主流程)。
    """
    ff = _ffmpeg()
    if not ff or not video_url or not video_url.startswith("http"):
        return video_url
    _ensure_dir()
    h = hashlib.md5(f"{video_url}|{voice_path}|{bgm}".encode("utf-8")).hexdigest()[:16]
    work = os.path.join(MEDIA_DIR, f"_av_{tag}_{h}")
    os.makedirs(work, exist_ok=True)
    try:
        raw = os.path.join(work, "raw.mp4")
        if not _download(video_url, raw):
            return video_url
        dur = _probe_duration(raw) or 5.0

        cmd = [ff, "-y", "-i", raw]
        filters = []
        labels = []
        idx = 1
        if voice_path and os.path.exists(voice_path):
            cmd += ["-i", voice_path]
            filters.append(f"[{idx}:a]volume=1.7[v{idx}]")
            labels.append(f"[v{idx}]")
            idx += 1
        bgm_wav = os.path.join(work, "bgm.wav")
        if bgm and _make_bgm(dur, bgm_wav):
            cmd += ["-i", bgm_wav]
            filters.append(f"[{idx}:a]volume=0.16[bgm]")
            labels.append("[bgm]")
            idx += 1

        if not labels:
            return video_url
        if len(labels) == 1:
            filters[-1] = filters[-1].rsplit("[", 1)[0] + "[aout]"
        else:
            filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0[aout]")

        out = os.path.join(MEDIA_DIR, f"{tag}_{h}.mp4")
        cmd += ["-filter_complex", ";".join(filters), "-map", "0:v:0", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac", "-t", f"{dur:.3f}", out]
        subprocess.run(cmd, check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(out) and os.path.getsize(out) > 1024:
            logger.info(f"[Compositor] 镜头音轨挂载成功 (配音={'有' if voice_path else '无'}, BGM={'有' if bgm else '无'}): {out}")
            return public_url(os.path.basename(out))
        return video_url
    except Exception as e:
        logger.warning(f"[Compositor] 镜头音轨挂载失败，回退无声片段: {str(e)[:140]}")
        return video_url
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _join_video_segments(
    segment_paths: List[str],
    output_path: str,
    *,
    transition_specs: Optional[List[dict]] = None,
) -> List[float]:
    """Join normalized clips with explicit overlap transitions.

    Returns the effective overlap before each segment after the first. A tiny
    overlap is used for match/hard cuts to keep one filter graph and stable A/V
    timing while avoiding an obvious dissolve.
    """
    ff = _ffmpeg()
    if not ff or not segment_paths:
        raise ValueError("ffmpeg and at least one segment are required")
    if len(segment_paths) == 1:
        shutil.copyfile(segment_paths[0], output_path)
        return []
    specs = list(transition_specs or [])
    while len(specs) < len(segment_paths) - 1:
        specs.append({"type": "crossfade", "duration": 0.22})
    specs = specs[: len(segment_paths) - 1]
    type_map = {
        "hard_cut": ("fade", 0.04),
        "match_cut": ("fade", 0.08),
        "crossfade": ("fade", None),
        "dip_to_black": ("fadeblack", None),
        "neutral_bridge": ("fadeblack", None),
    }
    durations = [_probe_duration(path) or 1.0 for path in segment_paths]
    cmd = [ff, "-y"]
    for path in segment_paths:
        cmd.extend(["-i", path])
    filters = [f"[{index}:v]settb=AVTB,setpts=PTS-STARTPTS[v{index}]" for index in range(len(segment_paths))]
    effective: List[float] = []
    running_duration = durations[0]
    previous_label = "v0"
    for index, spec in enumerate(specs, start=1):
        transition_type = str(spec.get("type") or "crossfade")
        ff_transition, forced_duration = type_map.get(transition_type, ("fade", None))
        requested = float(spec.get("duration") or 0.22)
        overlap = forced_duration if forced_duration is not None else requested
        overlap = max(0.04, min(overlap, durations[index] * 0.45, running_duration * 0.45, 1.0))
        offset = max(0.0, running_duration - overlap)
        output_label = f"x{index}"
        filters.append(
            f"[{previous_label}][v{index}]xfade=transition={ff_transition}:duration={overlap:.3f}:offset={offset:.3f}[{output_label}]"
        )
        running_duration += durations[index] - overlap
        effective.append(round(overlap, 3))
        previous_label = output_label
    cmd.extend([
        "-filter_complex", ";".join(filters),
        "-map", f"[{previous_label}]", "-an", "-r", str(OUT_FPS),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", output_path,
    ])
    subprocess.run(cmd, check=True, timeout=240, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return effective


def _append_master_mix_filters(
    filters: List[str],
    voice_labels: List[str],
    bgm_label: Optional[str],
    sfx_label: Optional[str],
    voices_carry_ambience: bool = False,
) -> str:
    """Append dialogue ducking and EBU-style delivery mastering to a filter graph.

    A clip's own sound never drops to silence between lines: with ``voices_carry_ambience`` the music gives way to
    loud moments only, or it would stay ducked out of hearing for the whole film.
    """
    mix_inputs: List[str] = []
    dialogue_base: Optional[str] = None
    if voice_labels:
        if len(voice_labels) == 1:
            filters.append(f"{voice_labels[0]}anull[dialoguebase]")
        else:
            filters.append(
                f"{''.join(voice_labels)}amix=inputs={len(voice_labels)}:duration=longest:normalize=0[dialoguebase]"
            )
        dialogue_base = "[dialoguebase]"

    if bgm_label and dialogue_base:
        filters.append(f"{dialogue_base}asplit=2[dialogue][duckkey]")
        filters.append(
            f"{bgm_label}[duckkey]sidechaincompress=threshold={0.25 if voices_carry_ambience else 0.04}"
            f":ratio={3 if voices_carry_ambience else 8}:attack=20:release=350:makeup=1[bgmduck]"
        )
        mix_inputs.extend(["[dialogue]", "[bgmduck]"])
    else:
        if dialogue_base:
            mix_inputs.append(dialogue_base)
        if bgm_label:
            mix_inputs.append(bgm_label)
    if sfx_label:
        mix_inputs.append(sfx_label)
    if not mix_inputs:
        raise ValueError("master mix requires at least one audio input")
    if len(mix_inputs) == 1:
        filters.append(f"{mix_inputs[0]}anull[premaster]")
    else:
        filters.append(
            f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=longest:normalize=0[premaster]"
        )
    filters.append("[premaster]loudnorm=I=-16:TP=-1:LRA=11,alimiter=limit=0.891251[aout]")
    return "[aout]"


# J-cut / L-cut：声音和画面错开切。配音是对着片段开头摆的，只挪声音口型就歪了，所以动的是画面：
# L 把上一镜的画面提前切走，台词继续；J 让下一镜的画面晚点出现(剪掉片头)，台词在它之前响起。
SOUND_JOIN_SECONDS = {"j_cut": 0.4, "l_cut": 0.5}
MIN_SOUND_JOIN_SECONDS = 0.1
MAX_SOUND_JOIN_SECONDS = 1.5
#: 错开之后一段画面至少留这么长。
MIN_CLIP_AFTER_JOIN_S = 1.0
#: 为了让台词越过切点，上一镜的尾巴最多剪掉这么多；再多就是在删戏了。
MAX_TAIL_CUT_S = 1.5
MAX_TAIL_CUT_FRACTION = 0.3


def sound_join_seconds(join: Any) -> float:
    """这一刀声音错开多久：写了就用写的(限在范围内)，没写用默认。"""
    wanted = join.get("seconds") if isinstance(join, dict) else None
    fallback = SOUND_JOIN_SECONDS.get(str((join or {}).get("join") or ""), 0.0)
    return max(MIN_SOUND_JOIN_SECONDS, min(float(wanted or fallback), MAX_SOUND_JOIN_SECONDS))


def plan_sound_joins(
    clip_seconds: List[float],
    voice_seconds: List[Optional[float]],
    joins: List[Optional[dict]],
    transitions: Optional[List[dict]] = None,
) -> Tuple[List[float], List[float], List[float], List[dict]]:
    """``(片头剪掉, 片尾剪掉, 配音提前, 报告)``，都按镜头一一对应。``joins[k]`` 是切入第 k+1 镜的那一刀。

    做不到的不硬做：报告里写明为什么，这一刀按普通的声画同切合成。
    """
    count = len(clip_seconds)
    heads, tails, leads = [0.0] * count, [0.0] * count, [0.0] * count
    report: List[dict] = []
    for index in range(1, count):
        join = joins[index - 1] if index - 1 < len(joins) else None
        kind = str((join or {}).get("join") or "")
        if kind not in SOUND_JOIN_SECONDS:
            continue
        seconds = sound_join_seconds(join)
        before, after = index - 1, index
        room_before = clip_seconds[before] - heads[before] - tails[before]
        room_after = clip_seconds[after] - heads[after] - tails[after]
        spoken_before = voice_seconds[before] - leads[before] if voice_seconds[before] is not None else None
        spec = transitions[index - 1] if transitions and index - 1 < len(transitions) else {}
        reason = ""
        cut = 0.0
        if str((spec or {}).get("type") or "") in {"dip_to_black", "neutral_bridge"}:
            reason = "转黑是一次停顿，声音不错开"
        elif kind == "j_cut":
            if voice_seconds[after] is None:
                reason = "下一镜没有配音，没有声音可以提前"
            elif room_after - seconds < MIN_CLIP_AFTER_JOIN_S:
                reason = "下一镜太短，剪掉片头就不够看了"
            elif spoken_before is not None and spoken_before > room_before - seconds:
                reason = "上一镜的台词还没说完，提前会和它压在一起"
            else:
                heads[after] += seconds
                leads[after] = seconds
        elif spoken_before is None:
            reason = "上一镜没有配音，没有声音可以留下"
        elif voice_seconds[after] is not None:
            reason = "下一镜也有台词，留下的声音会压住它"
        else:
            cut = max(0.0, room_before - (spoken_before - seconds))
            if cut > min(MAX_TAIL_CUT_S, room_before * MAX_TAIL_CUT_FRACTION) or room_before - cut < MIN_CLIP_AFTER_JOIN_S:
                reason = f"这句话在切点前 {max(0.0, room_before - spoken_before):.1f} 秒就说完了，要留声音得剪掉太多画面"
            else:
                tails[before] += cut
        report.append({"index": index, "join": kind, "seconds": seconds, "applied": not reason, "reason": reason})
    return heads, tails, leads, report


def _kept_seconds(trim: Optional[Tuple[float, Optional[float]]], raw_seconds: float) -> float:
    start, end = trim if trim else (0.0, None)
    return (float(end) if end is not None else raw_seconds) - float(start or 0)


def _trim_after_join(trim: Optional[Tuple[float, Optional[float]]], head: float, tail: float, raw_seconds: float) -> Tuple[float, Optional[float]]:
    start, end = trim if trim else (0.0, None)
    start = float(start or 0) + head
    if tail > 0:
        end = (float(end) if end is not None else raw_seconds) - tail
    return start, end


def compose_film(shot_video_urls: List[str], subtitles: List[str], audio_path: Optional[str],
                 tag: str = "film", title: Optional[str] = None, bgm: bool = True,
                 shot_voices: List = None, bgm_path: Optional[str] = None,
                 sfx_path: Optional[str] = None,
                 transition_plans: Optional[List[dict]] = None,
                 trims: Optional[List[Tuple[float, Optional[float]]]] = None,
                 bgm_volume: float = 0.16,
                 sound_joins: Optional[List[Optional[dict]]] = None,
                 sound_report: Optional[List[dict]] = None,
                 native_audio: Optional[List[bool]] = None) -> Optional[str]:
    """
    将多镜头视频合成为一条带片头标题卡、字幕、配音与 BGM 的竖屏成片/单集。
    - shot_video_urls: 各镜头视频直链 (http mp4)
    - subtitles: 与镜头一一对应的字幕文本 (可含空串；空串=该镜无对话不显示字幕)
    - audio_path: 整条配音本地文件路径 (单条全局配音；与 shot_voices 二选一)
    - shot_voices: 与镜头一一对应的配音本地路径列表 (按镜头时间轴对齐，实现配音/字幕/画面同步)
    - title: 片头标题卡文字 (None 则不加片头)
    - bgm: 是否叠加程序化生成的 BGM 低音垫
    - trims: 与镜头一一对应的 (入点秒, 出点秒或 None)，来自剪辑时间线；None 表示整段
    - bgm_volume: 配乐音量 (0-1)，闪避仍按台词侧链压缩
    - sound_joins: 切入第 2、3…镜的声画错开 ({join: j_cut|l_cut, seconds})；只作用于逐镜配音
    - sound_report: 传一个列表进来，合成时写进每一刀错开了没有、没错开的原因
    - native_audio: 与镜头一一对应；为真的镜头用片段自己的声音(按修剪后的入出点取)，不错开也不配音
    返回成片对外 URL；任一关键环节失败返回 None。
    """
    ff = _ffmpeg()
    clips = [u for u in (shot_video_urls or []) if u and isinstance(u, str) and u.startswith("http")]
    if not ff or not clips:
        logger.warning("[Compositor] 成片合成不可用 (缺 ffmpeg 或无有效视频片段)")
        return None
    _ensure_dir()
    h = hashlib.md5(("|".join(clips) + "|" + "|".join(subtitles or []) + f"|{native_audio}|{title}|{bgm}|{bool(shot_voices)}|{bgm_path}|{sfx_path}|{trims}|{bgm_volume}|{sound_joins}").encode("utf-8")).hexdigest()[:16]
    work = os.path.join(MEDIA_DIR, f"_work_{tag}_{h}")
    os.makedirs(work, exist_ok=True)
    try:
        scale_pad = f"scale={OUT_W}:-2,pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
        seg_files = []
        # 时间轴：[(段落时长, 该段配音路径或None)]，用于把逐镜配音对齐到时间轴
        timeline = []

        # 片头标题卡 (静音视频片段，置于最前)
        title_dur = 0.0
        if title:
            tpng = os.path.join(work, "title.png")
            if _render_title_png(title, tpng):
                tseg = os.path.join(work, "seg_title.mp4")
                try:
                    subprocess.run([ff, "-y", "-loop", "1", "-i", tpng, "-t", f"{TITLE_DUR}",
                                    "-vf", f"scale={OUT_W}:{OUT_H},setsar=1", "-r", str(OUT_FPS),
                                    "-c:v", "libx264", "-pix_fmt", "yuv420p", tseg],
                                   check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    seg_files.append(tseg)
                    title_dur = TITLE_DUR
                    timeline.append((TITLE_DUR, None, 0.0))
                except Exception as e:
                    logger.warning(f"[Compositor] 标题卡片段生成失败: {str(e)[:120]}")

        raws = [os.path.join(work, f"raw_{i}.mp4") for i in range(len(clips))]
        for i, url in enumerate(clips):
            if not _download(url, raws[i]):
                # 少一段就不是这一集：跳过它会剪出一部短了一截、字幕和配音错位的成片，还被当成合成成功。
                logger.error(f"[Compositor] 第{i + 1}/{len(clips)}段片段拿不到，不合成残缺成片")
                return None

        native_tracks: dict[int, str] = {}

        def voice_of(position: int) -> Optional[str]:
            if position in native_tracks:
                return native_tracks[position]
            if shot_voices and position < len(shot_voices) and shot_voices[position] and os.path.exists(shot_voices[position]):
                return shot_voices[position]
            return None

        # 声画错开要先知道每段画面和配音多长，才定得下剪多少。
        effective_trims = list(trims or [])
        voice_leads = [0.0] * len(clips)
        if sound_joins and any(sound_joins):
            raw_seconds = [_probe_duration(path) or 0.0 for path in raws]
            kept = [_kept_seconds(effective_trims[i] if i < len(effective_trims) else None, raw_seconds[i]) for i in range(len(clips))]
            heads, tails, voice_leads, joined = plan_sound_joins(
                kept, [_probe_duration(voice_of(i)) if voice_of(i) else None for i in range(len(clips))], list(sound_joins), transition_plans,
            )
            effective_trims = [
                _trim_after_join(effective_trims[i] if i < len(effective_trims) else None, heads[i], tails[i], raw_seconds[i])
                for i in range(len(clips))
            ]
            if sound_report is not None:
                sound_report.extend(joined)

        # 片段自己的声音按修剪后的入出点取：和画面同一段，不会错开口型。放在声画错开之后，这些镜头不参与错开。
        for i in range(len(clips)):
            if native_audio and i < len(native_audio) and native_audio[i]:
                trim = effective_trims[i] if i < len(effective_trims) else None
                track = _clip_sound(ff, raws[i], trim, os.path.join(work, f"native_{i}.m4a"))
                if track:
                    native_tracks[i] = track

        # 各镜头：竖屏化 + 烧字幕(仅对话镜头)
        for i, url in enumerate(clips):
            raw = raws[i]
            seg = os.path.join(work, f"seg_{i}.mp4")
            sub_text = subtitles[i] if subtitles and i < len(subtitles) else ""
            sub_text = re.sub(r"\s+", " ", (sub_text or "")).strip()
            png = os.path.join(work, f"sub_{i}.png")
            has_sub = bool(sub_text) and _render_subtitle_png(sub_text, png)
            # The timeline's trim: decode from the in point and stop at the out point.
            trim_args: List[str] = []
            if i < len(effective_trims) and effective_trims[i]:
                start, end = effective_trims[i]
                if start and float(start) > 0:
                    trim_args += ["-ss", f"{float(start):.3f}"]
                if end is not None:
                    trim_args += ["-to", f"{float(end):.3f}"]
            try:
                if has_sub:
                    cmd = [ff, "-y", *trim_args, "-i", raw, "-i", png,
                           "-filter_complex", f"[0:v]{scale_pad}[bg];[bg][1:v]overlay=0:0",
                           "-r", str(OUT_FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", seg]
                else:
                    cmd = [ff, "-y", *trim_args, "-i", raw, "-vf", scale_pad,
                           "-r", str(OUT_FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", seg]
                subprocess.run(cmd, check=True, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                seg_files.append(seg)
                seg_dur = _probe_duration(seg) or 5.0
                timeline.append((seg_dur, voice_of(i), voice_leads[i]))
            except Exception as e:
                logger.error(f"[Compositor] 片段{i}处理失败，不合成残缺成片: {str(e)[:120]}")
                return None

        if not seg_files:
            logger.warning("[Compositor] 无可用片段，成片合成失败")
            return None

        # 相邻镜头使用动作匹配/短叠化/转黑等显式转场，避免硬拼接。
        specs = list(transition_plans or [])
        if title_dur:
            specs.insert(0, {"type": "crossfade", "duration": 0.35})
        concat = os.path.join(work, "concat.mp4")
        transition_overlaps = _join_video_segments(seg_files, concat, transition_specs=specs)

        vdur = _probe_duration(concat) or 0.0
        final = os.path.join(MEDIA_DIR, f"{tag}_{h}.mp4")

        bgm_wav = os.path.join(work, "bgm.wav")
        if bgm_path and os.path.exists(bgm_path):
            bgm_wav = bgm_path
            has_bgm = True
        else:
            has_bgm = bgm and vdur > 0 and _make_bgm(vdur, bgm_wav)

        # 逐镜配音按时间轴对齐 (优先)；否则用整条全局配音
        per_shot_voices = [(t, v) for (t, v, _) in timeline if v]
        cmd = [ff, "-y", "-i", concat]
        filters = []
        voice_labels = []
        idx = 1
        if per_shot_voices:
            # 计算每段在时间轴上的起点，把该段配音 adelay 到对应时刻
            cum = 0.0
            offsets = []
            for timeline_index, (dur, voice, lead) in enumerate(timeline):
                if timeline_index > 0 and timeline_index - 1 < len(transition_overlaps):
                    cum = max(0.0, cum - transition_overlaps[timeline_index - 1])
                if voice:
                    offsets.append((voice, max(0.0, cum - lead)))
                cum += dur
            for voice, start in offsets:
                cmd += ["-i", voice]
                delay_ms = int(start * 1000)
                filters.append(f"[{idx}:a]adelay={delay_ms}|{delay_ms},volume=1.7[v{idx}]")
                voice_labels.append(f"[v{idx}]")
                idx += 1
        elif audio_path and os.path.exists(audio_path):
            cmd += ["-i", audio_path]
            delay_ms = int(title_dur * 1000)
            filters.append(f"[{idx}:a]adelay={delay_ms}|{delay_ms},volume=1.7[v{idx}]")
            voice_labels.append(f"[v{idx}]")
            idx += 1

        bgm_label = None
        if has_bgm:
            cmd += ["-stream_loop", "-1", "-i", bgm_wav]
            filters.append(f"[{idx}:a]volume={max(0.0, min(float(bgm_volume), 1.0)):.2f}[bgm]")
            bgm_label = "[bgm]"
            idx += 1

        sfx_label = None
        if sfx_path and os.path.exists(sfx_path):
            cmd += ["-stream_loop", "-1", "-i", sfx_path]
            filters.append(f"[{idx}:a]volume=0.22[sfx]")
            sfx_label = "[sfx]"
            idx += 1

        all_labels = voice_labels + ([bgm_label] if bgm_label else []) + ([sfx_label] if sfx_label else [])
        if all_labels:
            out_label = _append_master_mix_filters(filters, voice_labels, bgm_label, sfx_label, voices_carry_ambience=bool(native_tracks))
            fc = ";".join(filters)
            cmd += ["-filter_complex", fc, "-map", "0:v:0", "-map", out_label,
                    "-c:v", "copy", "-c:a", "aac", "-t", f"{vdur:.3f}", final]
            subprocess.run(cmd, check=True, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            shutil.copyfile(concat, final)

        logger.info(f"[Compositor] 成片合成成功 (片头={'有' if title_dur else '无'}, BGM={'有' if has_bgm else '无'}, 逐镜配音={len(per_shot_voices)}句): {final}")
        return public_url(os.path.basename(final))
    except Exception as e:
        logger.warning(f"[Compositor] 成片合成异常: {str(e)[:160]}")
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)
