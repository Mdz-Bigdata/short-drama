# -*- coding: utf-8 -*-
"""宣发 · 自动获客：已发布作品 → 评论 → 线索 → 联系 → 跟进 → 复盘。

全部状态放在任务的 ``assets["8_acquisition"]``，只通过 ``mutate_task`` 改（它在 task_repo 里登记为
sink-owned，阶段线程保存旧快照时不会把它冲掉）。模型调用和 YouTube 请求都在锁外做，写回时按 id 合并。
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from app.core import lead_acquisition as la
from app.core.providers.defaults import GATEWAY_DEFAULT_MODELS

logger = logging.getLogger("app.service.acquisition")

KEY = "8_acquisition"
MAX_COMMENTS = 3000
MAX_INBOX = 50
MODEL_BATCH = 60
_EVIDENCE_PER_LEAD = 5


def _empty() -> Dict[str, Any]:
    return {"works": [], "comments": [], "leads": [], "follow_ups": [], "inbox": [],
            "settings": {"auto_sync": True}, "synced_at": None, "sync_errors": []}


def _state(task: Dict[str, Any]) -> Dict[str, Any]:
    state = (task.get("assets") or {}).get(KEY)
    if not isinstance(state, dict):
        return _empty()
    merged = _empty()
    merged.update(state)
    return merged


class AcquisitionService:
    def __init__(self, repo: Any, gateway: Any, *, youtube: Callable[[], la.YouTubeClient] = la.YouTubeClient.from_env,
                 clock: Callable[[], datetime] = la.local_now):
        self.repo = repo
        self.gateway = gateway
        self.youtube = youtube
        self.clock = clock

    # ------------------------------------------------------------ 读

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.repo.get_task(task_id)
        if not task:
            return None
        return self._view(task)

    def _view(self, task: Dict[str, Any]) -> Dict[str, Any]:
        state = _state(task)
        client = self.youtube()
        leads = sorted(state["leads"], key=lambda lead: (lead.get("status") != "new", -int(lead.get("score") or 0), str(lead.get("created_at") or "")))
        follow_ups = sorted(state["follow_ups"], key=lambda item: (item.get("status") not in ("pending", "sent_once"), str(item.get("due_at") or "")))
        return {
            "channels": [{"id": item.id, "name": item.name, "color": item.color, "language": item.language,
                          "autoRead": item.auto_read, "autoReply": item.auto_reply} for item in la.CHANNELS],
            "intents": {key: label for key, (label, _) in la.INTENTS.items()},
            "capabilities": {"youtubeRead": client.can_read, "youtubeReply": client.can_reply, "timezone": la.timezone_name()},
            "settings": state["settings"],
            "syncedAt": state["synced_at"],
            "syncErrors": state["sync_errors"],
            "works": [{**work, "comments": sum(1 for item in state["comments"] if item.get("work_id") == work.get("id"))} for work in state["works"]],
            "leads": leads,
            "followUps": follow_ups,
            "inbox": list(reversed(state["inbox"][-20:])),
            "review": la.review(state, self.clock(), can_read_youtube=client.can_read),
        }

    # ------------------------------------------------------------ 公共小件

    def _mutate(self, task_id: str, change: Callable[[Dict[str, Any]], Any]) -> Optional[Dict[str, Any]]:
        """Apply ``change`` to the stored acquisition state.

        Returns ``{"result": <change's return>}``, or None when the task does not exist.
        """
        holder: Dict[str, Any] = {}

        def mutation(task: Dict[str, Any]) -> bool:
            state = _state(task)
            holder["result"] = change(state)
            task.setdefault("assets", {})[KEY] = state
            return True

        if self.repo.mutate_task(task_id, mutation) is None:
            return None
        return holder

    def _now(self) -> str:
        return self.clock().isoformat()

    @staticmethod
    def _drama(task: Dict[str, Any]) -> tuple[str, str]:
        assets = task.get("assets") or {}
        config = task.get("config") or {}
        pr_title = re.search(r"大字标题：([^\n]+)", str((assets.get("8") or {}).get("pr_content") or task.get("pr_content") or ""))
        title = (pr_title.group(1).strip() if pr_title else "") or str(config.get("script_name") or config.get("title_suggestion") or "本剧")
        return title, str(assets.get("1") or "")

    @staticmethod
    def _where(task: Dict[str, Any], language: str) -> str:
        state = _state(task)
        platforms = [work.get("platform") for work in state["works"]]
        if not platforms:
            platforms = ((task.get("assets") or {}).get("8_publish") or {}).get("platforms") or []
        wanted = [item for item in platforms if item in la.CHANNEL_IDS and la.channel(item).language == language] or platforms
        return la.where_to_watch(wanted, language)

    def _model(self, task: Dict[str, Any]) -> str:
        return (task.get("config") or {}).get("llm_model") or GATEWAY_DEFAULT_MODELS["deepseek"]

    @staticmethod
    def _find(items: List[Dict[str, Any]], item_id: str, what: str) -> Dict[str, Any]:
        for item in items:
            if item.get("id") == item_id:
                return item
        raise LookupError(f"{what}不存在")

    # ------------------------------------------------------------ 已发布作品

    def add_work(self, task_id: str, platform: str, url: str, *, episode: Optional[int] = None, title: str = "") -> Optional[Dict[str, Any]]:
        if platform not in la.CHANNEL_IDS:
            raise ValueError("不支持的平台")
        url = str(url or "").strip()
        if not re.match(r"^https?://", url):
            raise ValueError("请填作品的完整链接（http 或 https 开头）")
        video_id = la.youtube_video_id(url) if platform == "youtube" else None
        if platform == "youtube" and not video_id:
            raise ValueError("这不是 YouTube 视频链接")
        work = {
            "id": "w" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:10],
            "platform": platform, "url": url, "episode": episode, "title": str(title or "").strip()[:80],
            "video_id": video_id, "metrics": {}, "metrics_at": None, "added_at": self._now(),
        }

        def change(state: Dict[str, Any]) -> None:
            if any(item.get("url") == url for item in state["works"]):
                raise ValueError("这个链接已经登记过")
            state["works"].append(work)

        return self._after(task_id, change)

    def remove_work(self, task_id: str, work_id: str) -> Optional[Dict[str, Any]]:
        def change(state: Dict[str, Any]) -> None:
            self._find(state["works"], work_id, "作品")
            state["works"] = [item for item in state["works"] if item.get("id") != work_id]
            # 人（线索）留着：联系记录和跟进不能因为删了一个作品链接就丢。
            state["comments"] = [item for item in state["comments"] if item.get("work_id") != work_id]

        return self._after(task_id, change)

    def update_metrics(self, task_id: str, work_id: str, metrics: Dict[str, int]) -> Optional[Dict[str, Any]]:
        clean = {key: max(0, int(value)) for key, value in (metrics or {}).items()
                 if key in ("views", "likes", "comments", "shares", "favorites") and value is not None}

        def change(state: Dict[str, Any]) -> None:
            work = self._find(state["works"], work_id, "作品")
            work["metrics"] = {**(work.get("metrics") or {}), **clean}
            work["metrics_at"] = self._now()
            work["metrics_source"] = "manual"

        return self._after(task_id, change)

    def _after(self, task_id: str, change: Callable[[Dict[str, Any]], Any]) -> Optional[Dict[str, Any]]:
        """Run a change and return the fresh view (None when the task is gone)."""
        if self._mutate(task_id, change) is None:
            return None
        return self.get(task_id)

    def set_auto_sync(self, task_id: str, enabled: bool) -> Optional[Dict[str, Any]]:
        return self._after(task_id, lambda state: state["settings"].update(auto_sync=bool(enabled)))

    # ------------------------------------------------------------ 评论 → 线索

    def import_comments(self, task_id: str, work_id: str, text: str) -> Optional[Dict[str, Any]]:
        task = self.repo.get_task(task_id)
        if not task:
            return None
        state = _state(task)
        work = self._find(state["works"], work_id, "作品")
        rows = la.parse_import(text)
        if not rows:
            raise ValueError("没有读到评论：每行一条，格式「昵称：评论」，或从表格复制的「昵称<Tab>评论」")
        now = self._now()
        comments = [{
            "id": row.get("id") or la.comment_id(work["platform"], work_id, row["author"], row["text"]),
            "platform": work["platform"], "work_id": work_id,
            "author_id": row.get("author_id") or "", "author_name": row["author"], "text": row["text"],
            "published_at": row.get("published_at") or "", "likes": 0, "source": "import", "fetched_at": now,
        } for row in rows]
        added = self._ingest(task_id, task, comments)
        view = self.get(task_id)
        if view is not None:
            view["result"] = {"read": len(rows), **added}
        return view

    def sync(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Pull statistics and new comments for every work an official API can read, then score them."""
        task = self.repo.get_task(task_id)
        if not task:
            return None
        state = _state(task)
        client = self.youtube()
        targets = [work for work in state["works"] if work.get("platform") == "youtube" and work.get("video_id")]
        errors: List[str] = []
        comments: List[Dict[str, Any]] = []
        stats: Dict[str, Dict[str, int]] = {}
        if targets and not client.can_read:
            errors.append("没有配置 YOUTUBE_API_KEY，无法自动读取 YouTube")
        elif targets:
            try:
                stats = client.statistics([work["video_id"] for work in targets])
            except la.YouTubeError as error:
                errors.append(str(error))
            now = self._now()
            for work in targets:
                try:
                    fetched = client.comments(work["video_id"])
                except la.YouTubeError as error:
                    errors.append(f"{work.get('title') or work['video_id']}：{error}")
                    continue
                comments.extend({
                    "id": item["id"] or la.comment_id("youtube", work["id"], item["author"], item["text"]),
                    "platform": "youtube", "work_id": work["id"], "author_id": item["author_id"],
                    "author_name": item["author"], "text": item["text"], "published_at": item["published_at"],
                    "likes": item["likes"], "source": "api", "fetched_at": now,
                } for item in fetched if item.get("text"))
        added = self._ingest(task_id, task, comments, stats=stats, errors=errors, synced=True)
        view = self.get(task_id)
        if view is not None:
            view["result"] = {"read": len(comments), "errors": errors, "autoTargets": len(targets), **added}
        return view

    def _ingest(self, task_id: str, task: Dict[str, Any], comments: List[Dict[str, Any]], *,
                stats: Optional[Dict[str, Dict[str, int]]] = None, errors: Optional[List[str]] = None,
                synced: bool = False) -> Dict[str, int]:
        known = {item.get("id") for item in _state(task)["comments"]}
        fresh = [item for item in {item["id"]: item for item in comments}.values() if item["id"] not in known]
        judged = self._judge(task, fresh)

        def change(state: Dict[str, Any]) -> Dict[str, int]:
            have = {item.get("id") for item in state["comments"]}
            new_comments = [item for item in fresh if item["id"] not in have]
            created = 0
            for item in new_comments:
                verdict = judged.get(item["id"]) or {}
                item["intent"] = verdict.get("intent", "neutral")
                item["score"] = verdict.get("score", 0)
                if la.is_lead(item["intent"]):
                    created += self._lead_from(state, item, verdict)
            state["comments"] = (state["comments"] + new_comments)[-MAX_COMMENTS:]
            for work in state["works"]:
                if work.get("video_id") in (stats or {}):
                    work["metrics"] = {**(work.get("metrics") or {}), **stats[work["video_id"]]}
                    work["metrics_at"] = self._now()
                    work["metrics_source"] = "youtube_api"
            if synced:
                state["synced_at"] = self._now()
                state["sync_errors"] = list(errors or [])
            return {"newComments": len(new_comments), "newLeads": created}

        stored = self._mutate(task_id, change)
        return stored["result"] if stored else {"newComments": 0, "newLeads": 0}

    def _judge(self, task: Dict[str, Any], comments: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Rules for every comment; the model refines the non-spam ones and writes the drafts."""
        title, logline = self._drama(task)
        verdicts: Dict[str, Dict[str, Any]] = {}
        for item in comments:
            intent, score, _ = la.classify(item["text"])
            language = la.language_of(item["text"])
            where = self._where(task, language)
            verdicts[item["id"]] = {
                "intent": intent, "score": score, "by": "rules",
                "reply": la.template_reply(intent, language, title=title, where=where),
                "dm": la.template_dm(intent, language, title=title, where=where),
            }
        candidates = [item for item in comments if verdicts[item["id"]]["intent"] != "spam"]
        candidates.sort(key=lambda item: -verdicts[item["id"]]["score"])
        batch = candidates[:MODEL_BATCH]
        if not batch:
            return verdicts
        system, user = la.lead_prompt(batch, title=title, logline=logline, where=self._where(task, "zh"))
        try:
            answer = la.parse_lead_answer(
                self.gateway.call_llm(self._model(task), system, user, title, max_tokens=6000),
                [item["id"] for item in batch],
            )
        except Exception as error:  # 模型失败不挡入库：规则判定和模板草稿照样可用
            logger.warning("[Acquisition] 线索判定失败 (task=%s): %s", task.get("task_id"), type(error).__name__)
            return verdicts
        for comment_id, verdict in answer.items():
            fallback = verdicts[comment_id]
            verdicts[comment_id] = {
                "intent": verdict["intent"], "score": verdict["score"], "by": "model",
                "reply": verdict["reply"] or fallback["reply"],
                "dm": verdict["dm"] if verdict["intent"] in ("business", "watch_full", "want_more") else "",
            }
        return verdicts

    def _lead_from(self, state: Dict[str, Any], comment: Dict[str, Any], verdict: Dict[str, Any]) -> int:
        """Attach a comment to its author's lead; returns 1 when that is a new person."""
        key = la.author_key(comment["platform"], comment.get("author_id", ""), comment.get("author_name", ""), comment["id"])
        evidence = {"comment_id": comment["id"], "work_id": comment.get("work_id"), "text": comment["text"][:500],
                    "published_at": comment.get("published_at") or "", "intent": comment["intent"]}
        for lead in state["leads"]:
            if lead.get("key") == key:
                lead["evidence"] = ([evidence] + [item for item in lead.get("evidence") or [] if item.get("comment_id") != comment["id"]])[:_EVIDENCE_PER_LEAD]
                if int(verdict.get("score") or 0) > int(lead.get("score") or 0):
                    lead.update(intent=comment["intent"], score=verdict.get("score"))
                    if lead.get("status") == "new":
                        lead.update(reply=verdict.get("reply", ""), dm=verdict.get("dm", ""), reply_to=comment["id"])
                if lead.get("status") == "contacted":
                    lead["status"] = "replied"  # 联系过的人又来留言或私信，就是有回应
                lead["updated_at"] = self._now()
                return 0
        state["leads"].append({
            "id": "l" + uuid4().hex[:12], "key": key, "platform": comment["platform"],
            "author_id": comment.get("author_id") or "", "author_name": comment.get("author_name") or "匿名",
            "intent": comment["intent"], "score": verdict.get("score", 0), "judged_by": verdict.get("by", "rules"),
            "status": "new", "reply": verdict.get("reply", ""), "dm": verdict.get("dm", ""),
            "reply_to": comment["id"] if comment.get("source") != "inbox" else "",
            "evidence": [evidence], "history": [], "note": "",
            "send_state": "", "created_at": self._now(), "updated_at": self._now(),
        })
        return 1

    # ------------------------------------------------------------ 联系

    def update_lead(self, task_id: str, lead_id: str, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        status = changes.get("status")
        if status is not None and status not in la.LEAD_STATUSES:
            raise ValueError("状态不对")

        def change(state: Dict[str, Any]) -> None:
            lead = self._find(state["leads"], lead_id, "线索")
            for field in ("reply", "dm", "note"):
                if changes.get(field) is not None:
                    lead[field] = str(changes[field])[:1500]
            if status and status != lead.get("status"):
                lead["history"] = (lead.get("history") or []) + [{"at": self._now(), "action": f"status:{status}", "by": "manual"}]
                lead["status"] = status
                if status == "contacted":
                    lead["contacted_at"] = self._now()
                if status in ("won", "ignored"):
                    for item in state["follow_ups"]:
                        if item.get("lead_id") == lead_id and item.get("status") in ("pending", "sent_once"):
                            item.update(status="cancelled", completed_at=self._now())
            lead["updated_at"] = self._now()

        return self._after(task_id, change)

    def send_reply(self, task_id: str, lead_id: str) -> Optional[Dict[str, Any]]:
        """Post the lead's reply under its YouTube comment, once; an unclear result blocks a resend."""
        client = self.youtube()
        if not client.can_reply:
            raise ValueError("没有配置 YouTube 频道授权（YOUTUBE_CLIENT_ID / SECRET / REFRESH_TOKEN），请复制回复到 YouTube 手动发")
        claimed: Dict[str, str] = {}

        def claim(state: Dict[str, Any]) -> None:
            lead = self._find(state["leads"], lead_id, "线索")
            if lead.get("platform") != "youtube" or not lead.get("reply_to"):
                raise ValueError("只有 YouTube 评论线索能直接发送")
            if lead.get("send_state") in ("sending", "unknown"):
                raise ValueError("上一次发送结果不明：先到 YouTube 核对，再标记已发出或未发出")
            if lead.get("send_state") == "sent":
                raise ValueError("这条回复已经发过了")
            text = " ".join(str(lead.get("reply") or "").split())
            if not text:
                raise ValueError("回复是空的")
            lead["send_state"] = "sending"  # 先落下发送意图，进程中途死掉也不会被当成没发过
            claimed.update(parent=lead["reply_to"], text=text)

        if self._mutate(task_id, claim) is None:
            return None
        outcome: Dict[str, Any] = {}
        try:
            outcome["comment_id"] = client.reply(claimed["parent"], claimed["text"])
            outcome["state"] = "sent"
        except la.YouTubeError as error:
            outcome.update(state="failed" if error.definite else "unknown", error=str(error))

        def record(state: Dict[str, Any]) -> None:
            lead = self._find(state["leads"], lead_id, "线索")
            lead["send_state"] = "" if outcome["state"] == "failed" else outcome["state"]
            lead["send_error"] = outcome.get("error", "")
            entry = {"at": self._now(), "action": f"youtube_reply:{outcome['state']}", "by": "youtube_api", "text": claimed["text"]}
            if outcome.get("comment_id"):
                entry["comment_id"] = outcome["comment_id"]
            lead["history"] = (lead.get("history") or []) + [entry]
            if outcome["state"] == "sent" and lead.get("status") == "new":
                lead["status"] = "contacted"
                lead["contacted_at"] = self._now()
            lead["updated_at"] = self._now()

        self._mutate(task_id, record)
        view = self.get(task_id)
        if view is not None:
            view["result"] = outcome
        return view

    def resolve_send(self, task_id: str, lead_id: str, sent: bool) -> Optional[Dict[str, Any]]:
        """A person checked YouTube after an unclear send and says whether the reply is there."""
        def change(state: Dict[str, Any]) -> None:
            lead = self._find(state["leads"], lead_id, "线索")
            if lead.get("send_state") not in ("sending", "unknown"):
                raise ValueError("这条线索没有待核对的发送")
            lead["send_state"] = "sent" if sent else ""
            lead["send_error"] = ""
            lead["history"] = (lead.get("history") or []) + [{"at": self._now(), "action": f"verified:{'sent' if sent else 'not_sent'}", "by": "manual"}]
            if sent and lead.get("status") == "new":
                lead["status"] = "contacted"
                lead["contacted_at"] = self._now()

        return self._after(task_id, change)

    # ------------------------------------------------------------ 跟进

    def schedule_follow_up(self, task_id: str, lead_id: str, when: str, reason: str = "") -> Optional[Dict[str, Any]]:
        due = la.follow_up_time(when, self.clock())
        if due is None:
            raise ValueError("没看懂跟进时间：写「明天」「下周」「11月3日 15点」或 2026-11-03 15:00")
        if due <= self.clock() - timedelta(minutes=1):
            raise ValueError("跟进时间已经过去了")

        def change(state: Dict[str, Any]) -> None:
            lead = self._find(state["leads"], lead_id, "线索")
            self._replace_follow_up(state, lead, due, reason or when)

        return self._after(task_id, change)

    def _replace_follow_up(self, state: Dict[str, Any], lead: Dict[str, Any], due: datetime, reason: str) -> Dict[str, Any]:
        # 同一个人只留一条待办跟进：新约的时间替换旧的。
        for item in state["follow_ups"]:
            if item.get("lead_id") == lead["id"] and item.get("status") in ("pending", "sent_once"):
                item.update(status="cancelled", completed_at=self._now())
        entry = {
            "id": "f" + uuid4().hex[:12], "lead_id": lead["id"], "platform": lead.get("platform"),
            "author_name": lead.get("author_name"), "due_at": due.isoformat(), "reason": str(reason)[:200],
            "context": " / ".join(item.get("text", "")[:80] for item in (lead.get("evidence") or [])[:2]),
            "status": "pending", "created_at": self._now(), "completed_at": None,
        }
        state["follow_ups"].append(entry)
        return entry

    def update_follow_up(self, task_id: str, follow_up_id: str, status: str) -> Optional[Dict[str, Any]]:
        if status not in la.FOLLOW_UP_STATUSES:
            raise ValueError("状态不对")

        def change(state: Dict[str, Any]) -> None:
            item = self._find(state["follow_ups"], follow_up_id, "跟进")
            item["status"] = status
            if status in ("completed", "cancelled"):
                item["completed_at"] = self._now()
            if status in ("sent_once", "completed"):
                for lead in state["leads"]:
                    if lead.get("id") == item.get("lead_id"):
                        lead["history"] = (lead.get("history") or []) + [{"at": self._now(), "action": f"follow_up:{status}", "by": "manual"}]
                        if lead.get("status") == "new":
                            lead["status"] = "contacted"
                            lead["contacted_at"] = self._now()

        return self._after(task_id, change)

    # ------------------------------------------------------------ 私信接待

    def answer_inbox(self, task_id: str, platform: str, author: str, text: str) -> Optional[Dict[str, Any]]:
        """Draft the reply to someone who wrote in, keep them as a lead, and book the follow-up they asked for."""
        if platform not in la.CHANNEL_IDS:
            raise ValueError("不支持的平台")
        text = str(text or "").strip()
        if not text:
            raise ValueError("先粘贴对方的消息")
        task = self.repo.get_task(task_id)
        if not task:
            return None
        title, logline = self._drama(task)
        language = la.language_of(text)
        where = self._where(task, language)
        author = str(author or "").strip()[:40]
        key = la.author_key(platform, "", author, la.comment_id(platform, "inbox", author, text))
        history = [f"{item['from']}：{item['text'][:200]}" for item in _state(task)["inbox"] if item.get("key") == key]
        rule_intent, rule_score, _ = la.classify(text)
        drafted: Dict[str, str] = {}
        system, user = la.inbox_prompt(text, title=title, logline=logline, where=where, history=history)
        try:
            drafted = la.parse_inbox_answer(self.gateway.call_llm(self._model(task), system, user, title, max_tokens=1500))
        except Exception as error:  # 模型失败：退回模板回复
            logger.warning("[Acquisition] 私信回复生成失败 (task=%s): %s", task_id, type(error).__name__)
        intent = drafted.get("intent") or rule_intent
        reply = drafted.get("reply") or la.template_reply(intent, language, title=title, where=where)
        phrase = drafted.get("follow_up") or (text if la.mentions_delay(text) and intent in ("business", "watch_full", "want_more") else "")
        due = la.follow_up_time(phrase, self.clock()) if phrase else None
        if due is not None and due <= self.clock():
            due = None
        message_id = la.comment_id(platform, "inbox", author, text + self._now())
        outcome: Dict[str, Any] = {"intent": intent, "reply": reply, "followUp": None}

        def change(state: Dict[str, Any]) -> None:
            now = self._now()
            state["inbox"] = (state["inbox"] + [
                {"id": message_id, "key": key, "platform": platform, "author": author or "匿名", "from": "对方", "text": text[:2000], "at": now, "intent": intent},
                {"id": message_id + "r", "key": key, "platform": platform, "author": author or "匿名", "from": "草稿", "text": reply, "at": now, "intent": intent},
            ])[-MAX_INBOX * 2:]
            if la.is_lead(intent):
                comment = {"id": message_id, "platform": platform, "work_id": None, "author_id": "", "author_name": author,
                           "text": text, "published_at": now, "intent": intent, "source": "inbox"}
                score = max(rule_score if intent == rule_intent else 0, la.INTENTS[intent][1])
                self._lead_from(state, comment, {"intent": intent, "score": score, "reply": reply, "by": "model" if drafted else "rules",
                                                 "dm": la.template_dm(intent, language, title=title, where=where)})
                lead = next(item for item in state["leads"] if item.get("key") == key)
                lead["reply"] = reply  # 私信里来的人，回复就是给这条私信的
                outcome["leadId"] = lead["id"]
                if due is not None:
                    outcome["followUp"] = self._replace_follow_up(state, lead, due, f"对方说「{phrase}」")

        if self._mutate(task_id, change) is None:
            return None
        view = self.get(task_id)
        if view is not None:
            view["result"] = outcome
        return view

    # ------------------------------------------------------------ 定时

    def scheduled_sweep(self, task_ids: List[str]) -> Dict[str, int]:
        """The background pass: pull new comments for works an official API can read. Reads only, never sends."""
        client = self.youtube()
        swept = failed = 0
        if not client.can_read:
            return {"swept": 0, "failed": 0}
        for task_id in task_ids:
            task = self.repo.get_task(task_id)
            if not task:
                continue
            state = _state(task)
            if not state["settings"].get("auto_sync", True) or not any(work.get("platform") == "youtube" for work in state["works"]):
                continue
            try:
                self.sync(task_id)
                swept += 1
            except Exception as error:  # noqa: BLE001 - one task's failure must not stop the others
                failed += 1
                logger.warning("[Acquisition] 定时同步失败 (task=%s): %s", task_id, str(error)[:160])
        return {"swept": swept, "failed": failed}
