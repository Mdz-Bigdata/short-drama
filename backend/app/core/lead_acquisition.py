# -*- coding: utf-8 -*-
"""自动获客：把已发布作品下的评论和找上门的私信变成能跟进的线索。

一条线索从一条真实评论或私信开始：判定意图（合作、求全集、催更、提问、差评），按同一平台的
同一个人合并去重，给出公开回复和私信草稿，联系过就记下，约了时间就排一条跟进。

取数和发送只走平台的官方接口。YouTube 有公开的 Data API：评论与播放数据用 API key 自动读，
回复用频道自己授权的 OAuth 发。抖音、快手、小红书等没有给个人账号开放评论接口，评论由人粘贴
导入，回复由人复制到平台里发。这里不模拟登录、不绕过风控、不批量私信陌生人。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from app.core import publish_targets


@dataclass(frozen=True)
class Channel:
    id: str
    name: str
    color: str
    language: str
    auto_read: bool = False     # 评论与数据能通过官方接口自动读取
    auto_reply: bool = False    # 回复能通过官方接口发出


_EXTRA_CHANNELS = (
    Channel("kuaishou", "快手", "#ff6a00", "zh"),
    Channel("xiaohongshu", "小红书", "#ff2442", "zh"),
    Channel("bilibili", "B站", "#00a1d6", "zh"),
    Channel("wechat_channels", "视频号", "#07c160", "zh"),
    Channel("tiktok", "TikTok", "#161823", "en"),
)
CHANNELS: tuple[Channel, ...] = (
    *(Channel(item.id, item.name, item.color, item.language, item.id == "youtube", item.id == "youtube")
      for item in publish_targets.PLATFORMS),
    *_EXTRA_CHANNELS,
)
CHANNEL_IDS = tuple(item.id for item in CHANNELS)
_CHANNEL = {item.id: item for item in CHANNELS}


def channel(channel_id: str) -> Channel:
    return _CHANNEL[channel_id]


# ---------------------------------------------------------------- 意图判定

INTENTS: dict[str, tuple[str, int]] = {
    "business": ("合作意向", 90),
    "watch_full": ("求全集", 75),
    "want_more": ("催更", 60),
    "question": ("剧情提问", 45),
    "complaint": ("差评投诉", 40),
    "praise": ("夸赞", 20),
    "neutral": ("其他", 5),
    "spam": ("广告引流", 0),
}
# 值得有人回应的意图；夸赞、其他和广告只计数。
LEAD_INTENTS = ("business", "watch_full", "want_more", "question", "complaint")
LEAD_STATUSES = ("new", "contacted", "replied", "won", "ignored")
FOLLOW_UP_STATUSES = ("pending", "sent_once", "completed", "cancelled")

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("spam", re.compile(r"代刷|兼职|日结|刷单|点我头像|看我主页|进群领|https?://|www\.|check my (profile|channel)|subscribe to my|onlyfans", re.I)),
    ("business", re.compile(r"合作|商务|投放|版权|代理|分销|采购|发行|授权|报价|对接|招商|买断|联系方式|\b(licens|distribut|partner|collab|business|sponsor|inquir)", re.I)),
    ("watch_full", re.compile(r"全集|完整版|在哪看|哪里看|哪看|去哪看|哪能看|链接|资源|求片|片名|剧名|叫什么|全剧|\b(full (episode|series|movie|drama)|where (can i|to|do i) watch|what('?s| is) the (name|title)|link)", re.I)),
    ("want_more", re.compile(r"更新|催更|下一集|后续|第二季|续集|还有吗|什么时候更|快更|等更|\b(next (episode|part)|part 2|season 2|more episodes|when('?s| is) the next|can'?t wait|continue)", re.I)),
    ("complaint", re.compile(r"难看|垃圾|骗|退款|差评|无聊|尴尬|ai味|假得|看不下去|劝退|\b(boring|scam|refund|trash|cringe|terrible|awful|worst)", re.I)),
    ("question", re.compile(r"[?？]|为什么|怎么|是谁|是不是|会不会|\b(who|why|how|what|is (he|she|it))\b", re.I)),
    ("praise", re.compile(r"好看|好棒|绝了|上头|太好|爱了|太爽|好燃|好帅|好美|神剧|\b(great|love|amazing|awesome|beautiful|best|good)\b", re.I)),
)


def classify(text: str) -> tuple[str, int, str]:
    """The intent a comment shows, its base score and the words that showed it."""
    body = " ".join(str(text or "").split())
    for intent, pattern in _RULES:
        found = pattern.search(body)
        if found:
            return intent, INTENTS[intent][1], found.group(0)
    return "neutral", INTENTS["neutral"][1], ""


def is_lead(intent: str) -> bool:
    return intent in LEAD_INTENTS


def language_of(text: str) -> str:
    return "zh" if re.search(r"[一-鿿]", str(text or "")) else "en"


# ---------------------------------------------------------------- 评论

def comment_id(platform: str, work_id: str, author: str, text: str) -> str:
    digest = hashlib.sha1(f"{platform}|{work_id}|{author}|{text}".encode("utf-8")).hexdigest()
    return f"c{digest[:16]}"


def author_key(platform: str, author_id: str, author_name: str, fallback: str) -> str:
    """One person on one platform; a comment with no author never merges with anyone else's."""
    who = str(author_id or "").strip() or str(author_name or "").strip()
    return f"{platform}:{who}" if who else f"{platform}:anon:{fallback}"


