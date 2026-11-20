# -*- coding: utf-8 -*-
"""Creative intents, style packs and storyboard panels say what their wording tables say.

No model, no network. Each table (``creative_intent.json``, ``style_packs.json``,
``storyboard_panels.json``) is checked against the module that reads it in both directions:
every entry in the table is read, every entry the code asks for is there with exactly the
placeholders it fills, order is kept where the first match wins, and no Chinese string is left
(nor any other non-ASCII text: full-width punctuation, arrows) written in the module outside its
docstrings.
"""

import ast
import dataclasses
import inspect
import re
import string
import unittest
from types import ModuleType
from unittest.mock import patch

from app.core import creative_intent, prompt_data, storyboard_panels, style_packs

_MODULES: dict[str, ModuleType] = {
    "creative_intent": creative_intent,
    "style_packs": style_packs,
    "storyboard_panels": storyboard_panels,
}
# Non-ASCII string literals (Chinese words, full-width punctuation, arrows, dashes) a module may still
# carry outside its docstrings, each with the reason it is not wording. None are needed: every
# sentence, word, joiner and pattern is in the table.
_ALLOWED_LITERALS: dict[str, dict[str, str]] = {name: {} for name in _MODULES}


def _tree(module: ModuleType) -> ast.Module:
    return ast.parse(inspect.getsource(module))


def _literal(node: ast.AST | None, what: str) -> str:
    if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
        raise AssertionError(f"a {what} key is not a literal at line {getattr(node, 'lineno', '?')}")
    return node.value


def _calls(module: ModuleType, helper: str) -> list[tuple[str, frozenset[str], int]]:
    """Every ``helper("key", ...)``: the key it names, the keywords it fills, and its line."""
    found = []
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == helper:
            if len(node.args) != 1:
                raise AssertionError(f"{helper} takes one positional key (line {node.lineno})")
            first = node.args[0]
            if isinstance(first, ast.IfExp):  # _says("a" if … else "b", …): both keys are read
                for branch in (first.body, first.orelse):
                    found.append((_literal(branch, helper), frozenset(item.arg for item in node.keywords), node.lineno))
                continue
            found.append((_literal(first, helper), frozenset(item.arg for item in node.keywords), node.lineno))
    return found


def _is_wording(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "_WORDING"


def _top_level_reads(module: ModuleType) -> set[str]:
    """Top-level keys read: ``_word("k")``, ``prompt_data.f(_WORDING, "k")``, ``prompt_data.load(_WORDING)["k"]``."""
    keys = {key for key, _, _ in _calls(module, "_word")}
    for node in ast.walk(_tree(module)):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "prompt_data" and len(node.args) >= 2 and _is_wording(node.args[0])
            and not (isinstance(node.args[1], ast.Name) and node.args[1].id == "key")  # the _word helper itself
        ):
            keys.add(_literal(node.args[1], "prompt_data"))
        elif (
            isinstance(node, ast.Subscript) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "load"
            and node.value.args and _is_wording(node.value.args[0])
        ):
            keys.add(_literal(node.slice, "load"))
    return keys


def _fields(template: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name)


def _docstring_nodes(tree: ast.Module) -> set[int]:
    nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                nodes.add(id(first.value))
    return nodes


def _reworded(name: str, change):
    """Patch ``prompt_data.load`` so the table ``name`` comes back changed by ``change(copy)``."""
    import copy

    original = prompt_data.load
    table = copy.deepcopy(original(name))
    change(table)
    return patch.object(prompt_data, "load", lambda which: table if which == name else original(which))


