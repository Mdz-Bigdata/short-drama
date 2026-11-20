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
from app.core import prompt_data


_WORDING_FILE = "lead_acquisition"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/lead_acquisition.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


@dataclass(frozen=True)
class Channel:
    id: str
    name: str
    color: str
    language: str
    auto_read: bool = False     # 评论与数据能通过官方接口自动读取
    auto_reply: bool = False    # 回复能通过官方接口发出


_EXTRA_CHANNELS = (
    Channel("kuaishou", _text_of("module.extra_channels"), "#ff6a00", "zh"),
    Channel("xiaohongshu", _text_of("module.extra_channels.2"), "#ff2442", "zh"),
    Channel("bilibili", _text_of("module.extra_channels.3"), "#00a1d6", "zh"),
    Channel("wechat_channels", _text_of("module.extra_channels.4"), "#07c160", "zh"),
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
    "business": (_text_of("module.intents.business"), 90),
    "watch_full": (_text_of("module.intents.watch_full"), 75),
    "want_more": (_text_of("module.intents.want_more"), 60),
    "question": (_text_of("module.intents.question"), 45),
    "complaint": (_text_of("module.intents.complaint"), 40),
    "praise": (_text_of("module.intents.praise"), 20),
    "neutral": (_text_of("module.intents.neutral"), 5),
    "spam": (_text_of("module.intents.spam"), 0),
}
# 值得有人回应的意图；夸赞、其他和广告只计数。
LEAD_INTENTS = ("business", "watch_full", "want_more", "question", "complaint")
LEAD_STATUSES = ("new", "contacted", "replied", "won", "ignored")
FOLLOW_UP_STATUSES = ("pending", "sent_once", "completed", "cancelled")

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("spam", re.compile(_text_of("module.rules"), re.I)),
    ("business", re.compile(_text_of("module.rules.2"), re.I)),
    ("watch_full", re.compile(_text_of("module.rules.3"), re.I)),
    ("want_more", re.compile(_text_of("module.rules.4"), re.I)),
    ("complaint", re.compile(_text_of("module.rules.5"), re.I)),
    ("question", re.compile(_text_of("module.rules.6"), re.I)),
    ("praise", re.compile(_text_of("module.rules.7"), re.I)),
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
    return "zh" if re.search(_text_of("language_of.text"), str(text or "")) else "en"


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
        return _text_of("where_to_watch.text") if language == "zh" else "our channel"
    return "、".join(names) if language == "zh" else ", ".join(names)


def template_reply(intent: str, language: str, *, title: str, where: str) -> str:
    """A safe public reply when the model gives none: no contact details, no links, no promises."""
    if language == "zh":
        return {
            "business": _text_of("template_reply.business").format(title),
            "watch_full": _text_of("template_reply.watch_full").format(title, where),
            "want_more": _text_of("template_reply.want_more"),
            "question": _text_of("template_reply.question"),
            "complaint": _text_of("template_reply.complaint"),
            "praise": _text_of("template_reply.praise"),
        }.get(intent, _text_of("template_reply.text"))
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
            "business": _text_of("template_dm.business").format(title),
            "watch_full": _text_of("template_dm.watch_full").format(title, where),
            "want_more": _text_of("template_dm.want_more").format(title),
        }[intent]
    return {
        "business": f"Hi, thanks for your comment on {title} about working together. Could you share what you have in mind — distribution, promotion or licensing? We'll send the right materials.",
        "watch_full": f"Hi! You asked where to watch {title} — the full series is on {where}; search the title to find it.",
        "want_more": f"Hi, thanks for following {title}! New episodes go up on our channel first.",
    }[intent]


_RULES_PROMPT = (
    _text_of("module.rules_prompt")
)