_COLON_LINE = re.compile(r"^(.{1,30}?)\s*[：:]\s*(.+)$")


def parse_import(text: str, limit: int = 500) -> list[dict[str, str]]:
    """Comments pasted from a platform: a JSON list, tab-separated rows or「昵称：评论」lines."""
    raw = str(text or "").strip()
    if not raw:
        return []
    rows: list[dict[str, str]] = []
    if raw[0] in "[{":
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if isinstance(data, dict):
            data = data.get("comments") or data.get("items") or [data]
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                body = str(item.get("text") or item.get("content") or item.get("comment") or "").strip()
                if body:
                    rows.append({
                        "author": str(item.get("author") or item.get("nickname") or item.get("user") or item.get("name") or "").strip(),
                        "author_id": str(item.get("author_id") or item.get("uid") or item.get("user_id") or "").strip(),
                        "text": body,
                        "published_at": str(item.get("published_at") or item.get("time") or item.get("date") or "").strip(),
                        "id": str(item.get("id") or item.get("cid") or "").strip(),
                    })
            return rows[:limit]
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if "\t" in line:
            parts = [part.strip() for part in line.split("\t")]
            author, body = (parts[0], parts[1]) if len(parts) > 1 else ("", parts[0])
            when = parts[2] if len(parts) > 2 else ""
        else:
            match = _COLON_LINE.match(line)
            author, body, when = (match.group(1).strip(), match.group(2).strip(), "") if match else ("", line, "")
        if body:
            rows.append({"author": author, "author_id": "", "text": body[:2000], "published_at": when, "id": ""})
    return rows[:limit]


# ---------------------------------------------------------------- 回复草稿

def where_to_watch(platform_ids: Iterable[str], language: str) -> str:
    names = [(_CHANNEL[item].name if item in _CHANNEL else item) for item in dict.fromkeys(platform_ids)]
    if not names:
        return "我们的主页" if language == "zh" else "our channel"
    return "、".join(names) if language == "zh" else ", ".join(names)


def template_reply(intent: str, language: str, *, title: str, where: str) -> str:
    """A safe public reply when the model gives none: no contact details, no links, no promises."""
    if language == "zh":
        return {
            "business": f"感谢关注《{title}》！合作与版权事宜欢迎私信留言，我们会尽快对接。",
            "watch_full": f"谢谢喜欢！《{title}》全集在{where}，搜剧名就能看到～",
            "want_more": "收到催更！新一集上线会第一时间更新在主页，关注不迷路～",
            "question": "好问题！答案就藏在后面的剧情里，接着往下看～",
            "complaint": "谢谢你直说，我们会认真改。哪里不满意欢迎私信细说。",
            "praise": "谢谢喜欢，会继续努力的！",
        }.get(intent, "谢谢观看！")
    return {
        "business": f"Thanks for your interest in {title}! Please send us a message about partnership or licensing and we'll get back to you.",
        "watch_full": f"Glad you like it! The full series of {title} is on {where} — search the title to watch.",
        "want_more": "Noted! New episodes go up on our channel first — follow so you don't miss them.",
        "question": "Good question — the answer is coming up in the next episodes!",
        "complaint": "Thanks for being honest — we'll work on it. Feel free to message us the details.",
        "praise": "Thank you so much for watching!",
    }.get(intent, "Thanks for watching!")


