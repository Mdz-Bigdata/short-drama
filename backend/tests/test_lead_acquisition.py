import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from app.core import lead_acquisition as la
from app.repository.task_repo import TaskRepository
from app.service.acquisition_service import KEY, AcquisitionService

TZ = ZoneInfo("Asia/Shanghai")
MORNING = datetime(2026, 10, 30, 11, 0, tzinfo=TZ)


class RuleTests(unittest.TestCase):
    def test_intents_from_comments(self):
        cases = {
            "这剧在哪看全集啊": "watch_full",
            "想谈下海外发行合作": "business",
            "快更新！下一集什么时候": "want_more",
            "女主为什么不说话？": "question",
            "AI味太重了看不下去": "complaint",
            "太好看了上头": "praise",
            "兼职日结点我头像": "spam",
            "Where can I watch the full series?": "watch_full",
            "We'd love to discuss distribution rights": "business",
        }
        for text, intent in cases.items():
            self.assertEqual(la.classify(text)[0], intent, text)

    def test_pasted_comments_in_each_format(self):
        lines = la.parse_import("阿青：在哪看全集\n小马\t求更新\t10-29\n\n只有内容的一行")
        self.assertEqual([(row["author"], row["text"]) for row in lines],
                         [("阿青", "在哪看全集"), ("小马", "求更新"), ("", "只有内容的一行")])
        self.assertEqual(lines[1]["published_at"], "10-29")
        exported = la.parse_import(json.dumps([{"nickname": "A", "content": "合作", "cid": "77"}], ensure_ascii=False))
        self.assertEqual(exported[0]["id"], "77")
        self.assertEqual(la.parse_import("   "), [])

    def test_follow_up_times_from_what_people_say(self):
        def at(phrase, now=MORNING):
            found = la.follow_up_time(phrase, now)
            return found.strftime("%m-%d %H:%M") if found else None

        self.assertEqual(at("明天再说"), "10-31 10:00")
        self.assertEqual(at("后天"), "11-01 10:00")
        self.assertEqual(at("下午吧"), "10-30 14:00")
        self.assertEqual(at("下午吧", MORNING.replace(hour=15)), "10-31 14:00")
        self.assertEqual(at("晚上看看"), "10-30 19:00")
        self.assertEqual(at("下周"), "11-06 10:00")
        self.assertEqual(at("等发工资"), "11-04 10:00")
        self.assertEqual(at("过两天"), "11-02 10:00")
        self.assertEqual(at("明天下午3点"), "10-31 15:00")
        self.assertEqual(at("11月3日 15点"), "11-03 15:00")
        self.assertEqual(at("5号"), "11-05 10:00", "a day already past this month means next month")
        self.assertEqual(at("2026-11-05 09:30"), "11-05 09:30")
        self.assertEqual(at("tomorrow"), "10-31 10:00")
        self.assertEqual(at("in 4 days"), "11-03 10:00")
        self.assertIsNone(at("随便"))

    def test_youtube_links(self):
        for url in ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3", "https://youtu.be/dQw4w9WgXcQ",
                    "https://youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"):
            self.assertEqual(la.youtube_video_id(url), "dQw4w9WgXcQ", url)
        self.assertIsNone(la.youtube_video_id("https://www.douyin.com/video/123"))

    def test_model_answer_is_validated(self):
        text = '```json\n{"items": [{"id": "a", "intent": "business", "score": 140, "reply": " 你好 ", "dm": "x"},' \
               '{"id": "b", "intent": "made_up"}, {"id": "zzz", "intent": "praise"}]}\n```'
        answer = la.parse_lead_answer(text, ["a", "b"])
        self.assertEqual(list(answer), ["a"])
        self.assertEqual(answer["a"]["score"], 100)
        self.assertEqual(answer["a"]["reply"], "你好")

    def test_templates_never_carry_contact_details(self):
        for intent in la.INTENTS:
            for language in ("zh", "en"):
                text = la.template_reply(intent, language, title="拭剑奴", where="抖音") + la.template_dm(intent, language, title="拭剑奴", where="抖音")
                self.assertNotRegex(text, r"https?://|微信|wechat|\d{11}")