class EveryTableMatchesItsModuleTests(unittest.TestCase):
    def test_every_sentence_in_a_table_is_used_and_every_one_asked_for_is_there(self):
        for name, module in _MODULES.items():
            with self.subTest(table=name):
                says = prompt_data.load(name)["says"]
                asked = {key for key, _, _ in _calls(module, "_says")}
                self.assertEqual(set(says) - asked, set(), "sentences nothing reads")
                self.assertEqual(asked - set(says), set(), "sentences the module reads that are missing")

    def test_each_sentence_gets_exactly_the_placeholders_it_names(self):
        for name, module in _MODULES.items():
            says = prompt_data.load(name)["says"]
            for key, filled, line in _calls(module, "_says"):
                with self.subTest(table=name, key=key):
                    self.assertEqual(filled, _fields(says[key]), f"{name}.says.{key} (line {line}): placeholders")

    def test_every_template_formats(self):
        for name in _MODULES:
            for key, template in prompt_data.load(name)["says"].items():
                with self.subTest(table=name, key=key):
                    template.format(**{field: 1.5 for field in _fields(template)})

    def test_every_top_level_entry_is_read_and_every_one_read_is_there(self):
        for name, module in _MODULES.items():
            with self.subTest(table=name):
                table = set(prompt_data.load(name)) - {"_about"}
                read = _top_level_reads(module)
                self.assertEqual(table - read, set(), "entries nothing reads")
                self.assertEqual(read - table, set(), "entries the module reads that are missing")

    def test_plain_words_are_never_templates(self):
        for name, module in _MODULES.items():
            data = prompt_data.load(name)
            for key in {key for key, _, _ in _calls(module, "_word")}:
                with self.subTest(table=name, key=key):
                    self.assertIsInstance(data[key], str)
                    self.assertTrue(data[key])
                    self.assertEqual(_fields(data[key]), frozenset())

    def test_no_chinese_or_other_non_ascii_string_literal_is_left_in_the_modules(self):
        for name, module in _MODULES.items():
            with self.subTest(module=name):
                tree = _tree(module)
                docstrings = _docstring_nodes(tree)
                left = sorted({
                    node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings and not node.value.isascii()
                } - set(_ALLOWED_LITERALS[name]))
                self.assertEqual(left, [])


class CreativeIntentTableTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load("creative_intent")

    def test_each_intent_row_carries_exactly_the_intent_fields(self):
        fields = {field.name for field in dataclasses.fields(creative_intent.Intent)}
        for row in self.data["intents"]:
            with self.subTest(intent=row.get("id")):
                self.assertEqual(set(row), fields)

    def test_the_catalogue_is_the_table_in_its_order(self):
        # Order matters: the first intent is the last-resort fallback and ties in a brief go to the earlier one.
        self.assertEqual([intent.id for intent in creative_intent.INTENTS], [row["id"] for row in self.data["intents"]])
        self.assertEqual(
            [intent.id for intent in creative_intent.INTENTS],
            ["vfx_maxed", "tight_fight", "tension", "impact", "burning", "epic", "oppressive", "healing",
             "comedic", "eerie", "tragic", "beat_synced", "one_take"],
        )
        for intent, row in zip(creative_intent.INTENTS, self.data["intents"]):
            self.assertEqual(intent.triggers, tuple(row["triggers"]), intent.id)
            self.assertEqual(intent.conflicts, tuple(row["conflicts"]), intent.id)

    def test_the_numbers_are_shares_and_the_conflicts_name_real_intents(self):
        ids = {row["id"] for row in self.data["intents"]}
        self.assertEqual(len(ids), len(self.data["intents"]), "duplicate intent id")
        for row in self.data["intents"]:
            with self.subTest(intent=row["id"]):
                self.assertEqual(len(row["sizes"]), len(creative_intent.SIZE_BANDS))
                self.assertAlmostEqual(sum(row["sizes"]), 1.0, places=6)
                self.assertTrue(0 <= row["vfx_density"] <= 1)
                self.assertGreater(row["rhythm"], 0)
                self.assertLessEqual(set(row["conflicts"]), ids)
                self.assertTrue(row["triggers"] and all(row["triggers"]))
        self.assertEqual(len(self.data["size_labels"]), len(creative_intent.SIZE_BANDS))

    def test_the_brief_reads_as_before(self):
        plan = creative_intent.decode("", primary="oppressive", secondary=["burning", "eerie"])
        self.assertEqual(
            plan.brief(),
            "【感觉】主感觉：压抑暗黑；次感觉：悬疑惊悚（只做偏移，不反客为主）\n"
            "运镜倾向：窥视式横移、缓慢推进、俯冲下压\n"
            "景别分布：远中景22%、中景34%、近特写44%；镜头长度按1.41倍基准（小于1更碎、大于1更长）\n"
            "特效密度：约14%的镜头带明显特效\n"
            "构图：压缩头顶空间、画框向内挤压、人物被环境吞掉、前景遮挡\n"
            "光影：低调、单光源、大片阴影吃掉人物、冷色主导，拒绝暖调\n"
            "音效策略：持续低频铺底、不协和音与噪声、可听见的心跳；不超过两层\n"
            "次感觉「悬疑惊悚」只在对应段落与峰值镜加权：从缝隙窥视、反向拉轨、甩镜、跳切闪回、穿物推进；"
            "低调、大片黑区、单点光源（手电烛光月光）、闪烁光、阴影里有东西\n"
            "已丢弃冲突次感觉：高燃（与主感觉「压抑暗黑」相冲）",
        )
        self.assertEqual(
            creative_intent.decode("", primary="vfx_maxed").camera_line("E1S02"),
            "运镜倾向：这一场优先用「超快环绕」作主运镜，确实不合戏再换成极速推拉、离心甩出",
        )

    def test_a_reworded_sentence_reaches_the_brief(self):
        def change(table):
            table["says"]["vfx"] = "特效：{percent}成"

        with _reworded("creative_intent", change):
            self.assertIn("\n特效：10成\n", creative_intent.decode("", primary="tension").brief())


