# -*- coding: utf-8 -*-
"""The poetry library: every text loads and checks out, what was asked for is on the shelf, and the Writer gets it only when asked."""

import json
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import poetry_api
from app.api.auth_api import get_current_user
from app.core import agent_tools, poetry_library
from app.service import screenwriting_service

# What the user asked for by name. Each must resolve to at least one work.
REQUESTED = (
    "道德经", "辛弃疾", "苏东坡", "欧阳修", "范仲淹", "晏几道", "晏殊", "徐再思", "柳永", "纳兰性德", "李白", "李商隐", "杜牧",
    "李煜", "姜夔", "滕王阁序", "岳阳楼记", "毛泽东", "李清照", "曹植", "陶渊明", "周敦颐", "王昌龄", "陆游", "韩愈", "元稹", "杨慎",
)


class ShelfTests(unittest.TestCase):
    def setUp(self):
        poetry_library.reset()
        self.lib = poetry_library.library()

    def test_everything_asked_for_is_there(self):
        poems, unknown = poetry_library.resolve_sources(list(REQUESTED), self.lib)
        self.assertEqual(unknown, [])
        for name in REQUESTED:
            with self.subTest(name):
                self.assertTrue(poetry_library.resolve_sources([name], self.lib)[0], name)

    def test_the_long_prose_pieces_are_whole(self):
        for title, opening, ending in (
            ("岳阳楼记", "庆历四年春", "吾谁与归"), ("滕王阁序", "豫章故郡", "一言均赋"), ("道德经·第81章", "信言不美", "为而不争"),
        ):
            with self.subTest(title):
                found = poetry_library.find_titled(title, lib=self.lib)
                self.assertTrue(found, title)
                text = found[0].entry.text
                self.assertIn(opening, text)
                self.assertIn(ending, text)

    def test_texts_are_clean(self):
        for poem in self.lib.poems:
            text = poem.entry.text
            with self.subTest(poem.key):
                # Supplementary-plane characters are conversion leftovers or variants nobody can type or render.
                self.assertFalse([ch for ch in text if ord(ch) > 0xFFFF], poem.key)
                for marker in ("{{", "}}", "[[", "<ref", "一作「", "一作“", "评曰", "註："):
                    self.assertNotIn(marker, text, poem.key)

    def test_protected_works_say_so_and_are_whole(self):
        # Mao's poems are stored in full (from the 2017 全编鉴赏 text layer) and stay flagged until the term ends.
        protected = [poem for poem in self.lib.poems if poem.entry.rights == "protected"]
        self.assertGreaterEqual(len(protected), 71)
        for poem in protected:
            with self.subTest(poem.key):
                self.assertIn("2026", poem.entry.rights_note)
                self.assertGreaterEqual(len(poem.entry.text), 28)
                self.assertNotIn("[", poem.entry.text)  # the book's note markers must not leak in
                self.assertIn("写作时间", poem.entry.note)
        self.assertTrue(all(poem.author == "毛泽东" for poem in protected))

    def test_collection_ids_and_keys_are_unique(self):
        keys = [poem.key for poem in self.lib.poems]
        self.assertEqual(len(keys), len(set(keys)))

    def test_a_famous_line_that_is_not_in_the_text_fails_on_load(self):
        broken = {
            "collection": "broken", "author": "某", "dynasty": "唐",
            "entries": [{"id": "x", "title": "某诗", "form": "诗", "text": "床前明月光，疑是地上霜。", "themes": ["思乡"], "famous_lines": ["举头望明月"]}],
        }
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "broken.json").write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(poetry_library.PoetryLibraryError, "名句"):
                poetry_library.load_library(Path(folder))