class _Response:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class _FakeHttp:
    """Records requests; answers from a list of (status, body) or raises the exceptions in it."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return _Response(*answer)


def _thread(comment_id, author, text):
    return {"id": f"t{comment_id}", "snippet": {"topLevelComment": {"id": comment_id, "snippet": {
        "authorDisplayName": author, "authorChannelId": {"value": f"UC{author}"}, "textOriginal": text,
        "publishedAt": "2026-10-29T10:00:00Z", "likeCount": 2}}}}


class YouTubeClientTests(unittest.TestCase):
    def test_comments_follow_pages_and_keep_the_reply_target(self):
        http = _FakeHttp([(200, {"items": [_thread("c1", "ann", "where to watch full?")], "nextPageToken": "p2"}),
                          (200, {"items": [_thread("c2", "bo", "love it")]})])
        found = la.YouTubeClient(api_key="k", http=http).comments("dQw4w9WgXcQ")

        self.assertEqual([item["id"] for item in found], ["c1", "c2"])
        self.assertEqual(found[0]["author_id"], "UCann")
        self.assertEqual(http.calls[1][2]["params"]["pageToken"], "p2")
        self.assertEqual(http.calls[0][2]["params"]["key"], "k")

    def test_reply_refreshes_the_token_and_posts_under_the_comment(self):
        http = _FakeHttp([(200, {"access_token": "tok"}), (200, {"id": "new1"})])
        client = la.YouTubeClient(client_id="i", client_secret="s", refresh_token="r", http=http)

        self.assertEqual(client.reply("c1", "Thanks!"), "new1")
        method, _, kwargs = http.calls[1]
        self.assertEqual(kwargs["json"]["snippet"], {"parentId": "c1", "textOriginal": "Thanks!"})
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok")

    def test_a_dropped_connection_is_an_unclear_send_and_a_4xx_a_definite_failure(self):
        dropped = la.YouTubeClient(client_id="i", client_secret="s", refresh_token="r",
                                   http=_FakeHttp([(200, {"access_token": "t"}), httpx.ReadTimeout("slow")]))
        with self.assertRaises(la.YouTubeError) as unclear:
            dropped.reply("c1", "hi")
        self.assertFalse(unclear.exception.definite)

        refused = la.YouTubeClient(client_id="i", client_secret="s", refresh_token="r", http=_FakeHttp([
            (200, {"access_token": "t"}), (403, {"error": {"errors": [{"reason": "commentsDisabled"}]}})]))
        with self.assertRaises(la.YouTubeError) as definite:
            refused.reply("c1", "hi")
        self.assertTrue(definite.exception.definite)
        self.assertIn("关闭了评论", str(definite.exception))


class _Gateway:
    def __init__(self, answer=None):
        self.answer = answer
        self.prompts = []

    def call_llm(self, model, system_prompt, user_prompt, title, *args, **kwargs):
        self.prompts.append(user_prompt)
        if isinstance(self.answer, Exception):
            raise self.answer
        if callable(self.answer):
            return self.answer(user_prompt)
        return self.answer or "{}"


class _FakeYouTube:
    def __init__(self, *, read=True, reply=True, comments=None, reply_error=None):
        self.can_read = read
        self.can_reply = reply
        self._comments = comments or []
        self.reply_error = reply_error
        self.replies = []

    def statistics(self, ids):
        return {video_id: {"views": 1200, "likes": 80, "comments": len(self._comments)} for video_id in ids}

    def comments(self, video_id, limit=200):
        return list(self._comments)

    def reply(self, parent_id, text):
        self.replies.append((parent_id, text))
        if self.reply_error:
            raise self.reply_error
        return "posted1"


def _judge_everything(prompt):
    """A model stand-in that tags every comment id in the prompt as a business lead."""
    import re
    ids = re.findall(r"id=(\S+?)｜", prompt)
    return json.dumps({"items": [{"id": item, "intent": "business", "score": 88, "reply": "感谢关注，欢迎私信。", "dm": "您好"} for item in ids]})


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("acq-1", {
            "task_id": "acq-1", "status": "idle", "logs": {}, "config": {"title_suggestion": "拭剑奴"},
            "assets": {"1": "贱籍少年拭剑为生。", "8": {"pr_content": "大字标题：拭剑奴"}},
        })
        self.youtube = _FakeYouTube()
        self.gateway = _Gateway(RuntimeError("model down"))
        self.now = MORNING
        self.service = AcquisitionService(self.repo, self.gateway, youtube=lambda: self.youtube, clock=lambda: self.now)

    def tearDown(self):
        self.temp.cleanup()

    def _work(self, platform="douyin", url="https://www.douyin.com/video/7400000000000000001"):
        view = self.service.add_work("acq-1", platform, url, episode=1)
        return view["works"][-1]["id"]

    def test_imported_comments_become_deduplicated_leads_with_drafts(self):
        work = self._work()
        view = self.service.import_comments("acq-1", work, "阿青：在哪看全集\n阿青：求全集链接\n路人：太好看了\n广告：兼职日结点我头像")

        self.assertEqual(view["result"], {"read": 4, "newComments": 4, "newLeads": 1})
        lead = view["leads"][0]
        self.assertEqual((lead["author_name"], lead["intent"], lead["judged_by"]), ("阿青", "watch_full", "rules"))
        self.assertEqual(len(lead["evidence"]), 2, "the same person's two comments are one lead")
        self.assertIn("抖音", lead["reply"], "the template says where the full series is")
        again = self.service.import_comments("acq-1", work, "阿青：在哪看全集")
        self.assertEqual(again["result"]["newComments"], 0)
        self.assertEqual(again["works"][0]["comments"], 4)

    def test_the_model_refines_intent_and_writes_the_reply(self):
        self.gateway.answer = _judge_everything
        work = self._work()
        view = self.service.import_comments("acq-1", work, "老周：你们这个剧能聊聊吗")

        lead = view["leads"][0]
        self.assertEqual((lead["intent"], lead["score"], lead["judged_by"]), ("business", 88, "model"))
        self.assertEqual(lead["reply"], "感谢关注，欢迎私信。")
        self.assertIn("剧名：拭剑奴", self.gateway.prompts[0])

    def test_sync_reads_youtube_and_records_metrics(self):
        self.youtube._comments = [{"id": "Ugx1", "author": "Ann", "author_id": "UCann", "text": "Where can I watch the full series?",
                                   "published_at": "2026-10-29T10:00:00Z", "likes": 3}]
        work = self._work("youtube", "https://youtu.be/dQw4w9WgXcQ")
        view = self.service.sync("acq-1")

        self.assertEqual(view["result"]["newLeads"], 1)
        self.assertEqual(view["works"][0]["metrics"]["views"], 1200)
        self.assertEqual(view["leads"][0]["reply_to"], "Ugx1")
        self.assertIsNotNone(view["syncedAt"])
        self.assertEqual(self.service.sync("acq-1")["result"]["newComments"], 0)
        self.assertEqual(work, view["works"][0]["id"])

    def test_sync_without_a_key_says_so(self):
        self.youtube.can_read = False
        self._work("youtube", "https://youtu.be/dQw4w9WgXcQ")

        view = self.service.sync("acq-1")
        self.assertIn("YOUTUBE_API_KEY", view["syncErrors"][0])

    def _youtube_lead(self):
        self.youtube._comments = [{"id": "Ugx1", "author": "Ann", "author_id": "UCann", "text": "full series link?",
                                   "published_at": "", "likes": 0}]
        self._work("youtube", "https://youtu.be/dQw4w9WgXcQ")
        return self.service.sync("acq-1")["leads"][0]["id"]

    def test_a_reply_is_sent_once_and_marks_the_lead_contacted(self):
        lead_id = self._youtube_lead()
        view = self.service.send_reply("acq-1", lead_id)

        self.assertEqual(view["result"]["state"], "sent")
        self.assertEqual(self.youtube.replies[0][0], "Ugx1")
        lead = view["leads"][0]
        self.assertEqual((lead["status"], lead["send_state"]), ("contacted", "sent"))
        with self.assertRaises(ValueError):
            self.service.send_reply("acq-1", lead_id)
        self.assertEqual(len(self.youtube.replies), 1)

    def test_an_unclear_send_blocks_a_resend_until_someone_checks(self):
        lead_id = self._youtube_lead()
        self.youtube.reply_error = la.YouTubeError("dropped", definite=False)

        self.assertEqual(self.service.send_reply("acq-1", lead_id)["result"]["state"], "unknown")
        with self.assertRaises(ValueError):
            self.service.send_reply("acq-1", lead_id)
        view = self.service.resolve_send("acq-1", lead_id, sent=False)
        self.assertEqual(view["leads"][0]["send_state"], "")
        self.youtube.reply_error = None
        self.assertEqual(self.service.send_reply("acq-1", lead_id)["result"]["state"], "sent")

    def test_sending_needs_channel_authorisation(self):
        lead_id = self._youtube_lead()
        self.youtube.can_reply = False

        with self.assertRaises(ValueError):
            self.service.send_reply("acq-1", lead_id)
        self.assertEqual(self.youtube.replies, [])

    def test_one_pending_follow_up_per_person_and_closing_a_lead_cancels_it(self):
        work = self._work()
        lead_id = self.service.import_comments("acq-1", work, "阿青：在哪看全集")["leads"][0]["id"]

        self.service.schedule_follow_up("acq-1", lead_id, "明天")
        view = self.service.schedule_follow_up("acq-1", lead_id, "下周")
        pending = [item for item in view["followUps"] if item["status"] == "pending"]
        self.assertEqual(len(pending), 1)
        self.assertTrue(pending[0]["due_at"].startswith("2026-11-06T10:00"))
        with self.assertRaises(ValueError):
            self.service.schedule_follow_up("acq-1", lead_id, "随便")
        view = self.service.update_lead("acq-1", lead_id, {"status": "won"})
        self.assertFalse([item for item in view["followUps"] if item["status"] == "pending"])

    def test_the_review_counts_due_follow_ups_and_suggests_next_steps(self):
        work = self._work()
        lead_id = self.service.import_comments("acq-1", work, "老周：想谈海外发行合作")["leads"][0]["id"]
        self.service.schedule_follow_up("acq-1", lead_id, "下午")
        self.now = MORNING.replace(hour=15)

        review = self.service.get("acq-1")["review"]
        self.assertEqual(review["due_follow_ups"], 1)
        self.assertEqual(review["funnel"]["leads"], 1)
        self.assertTrue(any("合作意向" in text for text in review["suggestions"]))

    def test_an_inbound_message_gets_a_reply_and_the_follow_up_it_asked_for(self):
        self.gateway.answer = json.dumps({"intent": "business", "reply": "您好，收到！明天我们把资料发您。", "follow_up": "明天"}, ensure_ascii=False)
        view = self.service.answer_inbox("acq-1", "douyin", "老周", "想谈合作，明天再细聊")

        self.assertEqual(view["result"]["reply"], "您好，收到！明天我们把资料发您。")
        self.assertTrue(view["result"]["followUp"]["due_at"].startswith("2026-10-31T10:00"))
        self.assertEqual(view["leads"][0]["author_name"], "老周")
        self.assertEqual([item["from"] for item in view["inbox"]], ["草稿", "对方"])

    def test_an_inbound_message_falls_back_to_rules_when_the_model_fails(self):
        view = self.service.answer_inbox("acq-1", "douyin", "阿青", "全集在哪看？过两天发工资了想看")

        self.assertEqual(view["result"]["intent"], "watch_full")
        self.assertTrue(view["result"]["followUp"]["due_at"].startswith("2026-11-04"), "工资 → in five days")

    def test_a_stale_stage_save_keeps_the_acquisition_state(self):
        stale = self.repo.get_task("acq-1")
        self._work()
        stale["status"] = "running"
        self.repo.save_task("acq-1", stale)

        self.assertEqual(len(self.repo.get_task("acq-1")["assets"][KEY]["works"]), 1)
        self.assertEqual(self.repo.task_ids_containing(f'"{KEY}"'), ["acq-1"])

    def test_the_sweep_reads_only_projects_with_youtube_works_and_auto_sync_on(self):
        self._youtube_lead()
        self.assertEqual(self.service.scheduled_sweep(["acq-1"]), {"swept": 1, "failed": 0})
        self.service.set_auto_sync("acq-1", False)
        self.assertEqual(self.service.scheduled_sweep(["acq-1"]), {"swept": 0, "failed": 0})
        self.assertEqual(self.youtube.replies, [], "the sweep never sends")

    def test_bad_input_is_refused(self):
        with self.assertRaises(ValueError):
            self.service.add_work("acq-1", "weibo", "https://weibo.com/1")
        with self.assertRaises(ValueError):
            self.service.add_work("acq-1", "youtube", "https://example.com/v")
        self._work()
        with self.assertRaises(ValueError):
            self._work()
        with self.assertRaises(LookupError):
            self.service.update_lead("acq-1", "nope", {"status": "won"})


if __name__ == "__main__":
    unittest.main()