def lead_prompt(comments: Sequence[Mapping[str, Any]], *, title: str, logline: str, where: str) -> tuple[str, str]:
    """One model call that judges a batch of comments and drafts the replies."""
    intents = "、".join(f"{key}（{label}）" for key, (label, _) in INTENTS.items())
    system = (
        _text_of("lead_prompt.system").format(intents)
        + _RULES_PROMPT
        + _text_of("lead_prompt.system.2")
    )
    lines = "\n".join(
        _text_of("lead_prompt.lines").format(item["id"], _CHANNEL.get(str(item.get("platform")), Channel("", str(item.get("platform")), "", "zh")).name, item.get("author_name") or "匿名", str(item.get("text") or "")[:400])
        for item in comments
    )
    user = _text_of("lead_prompt.user").format(title, logline[:1500], where, lines)
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
        _text_of("inbox_prompt.system")
        + _RULES_PROMPT.replace(_text_of("inbox_prompt.system.2"), _text_of("inbox_prompt.system.3"))
        + _text_of("inbox_prompt.system.4")
        + _text_of("inbox_prompt.system.5").format("、".join(INTENTS))
    )
    past = "\n".join(f"- {line}" for line in history[-6:]) or _text_of("inbox_prompt.past")
    user = _text_of("inbox_prompt.user").format(title, logline[:1500], where, past, message[:2000])
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
    _text_of("module.delay"),
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
    clock = re.search(_text_of("follow_up_time.clock"), text)
    hour = minute = None
    if clock:
        hour = int(clock.group(2))
        minute = 30 if clock.group(3) == _text_of("follow_up_time.minute") else int(clock.group(3) or 0)
        if clock.group(1) in _words_of("follow_up_time.text") and hour < 12:
            hour += 12
        if hour > 23 or minute > 59:
            hour = minute = None
    dated = re.search(_text_of("follow_up_time.dated"), text) or re.search(_text_of("follow_up_time.dated.2"), text)
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
    if _text_of("follow_up_time.text.2") in text or "day after tomorrow" in lowered:
        day_offset = 2
    elif re.search(_text_of("follow_up_time.text.3"), text, re.I):
        day_offset = 1
    elif re.search(_text_of("follow_up_time.text.4"), text, re.I):
        day_offset = 7
    elif re.search(_text_of("follow_up_time.text.5"), text, re.I):
        day_offset = 5
    elif re.search(_text_of("follow_up_time.text.6"), text):
        day_offset = 3
    else:
        days = re.search(r"in (\d+) days?", lowered) or re.search(_text_of("follow_up_time.days"), text)
        if days:
            day_offset = int(days.group(1))
    if day_offset is not None:
        default_hour = 19 if re.search(_text_of("follow_up_time.default_hour"), text, re.I) else 14 if re.search(_text_of("follow_up_time.default_hour.2"), text, re.I) else 10
        return _at(now + timedelta(days=day_offset), hour if hour is not None else default_hour, minute or 0)
    if hour is not None:
        target = _at(now, hour, minute or 0)
        return target if target > now else target + timedelta(days=1)
    if re.search(_text_of("follow_up_time.text.7"), text, re.I):
        return later_today(14, 13, _at(now + timedelta(days=1), 14))
    if re.search(_text_of("follow_up_time.text.8"), text, re.I):
        return later_today(19, 18, _at(now + timedelta(days=1), 19))
    if re.search(_text_of("follow_up_time.text.9"), text, re.I):
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
        suggestions.append(_text_of("review.text").format(business))
    if watch:
        suggestions.append(_text_of("review.text.2").format(watch))
    if due:
        suggestions.append(_text_of("review.text.3").format(len(due)))
    if unsure:
        suggestions.append(_text_of("review.text.4").format(unsure))
    if any(item.get("platform") == "youtube" for item in works) and not can_read_youtube:
        suggestions.append(_text_of("review.text.5"))
    silent = [item for item in works if not _CHANNEL.get(str(item.get("platform")), Channel("", "", "", "")).auto_read
              and not any(c.get("work_id") == item.get("id") for c in comments)]
    if silent:
        suggestions.append(_text_of("review.text.6").format(len(silent)))
    if not works:
        suggestions.append(_text_of("review.text.7"))
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
            raise YouTubeError(_text_of("_token.text").format(type(error).__name__)) from error
        if response.status_code != 200:
            raise YouTubeError(_text_of("_token.text.2").format(response.status_code))
        self._access_token = str(response.json().get("access_token") or "")
        if not self._access_token:
            raise YouTubeError(_text_of("_token.text.3"))
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
            raise YouTubeError(_text_of("_get.text").format(type(error).__name__)) from error
        if response.status_code != 200:
            raise YouTubeError(_youtube_reason(response, _text_of("_get.text.2")))
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
            raise YouTubeError(_text_of("reply.text").format(type(error).__name__), definite=False) from error
        if response.status_code >= 500:
            raise YouTubeError(_youtube_reason(response, _text_of("reply.text.2")) + _text_of("reply.text.3"), definite=False)
        if response.status_code not in (200, 201):
            raise YouTubeError(_youtube_reason(response, _text_of("reply.text.4")))
        return str(response.json().get("id") or "")


def _youtube_reason(response: Any, action: str) -> str:
    reason = ""
    try:
        errors = ((response.json().get("error") or {}).get("errors") or [{}])
        reason = str(errors[0].get("reason") or "")
    except Exception:  # noqa: BLE001 - a non-JSON error body still gets a status
        pass
    known = {
        "commentsDisabled": _text_of("_youtube_reason.known.commentsDisabled"),
        "quotaExceeded": _text_of("_youtube_reason.known.quotaExceeded"),
        "forbidden": _text_of("_youtube_reason.known.forbidden"),
        "videoNotFound": _text_of("_youtube_reason.known.videoNotFound"),
        "insufficientPermissions": _text_of("_youtube_reason.known.insufficientPermissions"),
    }
    return _text_of("_youtube_reason.text").format(action, known.get(reason, reason or f'HTTP {response.status_code}'))


__all__ = [
    "CHANNELS", "CHANNEL_IDS", "Channel", "FOLLOW_UP_STATUSES", "INTENTS", "LEAD_INTENTS", "LEAD_STATUSES",
    "YouTubeClient", "YouTubeError", "author_key", "channel", "classify", "comment_id", "follow_up_time",
    "inbox_prompt", "is_lead", "language_of", "lead_prompt", "local_now", "mentions_delay", "parse_import",
    "parse_inbox_answer", "parse_lead_answer", "review", "template_dm", "template_reply", "timezone_name",
    "where_to_watch", "youtube_video_id",
]