def template_dm(intent: str, language: str, *, title: str, where: str) -> str:
    if intent not in ("business", "watch_full", "want_more"):
        return ""
    if language == "zh":
        return {
            "business": f"您好，看到您在《{title}》下关于合作的留言。方便说说您那边的合作方向（发行、投放还是版权）吗？我们按方向准备资料给您。",
            "watch_full": f"你好，看到你在问《{title}》的全集～ 目前在{where}可以看完整版，搜剧名就能找到。",
            "want_more": f"你好，谢谢你追《{title}》！下一集上线时我们会在主页第一时间更新。",
        }[intent]
    return {
        "business": f"Hi, thanks for your comment on {title} about working together. Could you share what you have in mind — distribution, promotion or licensing? We'll send the right materials.",
        "watch_full": f"Hi! You asked where to watch {title} — the full series is on {where}; search the title to find it.",
        "want_more": f"Hi, thanks for following {title}! New episodes go up on our channel first.",
    }[intent]


_RULES_PROMPT = (
    "公开回复：用评论者的语言；中文不超过 60 字，英文不超过 200 个字符；不留微信号、手机号、二维码或外链，"
    "需要进一步沟通就请对方私信；不承诺免费、不夸大、不用「最」「第一」等绝对化用语；只说剧里真实存在的内容。"
    "私信草稿：只给合作意向、求全集、催更三类写，先说明是看到对方哪条留言，一条消息只推进一个动作；其他意图私信留空字符串。"
)


def lead_prompt(comments: Sequence[Mapping[str, Any]], *, title: str, logline: str, where: str) -> tuple[str, str]:
    """One model call that judges a batch of comments and drafts the replies."""
    intents = "、".join(f"{key}（{label}）" for key, (label, _) in INTENTS.items())
    system = (
        "你是短剧账号的运营，负责从评论区找出值得回应的观众和合作方，并写回复草稿。"
        f"意图只能取：{intents}。score 是 0-100 的跟进优先级：合作最高，求全集次之，广告为 0。"
        + _RULES_PROMPT
        + '只输出一个 JSON 对象：{"items": [{"id": str, "intent": str, "score": int, "reply": str, "dm": str}]}，不要输出其它文字。'
    )
    lines = "\n".join(
        f'- id={item["id"]}｜平台={_CHANNEL.get(str(item.get("platform")), Channel("", str(item.get("platform")), "", "zh")).name}'
        f'｜昵称={item.get("author_name") or "匿名"}｜评论={str(item.get("text") or "")[:400]}'
        for item in comments
    )
    user = f"剧名：{title}\n剧情梗概：{logline[:1500]}\n可以看全集的平台：{where}\n\n评论：\n{lines}"
    return system, user