class FindingTests(unittest.TestCase):
    def setUp(self):
        poetry_library.reset()

    def test_by_alias_title_and_theme(self):
        self.assertTrue(all(poem.author == "苏轼" for poem in poetry_library.search("", author="苏东坡", limit=50)))
        self.assertEqual(poetry_library.find_titled("岳阳楼记")[0].author, "范仲淹")
        self.assertTrue(poetry_library.search("明月"))
        self.assertTrue(poetry_library.search("", author="易安"))

    def test_the_writer_gets_nothing_unless_the_project_asked(self):
        self.assertEqual(poetry_library.writer_block({}), "")
        self.assertEqual(screenwriting_service.poetry_materials({}), "")
        plain = screenwriting_service.writer_system_prompt("role", stage="write")
        self.assertNotIn(poetry_library.MATERIALS_HEADER, plain)

    def test_the_writer_gets_the_guide_and_the_named_sources_within_budget(self):
        config = {poetry_library.CONFIG_KEY: ["李清照", "没有这个人"]}
        block = poetry_library.writer_block(config, keywords="离别 秋", budget=1500)
        self.assertIn("李清照", block)
        self.assertIn("没有这个人", block)
        self.assertLessEqual(len(block), 1500)
        prompt = screenwriting_service.writer_system_prompt("role", stage="write", config=config)
        self.assertIn(poetry_library.MATERIALS_HEADER, prompt)
        self.assertIn("诗词取材与二次创作", prompt)
        self.assertNotIn(poetry_library.MATERIALS_HEADER, screenwriting_service.writer_system_prompt("role", stage="extract", config=config))

    def test_the_whole_xiaoshan_ci_is_on_the_shelf_with_the_curated_ones_shown_first(self):
        yan = poetry_library.library().by_collection("yanjidao")
        self.assertEqual(len(yan), 255, "小山词 全本")
        bulk = [poem for poem in yan if not poem.entry.curated]
        self.assertEqual(len(bulk), 203, "246 added in bulk, 43 of them since curated by hand")
        self.assertTrue(all("未逐首人工审读" in poem.entry.note for poem in bulk))
        self.assertIn("强欢殢酒图消遣", poetry_library.find_titled("风入松·心心念念忆相逢")[0].entry.text)
        self.assertIn("倚处阑干月", poetry_library.find_titled("点绛唇·明日征鞭")[0].entry.text)
        # A bulk entry's tags can out-score a curated one; the Writer still sees the curated works first.
        chosen = poetry_library.pick(yan, "重逢 歌女 旧情", limit=12)
        curated = [poem.entry.curated for poem in chosen]
        self.assertTrue(curated[0])
        self.assertEqual(curated, sorted(curated, reverse=True), "no bulk entry before a curated one")
        self.assertIn("鹧鸪天·彩袖殷勤捧玉钟", [poem.title for poem in chosen])
        self.assertEqual(poetry_library.search("桃源梦", author="晏几道")[0].title, "采桑子·无端恼破桃源梦", "search still finds them")

    def test_the_nalan_shelf_follows_tongzhitang_ji_and_puts_the_curated_works_first(self):
        nalan = poetry_library.library().by_collection("nalanxingde")
        self.assertEqual(len(nalan), 243, "15 hand-written entries + 228 from the Zhihu list's works")
        self.assertEqual(sum(1 for poem in nalan if not poem.entry.curated), 138, "218 added in bulk, 80 of them since curated by hand")
        self.assertIn("屧粉衣香何处", titled_text := next(p.entry.text for p in nalan if p.entry.text.startswith("黄叶青苔")))
        self.assertIn("今夜相思几许", titled_text)
        self.assertIn("爇尽水沈烟", next(p.entry.text for p in nalan if p.entry.text.startswith("东风不解愁")))
        self.assertIn("忆秦娥·龙潭口", {p.title for p in nalan})
        # A curated work carries the lines a writer can quote and no longer says it was tagged by keyword.
        rain = next(poem.entry for poem in nalan if poem.entry.text.startswith("别绪如丝"))
        self.assertTrue(rain.curated)
        self.assertIn("因听紫塞三更雨，却忆红楼半夜灯", rain.famous_lines)
        self.assertIn("呵手封题处", rain.text)
        self.assertNotIn("未逐首人工审读", rain.note)
        titled = {poem.title: poem.entry for poem in nalan}
        # The tune the transcription dropped is restored; the title split across the heading and the verse is joined.
        self.assertEqual(titled["蝶恋花·出塞"].tune, "蝶恋花")
        self.assertTrue(titled["蕉园"].text.startswith("见说斋坛"))
        # The long preface is the preface, not the first verse; the edition's reading wins over the Zhihu one.
        self.assertTrue(titled["沁园春·丁巳重阳前三日"].text.startswith("瞬息浮生"))
        self.assertIn("而今真个悔多情", titled["山花子·风絮飘残已化萍"].text)
        self.assertIn("拟古四十首·其十三", titled)
        chosen = poetry_library.pick(nalan, "悼亡 梦 边塞", limit=12)
        self.assertTrue(all(poem.entry.curated for poem in chosen[:12] if poem.entry.curated) and chosen[0].entry.curated)

    def test_every_writing_stage_gets_it(self):
        prompts = screenwriting_service.writer_system_prompts("role", config={poetry_library.CONFIG_KEY: ["全部"]})
        for stage in ("ledger", "plan", "prose"):
            self.assertIn(poetry_library.MATERIALS_HEADER, prompts[stage], stage)


class ReadersTests(unittest.TestCase):
    def setUp(self):
        poetry_library.reset()
        app = FastAPI()
        app.include_router(poetry_api.router)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u", "roles": [], "permissions": []}
        self.client = TestClient(app)

    def test_browsing(self):
        authors = self.client.get("/api/poetry/authors").json()
        self.assertIn("苏轼", [item["author"] for item in authors["items"]])
        found = self.client.get("/api/poetry", params={"q": "明月", "limit": 5}).json()
        self.assertTrue(found["items"])
        first = found["items"][0]["id"]
        detail = self.client.get(f"/api/poetry/{first}").json()
        self.assertTrue(detail["text"])
        self.assertEqual(self.client.get("/api/poetry/nobody/nothing").status_code, 404)

    def test_login_is_needed(self):
        app = FastAPI()
        app.include_router(poetry_api.router)
        self.assertEqual(TestClient(app).get("/api/poetry/authors").status_code, 401)

    def test_the_assistant_tools(self):
        user = {"user_id": "u", "roles": [], "permissions": []}

        def run(name, arguments):
            return agent_tools.catalog.call(name, arguments, service=None, user=user)

        found = run("search_poetry", {"author": "苏东坡", "limit": 3})
        self.assertTrue(found["ok"], found)
        items = found["result"]["items"]
        self.assertTrue(items)
        self.assertIn("text", run("get_poem", {"id": items[0]["id"]})["result"])
        self.assertEqual(run("get_poem", {"title": "岳阳楼记"})["result"]["author"], "范仲淹")
        missing = run("get_poem", {"title": "不存在的诗"})
        self.assertFalse(missing["ok"])
        self.assertIn("不存在的诗", missing["error"])


if __name__ == "__main__":
    unittest.main()