class StylePackTableTests(unittest.TestCase):
    _PACK_FIELDS = {
        "name", "summary", "lock", "tone_slots", "tone_default", "camera", "palette", "positives", "negatives",
        "situational_negatives", "anti_leak", "extension_restatement", "signature_sfx", "style_caption", "aliases",
    }

    def setUp(self):
        self.data = prompt_data.load("style_packs")

    def _pack_reads(self) -> set[str]:
        """The pack fields ``_pack`` reads: every ``words["k"]``."""
        build = next(
            node for node in ast.walk(_tree(style_packs)) if isinstance(node, ast.FunctionDef) and node.name == "_pack"
        )
        return {
            _literal(node.slice, "pack field") for node in ast.walk(build)
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "words"
        }

    def test_every_pack_field_is_read_and_every_one_read_is_there(self):
        read = self._pack_reads()
        self.assertEqual(read, self._PACK_FIELDS)
        for pack_id, words in self.data["packs"].items():
            with self.subTest(pack=pack_id):
                self.assertEqual(set(words), self._PACK_FIELDS)
                self.assertLessEqual(set(words["camera"]), set(style_packs.CameraKit.model_fields) - {"per_shot_swap_allowed"})
                self.assertLessEqual(set(words["palette"]), set(style_packs.PaletteRules.model_fields))

    def test_every_pack_in_the_table_is_built_and_says_what_the_table_says(self):
        packs = {pack.id: pack for pack in style_packs.list_packs()}
        self.assertEqual(set(packs), set(self.data["packs"]))
        # The catalog order other code shows (and the default first) is the module's, not the table's.
        self.assertEqual(list(packs), ["cinematic_realism", "film_35mm", "atom_punk", "anime_2d_cel", "anime_3d_cg"])
        self.assertEqual(style_packs.DEFAULT_PACK_ID, "cinematic_realism")
        for pack_id, words in self.data["packs"].items():
            pack = packs[pack_id]
            with self.subTest(pack=pack_id):
                self.assertEqual(pack.name, words["name"])
                self.assertEqual(pack.lock, words["lock"])
                self.assertEqual(pack.tone_slots, words["tone_slots"])
                self.assertEqual(pack.style_caption, words["style_caption"])
                self.assertEqual(pack.aliases, words["aliases"])
                self.assertEqual(pack.anti_leak, words["anti_leak"])
                self.assertEqual(pack.sound.signature_sfx, words["signature_sfx"])
                self.assertEqual(pack.positives[len(pack.positives) - len(words["positives"]):], words["positives"])
                self.assertEqual(pack.negatives[len(pack.negatives) - len(words["negatives"]):], words["negatives"])
                self.assertEqual(
                    [colour.model_dump() for colour in pack.palette.through_colours], words["palette"].get("through_colours", []),
                )
                # Only what the table sets is set: everything else stays the model's default.
                self.assertEqual(pack.camera.model_fields_set, {*words["camera"], "per_shot_swap_allowed"})
                self.assertEqual(pack.palette.model_fields_set, set(words["palette"]))

    def test_live_action_packs_build_on_the_shared_lists_in_order(self):
        for pack in (style_packs.FILM_35MM, style_packs.ATOM_PUNK, style_packs.CINEMATIC_REALISM):
            with self.subTest(pack=pack.id):
                shared = prompt_data.words("iron_rules", "live_action_negatives")
                self.assertEqual(tuple(pack.negatives[:len(shared)]), shared)
                shared = prompt_data.words("iron_rules", "live_action_positives")
                self.assertEqual(tuple(pack.positives[:len(shared)]), shared)
                situational = prompt_data.value("iron_rules", "situational_negatives")
                self.assertEqual(list(pack.situational_negatives)[:len(situational)], list(situational))

    def test_negatives_keep_the_continuity_terms_first(self):
        continuity = list(prompt_data.words("iron_rules", "continuity_negatives"))
        for pack in style_packs.list_packs():
            with self.subTest(pack=pack.id):
                terms = style_packs.negatives_for(pack, ["fight"])
                self.assertEqual(terms[:len(continuity)], list(dict.fromkeys(continuity)))

    def test_every_anti_leak_guard_names_a_reference_kind(self):
        marker, names = self.data["anti_leak_marker"], set(self.data["leak_kinds"].values())
        for pack_id, words in self.data["packs"].items():
            # A guard without the marker (atom_punk's pixel-panel rule) is the pack's own and is never matched to a reference.
            for guard in (item for item in words["anti_leak"] if marker in item):
                with self.subTest(pack=pack_id, guard=guard[:12]):
                    self.assertIn(guard.split(marker)[0], names)

    def test_the_rules_read_as_before(self):
        card = style_packs.build_palette_card(
            style_packs.ATOM_PUNK, project="废土", episode=1, segment=2, subject="仓库",
            new_colours=[style_packs.PaletteColour(name="铁锈红", hex="#8B3A2A", bound_to="锈蚀铁门")],
        )
        self.assertEqual(card.title, "废土 EP1 SEG2 - 仓库 COLOR REFERENCE")
        self.assertEqual(
            style_packs.palette_lines(card, "@图片3"),
            ["@图片3作为整段色卡锚定 + 所有色彩严格按色卡4色执行 + 不可偏离色板。",
             "主要色值：电子管与仪表灯琥珀#FFBF00；氧化铜管件铜绿#4A7C59；铆钉钢板深金属灰#2C3539；锈蚀铁门铁锈红#8B3A2A。"],
        )
        with self.assertRaises(ValueError) as raised:
            style_packs.build_palette_card(
                style_packs.FILM_35MM, project="p", episode=1, segment=1, subject="s",
                new_colours=[style_packs.PaletteColour(name="黑", hex="#000000", bound_to="")],
            )
        self.assertEqual(str(raised.exception), "色卡「黑」必须绑定具体物件，「空」不是物件")
        self.assertEqual(
            style_packs.image_style_line(style_packs.ANIME_2D_CEL, lighting=" 柔光 "),
            style_packs.ANIME_2D_CEL.style_caption + "；柔光 lighting style；画幅 9:16",
        )
        self.assertEqual(
            style_packs.identity_negative(style_packs.ANIME_2D_CEL, "(避免：证件照；并严禁任何非写实风格：动画)"), "(避免：证件照)",
        )
        self.assertTrue(style_packs.FILM_35MM.lock_text.startswith("[STYLE LOCK]\nShot on 35mm"))
        self.assertEqual(style_packs.SoundDefaults().closing_sentence, self.data["closing_sentence"])

    def test_a_reworded_sentence_reaches_the_rules(self):
        def change(table):
            table["says"]["style_rule"] = "画风禁忌：{terms}"

        with _reworded("style_packs", change):
            rules = style_packs.iron_rules(style_packs.FILM_35MM)
        self.assertEqual(rules[-1], "画风禁忌：" + " + ".join(style_packs.FILM_35MM.negatives[:5]))


class StoryboardPanelTableTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load("storyboard_panels")

    def test_every_joiner_is_used_and_every_one_asked_for_is_there(self):
        asked = {key for key, _, _ in _calls(storyboard_panels, "_joiner")}
        self.assertEqual(asked, set(self.data["joiners"]))

    def test_the_merged_beat_joiner_is_the_one_the_still_prompt_splits_on(self):
        # panel_still_prompt splits a merged panel back into beats on its own copy of this joiner.
        self.assertEqual(self.data["joiners"]["desc"], prompt_data.text("panel_still", "merged_beats"))

    def test_the_size_scale_is_the_table_in_order_and_a_longer_term_is_tried_first(self):
        self.assertEqual(
            storyboard_panels._SIZE_RANKS, tuple((tuple(terms), rank) for terms, rank in self.data["size_ranks"]),
        )
        # First match wins: a term that holds an earlier entry's term (「大特写」 holds 「特写」) would be
        # claimed by that earlier entry and never reached, so the longer term has to come first.
        entries = [[term.upper() for term in terms] for terms, _ in self.data["size_ranks"]]
        for later, terms in enumerate(entries):
            for longer in terms:
                for earlier in entries[:later]:
                    for shorter in earlier:
                        self.assertFalse(shorter != longer and shorter in longer, f"{longer!r} must come before {shorter!r}")
        self.assertEqual(storyboard_panels._size_rank("大特写"), 7)
        self.assertEqual(storyboard_panels._size_rank("中近景"), 4)
        self.assertEqual(storyboard_panels._size_rank("远中景"), 2)

    def test_camera_heights_try_low_before_high(self):
        # 「略仰俯拍」-style mixed angles have always read as low; the order is part of the meaning.
        self.assertEqual([height for height, _ in self.data["camera_heights"]], ["low", "high"])
        self.assertEqual(storyboard_panels._camera_height("仰俯"), "low")
        self.assertEqual(storyboard_panels._camera_height("略仰平视"), "eye")

    def test_the_patterns_compile_with_their_groups(self):
        self.assertEqual(storyboard_panels._FILM_SECONDS.groups, 2)
        self.assertTrue(storyboard_panels._FILM_SECONDS.flags & re.IGNORECASE)
        self.assertEqual(storyboard_panels._film_seconds({"duration": "生成 4 秒｜成片 1.8 秒"}), 1.8)
        self.assertEqual(storyboard_panels._norm("沈知微，跪在 堂中。"), "沈知微跪在堂中")
        self.assertEqual(storyboard_panels._SLIGHT.sub("", "略仰微俯"), "")

    def test_the_word_lists_are_the_table(self):
        self.assertEqual(storyboard_panels._STANDALONE, tuple(self.data["standalone_beats"]))
        self.assertEqual(storyboard_panels._REVERSE_SETUPS, tuple(self.data["reverse_setups"]))
        self.assertEqual(storyboard_panels._NO_LINE, tuple(self.data["no_line"]))
        self.assertEqual(storyboard_panels._VACANT, tuple(self.data["vacant_words"]))

    def test_a_merge_reads_as_before(self):
        def shot(number, desc, size, **extra):
            return {"shot_id": number, "desc": desc, "size": size, "angle": "平视", "characters": ["沈知微"], "duration": "4s", **extra}

        panels = storyboard_panels.consolidate_panels(
            [shot(1, "沈知微跪在堂中", "中景", motion="缓慢推近", sound="风声", dialogue="无", narrative_purpose="铺垫"),
             shot(2, "她抬眼", "近景", sound="心跳", dialogue="沈知微：是我。", narrative_purpose="蓄力")],
            video_model="seedance2.5",
        )
        self.assertEqual(len(panels), 1)
        self.assertEqual(panels[0]["desc"], "沈知微跪在堂中；随后她抬眼")
        self.assertEqual(panels[0]["motion"], "缓慢推近，随后推近至近景")
        self.assertEqual(panels[0]["sound"], "风声；心跳")
        self.assertEqual(panels[0]["dialogue"], "沈知微：是我。")
        self.assertEqual(panels[0]["narrative_purpose"], "铺垫→蓄力")

    def test_a_reworded_joiner_reaches_the_merge(self):
        def change(table):
            table["joiners"]["desc"] = "，接着"

        shots = [{"shot_id": n, "desc": d, "size": "中景", "characters": ["甲"], "duration": "2s"} for n, d in ((1, "甲坐下"), (2, "甲起身"))]
        with _reworded("storyboard_panels", change):
            panels = storyboard_panels.consolidate_panels(shots)
        self.assertEqual(panels[0]["desc"], "甲坐下，接着甲起身")


if __name__ == "__main__":
    unittest.main()