def _json_object(text: str) -> Any:
    match = re.search(r"\{.*\}", str(text or ""), re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except ValueError:
        return None


def parse_lead_answer(text: str, ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """The model's judgement per comment id; unknown ids, intents and empty items are dropped."""
    data = _json_object(text)
    items = data.get("items") if isinstance(data, dict) else None
    wanted = set(ids)
    result: dict[str, dict[str, Any]] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or str(item.get("id")) not in wanted or item.get("intent") not in INTENTS:
            continue
        try:
            score = max(0, min(100, int(item.get("score", INTENTS[item["intent"]][1]))))
        except (TypeError, ValueError):
            score = INTENTS[item["intent"]][1]
        result[str(item["id"])] = {
            "intent": item["intent"],
            "score": score,
            "reply": " ".join(str(item.get("reply") or "").split())[:500],
            "dm": str(item.get("dm") or "").strip()[:800],
        }
    return result


def inbox_prompt(message: str, *, title: str, logline: str, where: str, history: Sequence[str] = ()) -> tuple[str, str]:
    """The pre-sales reply to someone who wrote to the account."""
    system = (
        "你是短剧账号的客服，回复主动找来的观众或合作方。回复按「承接 → 结论 → 关键信息 → 推进」组织，"
        "能三到六句说清就不写长；一次只推进一个最自然的下一步，不连环追问；用对方的语言。"
        + _RULES_PROMPT.replace("公开回复：", "回复：")
        + "如果对方表示要过段时间再说（明天、下周、发工资后等），follow_up 填对方说的时间原话，否则填空字符串。"
        + f'intent 只能取：{"、".join(INTENTS)}。只输出一个 JSON 对象：{{"intent": str, "reply": str, "follow_up": str}}。'
    )
    past = "\n".join(f"- {line}" for line in history[-6:]) or "（无）"
    user = f"剧名：{title}\n剧情梗概：{logline[:1500]}\n可以看全集的平台：{where}\n此前往来：\n{past}\n\n对方的新消息：{message[:2000]}"
    return system, user


def parse_inbox_answer(text: str) -> dict[str, str]:
    data = _json_object(text)
    if not isinstance(data, dict) or not str(data.get("reply") or "").strip():
        return {}
    intent = data.get("intent") if data.get("intent") in INTENTS else ""
    return {"intent": intent, "reply": str(data["reply"]).strip()[:1500], "follow_up": str(data.get("follow_up") or "").strip()[:60]}


# ---------------------------------------------------------------- 跟进时间

def timezone_name() -> str:
    return os.getenv("ACQUISITION_TZ", "Asia/Shanghai")


def local_now() -> datetime:
    return datetime.now(ZoneInfo(timezone_name()))


_DELAY = re.compile(
    r"明天|明早|明晚|后天|下周|下星期|下礼拜|工资|月底|过两天|过几天|几天后|晚点|稍后|回头|改天|下午|晚上|今晚|\d{1,2}\s*[月/]\s*\d{1,2}|\d{1,2}\s*[号日]|"
    r"\b(tomorrow|next week|later|tonight|this (afternoon|evening)|in \d+ days?|payday|end of (the )?month)\b",
    re.I,
)


def mentions_delay(text: str) -> bool:
    return bool(_DELAY.search(str(text or "")))


def _at(day: datetime, hour: int, minute: int = 0) -> datetime:
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def follow_up_time(phrase: str, now: datetime) -> datetime | None:
    """When to follow up, from what the person said: 明天 → next day 10:00, 下周 → in 7 days, …

    An explicit date or time wins; an unparseable phrase gives None (the caller asks for a time).
    """
    text = " ".join(str(phrase or "").split())
    if not text:
        return None
    lowered = text.lower()
    iso = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?", text)
    if iso:
        year, month, day, hour, minute = iso.groups()
        try:
            return now.replace(year=int(year), month=int(month), day=int(day), hour=int(hour or 10),
                               minute=int(minute or 0), second=0, microsecond=0)
        except ValueError:
            return None
    clock = re.search(r"(上午|早上|中午|下午|晚上)?\s*(\d{1,2})\s*(?:点|:|：|时)\s*(半|\d{1,2})?", text)
    hour = minute = None
    if clock:
        hour = int(clock.group(2))
        minute = 30 if clock.group(3) == "半" else int(clock.group(3) or 0)
        if clock.group(1) in ("下午", "晚上") and hour < 12:
            hour += 12
        if hour > 23 or minute > 59:
            hour = minute = None
    dated = re.search(r"(\d{1,2})\s*[月/]\s*(\d{1,2})\s*[日号]?", text) or re.search(r"(?<![\d月/])(\d{1,2})\s*[号日]", text)
    if dated:
        month, day = (int(dated.group(1)), int(dated.group(2))) if dated.lastindex == 2 else (now.month, int(dated.group(1)))
        try:
            target = now.replace(month=month, day=day)
        except ValueError:
            return None
        if target.date() < now.date():
            try:
                target = target.replace(year=now.year + 1) if dated.lastindex == 2 else (target + timedelta(days=32)).replace(day=day)
            except ValueError:
                return None
        return _at(target, hour if hour is not None else 10, minute or 0)

    def later_today(start: int, cutoff: int, otherwise: datetime) -> datetime:
        return _at(now, start) if now.hour < cutoff else otherwise

    day_offset = None
    if "后天" in text or "day after tomorrow" in lowered:
        day_offset = 2
    elif re.search(r"明天|明早|明晚|tomorrow", text, re.I):
        day_offset = 1
    elif re.search(r"下周|下星期|下礼拜|next week", text, re.I):
        day_offset = 7
    elif re.search(r"工资|月底|payday|end of (the )?month", text, re.I):
        day_offset = 5
    elif re.search(r"过两天|过几天|几天后|改天", text):
        day_offset = 3
    else:
        days = re.search(r"in (\d+) days?", lowered) or re.search(r"(\d+)\s*天后", text)
        if days:
            day_offset = int(days.group(1))
    if day_offset is not None:
        default_hour = 19 if re.search(r"晚上|明晚|evening|night", text, re.I) else 14 if re.search(r"下午|afternoon", text, re.I) else 10
        return _at(now + timedelta(days=day_offset), hour if hour is not None else default_hour, minute or 0)
    if hour is not None:
        target = _at(now, hour, minute or 0)
        return target if target > now else target + timedelta(days=1)
    if re.search(r"下午|this afternoon", text, re.I):
        return later_today(14, 13, _at(now + timedelta(days=1), 14))
    if re.search(r"晚上|今晚|tonight|this evening", text, re.I):
        return later_today(19, 18, _at(now + timedelta(days=1), 19))
    if re.search(r"晚点|稍后|回头|later", text, re.I):
        return later_today(14, 13, _at(now + timedelta(days=1), 10))
    return None


# ---------------------------------------------------------------- 复盘

def review(state: Mapping[str, Any], now: datetime, *, can_read_youtube: bool) -> dict[str, Any]:
    """Today's picture: the funnel, what each platform brought, and what to do next."""
    works = [item for item in state.get("works") or [] if isinstance(item, dict)]
    comments = [item for item in state.get("comments") or [] if isinstance(item, dict)]
    leads = [item for item in state.get("leads") or [] if isinstance(item, dict)]
    follow_ups = [item for item in state.get("follow_ups") or [] if isinstance(item, dict)]
    statuses = {status: sum(1 for lead in leads if lead.get("status") == status) for status in LEAD_STATUSES}
    reached = statuses["contacted"] + statuses["replied"] + statuses["won"]
    due = [item for item in follow_ups if item.get("status") in ("pending", "sent_once") and _parse(item.get("due_at")) and _parse(item.get("due_at")) <= now]
    since = now - timedelta(hours=24)
    platforms: list[dict[str, Any]] = []
    for platform_id in dict.fromkeys(item.get("platform") for item in works):
        mine = [item for item in works if item.get("platform") == platform_id]
        platforms.append({
            "platform": platform_id,
            "name": _CHANNEL[platform_id].name if platform_id in _CHANNEL else platform_id,
            "works": len(mine),
            "views": sum(int((item.get("metrics") or {}).get("views") or 0) for item in mine),
            "likes": sum(int((item.get("metrics") or {}).get("likes") or 0) for item in mine),
            "comments": sum(1 for item in comments if item.get("platform") == platform_id),
            "leads": sum(1 for item in leads if item.get("platform") == platform_id),
        })
    open_leads = [lead for lead in leads if lead.get("status") == "new"]
    suggestions: list[str] = []
    business = sum(1 for lead in open_leads if lead.get("intent") == "business")
    watch = sum(1 for lead in open_leads if lead.get("intent") == "watch_full")
    unsure = sum(1 for lead in leads if lead.get("send_state") in ("unknown", "sending"))
    if business:
        suggestions.append(f"有 {business} 条合作意向还没联系，先处理它们")
    if watch:
        suggestions.append(f"{watch} 位观众在问全集去哪看：回复里写清平台和剧名")
    if due:
        suggestions.append(f"{len(due)} 条跟进已到时间")
    if unsure:
        suggestions.append(f"{unsure} 条 YouTube 回复发送结果不明：先到 YouTube 核对，再标记")
    if any(item.get("platform") == "youtube" for item in works) and not can_read_youtube:
        suggestions.append("配置 YOUTUBE_API_KEY 后，YouTube 的评论和播放数据会自动拉取")
    silent = [item for item in works if not _CHANNEL.get(str(item.get("platform")), Channel("", "", "", "")).auto_read
              and not any(c.get("work_id") == item.get("id") for c in comments)]
    if silent:
        suggestions.append(f"{len(silent)} 个作品还没有导入评论：从平台复制评论粘贴进来")
    if not works:
        suggestions.append("先登记已发布作品的链接，获客从这些作品的评论开始")
    return {
        "generated_at": now.isoformat(),
        "funnel": {"comments": len(comments), "leads": len(leads), "reached": reached,
                   "replied": statuses["replied"] + statuses["won"], "won": statuses["won"]},
        "statuses": statuses,
        "intents": {intent: sum(1 for lead in leads if lead.get("intent") == intent) for intent in LEAD_INTENTS},
        "last_24h": {
            "comments": sum(1 for item in comments if (_parse(item.get("fetched_at")) or now - timedelta(days=2)) >= since),
            "leads": sum(1 for lead in leads if (_parse(lead.get("created_at")) or now - timedelta(days=2)) >= since),
        },
        "due_follow_ups": len(due),
        "platforms": platforms,
        "suggestions": suggestions,
    }


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- YouTube Data API（官方接口）

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube_video_id(url: str) -> str | None:
    value = str(url or "").strip()
    if _VIDEO_ID.match(value):
        return value
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if host.endswith("youtu.be"):
        candidate = parsed.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com"):
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
        if not candidate:
            parts = [part for part in parsed.path.split("/") if part]
            candidate = parts[1] if len(parts) > 1 and parts[0] in ("shorts", "embed", "live", "v") else ""
    else:
        return None
    return candidate if _VIDEO_ID.match(candidate or "") else None


class YouTubeError(RuntimeError):
    """A YouTube call that failed. ``definite`` is False when a write may or may not have landed."""

    def __init__(self, message: str, *, definite: bool = True):
        super().__init__(message)
        self.definite = definite


Http = Callable[..., Any]


def _default_http(method: str, url: str, **kwargs: Any) -> Any:
    import httpx

    return httpx.request(method, url, **kwargs)


class YouTubeClient:
    """Reads public comments and statistics with an API key; replies as the channel that granted OAuth."""

    def __init__(self, *, api_key: str = "", client_id: str = "", client_secret: str = "", refresh_token: str = "",
                 http: Http | None = None, timeout: float = 20.0):
        self.api_key = api_key
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.http = http or _default_http
        self.timeout = timeout
        self._access_token = ""

    @classmethod
    def from_env(cls) -> "YouTubeClient":
        return cls(
            api_key=os.getenv("YOUTUBE_API_KEY", "").strip(),
            client_id=os.getenv("YOUTUBE_CLIENT_ID", "").strip(),
            client_secret=os.getenv("YOUTUBE_CLIENT_SECRET", "").strip(),
            refresh_token=os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip(),
        )

    @property
    def can_reply(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)

    @property
    def can_read(self) -> bool:
        return bool(self.api_key) or self.can_reply

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        try:
            response = self.http("POST", GOOGLE_TOKEN_URL, data={
                "client_id": self.client_id, "client_secret": self.client_secret,
                "refresh_token": self.refresh_token, "grant_type": "refresh_token",
            }, timeout=self.timeout)
        except Exception as error:  # noqa: BLE001 - network errors become one readable failure
            raise YouTubeError(f"YouTube 授权刷新失败：{type(error).__name__}") from error
        if response.status_code != 200:
            raise YouTubeError(f"YouTube 授权刷新失败（HTTP {response.status_code}）：检查 YOUTUBE_REFRESH_TOKEN 是否仍有效")
        self._access_token = str(response.json().get("access_token") or "")
        if not self._access_token:
            raise YouTubeError("YouTube 授权刷新没有返回 access_token")
        return self._access_token

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        headers = {}
        if self.api_key:
            params = {**params, "key": self.api_key}
        else:
            headers["Authorization"] = f"Bearer {self._token()}"
        try:
            response = self.http("GET", f"{YOUTUBE_API}/{path}", params=params, headers=headers, timeout=self.timeout)
        except Exception as error:  # noqa: BLE001
            raise YouTubeError(f"YouTube 读取失败：{type(error).__name__}") from error
        if response.status_code != 200:
            raise YouTubeError(_youtube_reason(response, "读取"))
        return response.json()

    def statistics(self, video_ids: Sequence[str]) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for start in range(0, len(video_ids), 50):
            data = self._get("videos", {"part": "statistics", "id": ",".join(video_ids[start:start + 50])})
            for item in data.get("items") or []:
                stats = item.get("statistics") or {}
                result[str(item.get("id"))] = {
                    "views": int(stats.get("viewCount") or 0),
                    "likes": int(stats.get("likeCount") or 0),
                    "comments": int(stats.get("commentCount") or 0),
                }
        return result

    def comments(self, video_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """The newest top-level comments, each with the id a reply attaches to."""
        found: list[dict[str, Any]] = []
        token = ""
        while len(found) < limit:
            params: dict[str, Any] = {"part": "snippet", "videoId": video_id, "maxResults": min(100, limit - len(found)),
                                      "order": "time", "textFormat": "plainText"}
            if token:
                params["pageToken"] = token
            data = self._get("commentThreads", params)
            for thread in data.get("items") or []:
                top = ((thread.get("snippet") or {}).get("topLevelComment") or {})
                snippet = top.get("snippet") or {}
                found.append({
                    "id": str(top.get("id") or thread.get("id") or ""),
                    "author": str(snippet.get("authorDisplayName") or ""),
                    "author_id": str((snippet.get("authorChannelId") or {}).get("value") or ""),
                    "text": str(snippet.get("textOriginal") or snippet.get("textDisplay") or ""),
                    "published_at": str(snippet.get("publishedAt") or ""),
                    "likes": int(snippet.get("likeCount") or 0),
                })
            token = str(data.get("nextPageToken") or "")
            if not token:
                break
        return found

    def reply(self, parent_id: str, text: str) -> str:
        """Post a reply under one comment; returns the new comment's id."""
        token = self._token()
        try:
            response = self.http("POST", f"{YOUTUBE_API}/comments", params={"part": "snippet"},
                                 headers={"Authorization": f"Bearer {token}"},
                                 json={"snippet": {"parentId": parent_id, "textOriginal": text}}, timeout=self.timeout)
        except Exception as error:  # noqa: BLE001 - the request may have reached YouTube
            raise YouTubeError(f"发送时连接中断（{type(error).__name__}），回复可能已经发出", definite=False) from error
        if response.status_code >= 500:
            raise YouTubeError(_youtube_reason(response, "发送") + "，回复可能已经发出", definite=False)
        if response.status_code not in (200, 201):
            raise YouTubeError(_youtube_reason(response, "发送"))
        return str(response.json().get("id") or "")


def _youtube_reason(response: Any, action: str) -> str:
    reason = ""
    try:
        errors = ((response.json().get("error") or {}).get("errors") or [{}])
        reason = str(errors[0].get("reason") or "")
    except Exception:  # noqa: BLE001 - a non-JSON error body still gets a status
        pass
    known = {
        "commentsDisabled": "这个视频关闭了评论",
        "quotaExceeded": "YouTube API 今日配额已用完",
        "forbidden": "没有权限：确认授权的频道与账号",
        "videoNotFound": "找不到这个视频",
        "insufficientPermissions": "授权缺少 youtube.force-ssl 权限",
    }
    return f"YouTube {action}失败：{known.get(reason, reason or f'HTTP {response.status_code}')}"


__all__ = [
    "CHANNELS", "CHANNEL_IDS", "Channel", "FOLLOW_UP_STATUSES", "INTENTS", "LEAD_INTENTS", "LEAD_STATUSES",
    "YouTubeClient", "YouTubeError", "author_key", "channel", "classify", "comment_id", "follow_up_time",
    "inbox_prompt", "is_lead", "language_of", "lead_prompt", "local_now", "mentions_delay", "parse_import",
    "parse_inbox_answer", "parse_lead_answer", "review", "template_dm", "template_reply", "timezone_name",
    "where_to_watch", "youtube_video_id",
]
