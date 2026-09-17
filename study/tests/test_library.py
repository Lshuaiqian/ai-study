"""学习库（知识原子）的单测（纯逻辑，不联网）。

运行：python -m unittest discover -s study/tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from library import (append_atoms, as_materials, cluster_duplicates,       # noqa: E402
                     course_view, dedupe, find_near_duplicates, global_stats,
                     load_atoms, make_atom_id, render_duplicates, set_status,
                     similarity, to_atoms, update_atom, validate,
                     verify_candidates)
from library.store import (STATUS_CONFIRMED, STATUS_PENDING,                # noqa: E402
                           STATUS_REJECTED)

MATERIAL = """robots.txt 是站点放在根目录下的文本文件，用 User-agent 和 Disallow 指令
声明哪些路径允许爬取。HTTP 429 表示请求过于频繁，应对方式是降低频率并使用指数退避重试。
requests.Session 会复用底层 TCP 连接，并在同一会话内自动保持 Cookie。
"""


def curriculums():
    return {
        "course_id": "py-agent-03",
        "title": "第 3 课 爬虫",
        "declares": {"knowledge": [
            {"id": "K1", "name": "爬虫流程", "level": "must"},
            {"id": "K3", "name": "礼貌爬取", "level": "must"},
            {"id": "K4", "name": "反爬初步", "level": "must"},
            {"id": "K6", "name": "BS 用法", "level": "should"},
        ]},
    }


class TestAtomId(unittest.TestCase):

    def test_deterministic(self):
        a = make_atom_id("c", "标题", "引文")
        self.assertEqual(a, make_atom_id("c", "标题", "引文"))

    def test_differs_by_content(self):
        self.assertNotEqual(make_atom_id("c", "标题", "引文A"),
                            make_atom_id("c", "标题", "引文B"))

    def test_prefix(self):
        self.assertTrue(make_atom_id("c", "t", "q").startswith("a_"))


class TestStore(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="study_lib_")
        self.path = os.path.join(self.dir, "atoms.jsonl")

    def _atom(self, aid="a_1", **kw):
        base = {"atom_id": aid, "type": "concept", "title": "T", "statement": "S",
                "course": "c", "source": {"kind": "material", "ref": "r",
                                          "verified": True},
                "status": STATUS_PENDING}
        base.update(kw)
        return base

    def test_append_and_load(self):
        append_atoms(self.path, [self._atom("a_1"), self._atom("a_2")])
        self.assertEqual(sorted(load_atoms(self.path)), ["a_1", "a_2"])

    def test_missing_file(self):
        self.assertEqual(load_atoms(os.path.join(self.dir, "no.jsonl")), {})

    def test_bad_line_skipped(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"atom_id":"a_1","status":"pending"}\n')
            f.write("坏行\n")
        self.assertEqual(len(load_atoms(self.path)), 1)

    def test_last_write_wins(self):
        append_atoms(self.path, [self._atom("a_1", status=STATUS_PENDING)])
        append_atoms(self.path, [self._atom("a_1", status=STATUS_CONFIRMED)])
        self.assertEqual(load_atoms(self.path)["a_1"]["status"], STATUS_CONFIRMED)

    def test_update_atom(self):
        append_atoms(self.path, [self._atom("a_1")])
        rec = update_atom(self.path, "a_1", mastery=0.5)
        self.assertEqual(rec["mastery"], 0.5)
        self.assertIn("updated_at", rec)
        self.assertEqual(load_atoms(self.path)["a_1"]["mastery"], 0.5)

    def test_update_missing_returns_none(self):
        self.assertIsNone(update_atom(self.path, "nope", mastery=1))

    def test_set_status(self):
        append_atoms(self.path, [self._atom("a_1"), self._atom("a_2")])
        changed = set_status(self.path, ["a_1", "nope"], STATUS_CONFIRMED)
        self.assertEqual(len(changed), 1)
        atoms = load_atoms(self.path)
        self.assertEqual(atoms["a_1"]["status"], STATUS_CONFIRMED)
        self.assertEqual(atoms["a_2"]["status"], STATUS_PENDING)


class TestValidate(unittest.TestCase):

    def _valid(self):
        return {"atom_id": "a_1", "type": "concept", "title": "T", "statement": "S",
                "source": {"kind": "material", "ref": "x.md#L1", "verified": True}}

    def test_valid(self):
        self.assertEqual(validate(self._valid()), [])

    def test_requires_ref(self):
        a = self._valid()
        a["source"]["ref"] = ""
        self.assertTrue(any("source.ref" in p for p in validate(a)))

    def test_requires_verified(self):
        a = self._valid()
        a["source"]["verified"] = False
        self.assertTrue(any("verified" in p for p in validate(a)))

    def test_rejects_bad_type(self):
        a = self._valid()
        a["type"] = "nonsense"
        self.assertTrue(any("type" in p for p in validate(a)))

    def test_requires_statement(self):
        a = self._valid()
        a["statement"] = "   "
        self.assertTrue(any("statement" in p for p in validate(a)))


class TestVerifyCandidates(unittest.TestCase):
    """这是 H1 假设的机械保障：出处不是模型说了算，是程序说了算。"""

    def test_exact_quote_passes(self):
        c = [{"title": "robots", "statement": "x",
              "quote": "robots.txt 是站点放在根目录下的文本文件"}]
        ok, bad = verify_candidates(c, MATERIAL)
        self.assertEqual(len(ok), 1)
        self.assertEqual(bad, [])

    def test_multiline_quote_with_whitespace_difference_passes(self):
        c = [{"title": "429", "statement": "x",
              "quote": "HTTP 429 表示请求过于频繁，\n应对方式是降低频率并使用指数退避重试"}]
        ok, _ = verify_candidates(c, MATERIAL)
        self.assertEqual(len(ok), 1)

    def test_fabricated_quote_rejected(self):
        c = [{"title": "假", "statement": "x",
              "quote": "robots.txt 规定违反者会被判刑三年"}]
        ok, bad = verify_candidates(c, MATERIAL)
        self.assertEqual(ok, [])
        self.assertIn("未在资料原文中找到", bad[0]["reason"])

    def test_too_short_quote_rejected(self):
        c = [{"title": "短", "statement": "x", "quote": "HTTP"}]
        ok, bad = verify_candidates(c, MATERIAL)
        self.assertEqual(ok, [])
        self.assertIn("引文过短", bad[0]["reason"])

    def test_missing_statement_rejected(self):
        c = [{"title": "无正文", "statement": " ", "quote": "requests.Session 会复用底层 TCP 连接"}]
        ok, bad = verify_candidates(c, MATERIAL)
        self.assertEqual(ok, [])
        self.assertIn("缺少 statement", bad[0]["reason"])

    def test_mixed_batch(self):
        c = [{"title": "ok", "statement": "s", "quote": "requests.Session 会复用底层 TCP 连接"},
             {"title": "bad", "statement": "s", "quote": "完全不存在的一句话在这里哦"}]
        ok, bad = verify_candidates(c, MATERIAL)
        self.assertEqual(len(ok), 1)
        self.assertEqual(len(bad), 1)


class TestToAtoms(unittest.TestCase):

    def test_produces_pending_verified_atoms(self):
        cands = [{"type": "pitfall", "title": "429", "statement": "S", "why": "W",
                  "quote": "HTTP 429 表示请求过于频繁，应对方式是降低频率并使用指数退避重试",
                  "knowledge_id": "K4"}]
        atoms = to_atoms(cands, "py-agent-03", source_kind="material",
                         source_ref="raw/a.md")
        a = atoms[0]
        self.assertEqual(a["status"], STATUS_PENDING)
        self.assertTrue(a["source"]["verified"])
        self.assertEqual(a["source"]["kind"], "material")
        self.assertEqual(a["knowledge_id"], "K4")
        self.assertEqual(a["course"], "py-agent-03")
        self.assertEqual(validate(a), [])

    def test_rejects_bad_source_kind(self):
        with self.assertRaises(ValueError):
            to_atoms([], "c", source_kind="nonsense")

    def test_dedupe_by_id(self):
        cands = [{"type": "concept", "title": "T", "statement": "S",
                  "quote": "requests.Session 会复用底层 TCP 连接"}]
        atoms = to_atoms(cands, "c", source_ref="r")
        fresh, dup = dedupe(atoms, {atoms[0]["atom_id"]: atoms[0]})
        self.assertEqual(fresh, [])
        self.assertEqual(len(dup), 1)
        fresh2, _ = dedupe(atoms, {})
        self.assertEqual(len(fresh2), 1)


class TestCourseView(unittest.TestCase):

    def _atoms(self):
        mk = lambda aid, kid, status=STATUS_CONFIRMED: {
            "atom_id": aid, "title": aid, "statement": "s", "course": "py-agent-03",
            "knowledge_id": kid, "status": status, "type": "concept",
            "source": {"kind": "material", "ref": "r", "verified": True}}
        return {"a_1": mk("a_1", "K1"), "a_2": mk("a_2", "K1"),
                "a_3": mk("a_3", "K3"), "a_4": mk("a_4", "", STATUS_CONFIRMED),
                "a_5": mk("a_5", "K4", STATUS_PENDING)}

    def test_coverage_counts_only_confirmed(self):
        v = course_view(curriculums(), self._atoms())
        # K1 ✅, K3 ✅, K4 只有 pending → 不算, K6 无
        self.assertEqual(v["must_total"], 3)
        self.assertEqual(v["must_covered"], 2)
        self.assertEqual(v["missing_must"], ["K4"])

    def test_include_pending(self):
        v = course_view(curriculums(), self._atoms(), include_pending=True)
        self.assertEqual(v["must_covered"], 3)

    def test_unmapped_listed(self):
        v = course_view(curriculums(), self._atoms())
        self.assertIn("a_4", v["unmapped"])

    def test_by_knowledge_groups(self):
        v = course_view(curriculums(), self._atoms())
        self.assertEqual(v["by_knowledge"]["K1"], ["a_1", "a_2"])

    def test_other_course_atoms_excluded(self):
        atoms = self._atoms()
        atoms["a_x"] = {"atom_id": "a_x", "title": "x", "statement": "s",
                        "course": "py-agent-99", "knowledge_id": "K1",
                        "status": STATUS_CONFIRMED, "type": "concept",
                        "source": {"kind": "material", "ref": "r", "verified": True}}
        v = course_view(curriculums(), atoms)
        self.assertNotIn("a_x", v["by_knowledge"].get("K1", []))

    def test_as_materials_skips_unconfirmed(self):
        mats = as_materials(self._atoms(), "py-agent-03")
        ids = [m["id"] for m in mats]
        self.assertIn("a_1", ids)
        self.assertNotIn("a_5", ids)
        self.assertTrue(all(m["text"] for m in mats))

    def test_authority_by_source_kind(self):
        """从学生自己的笔记抽的原子是 derived，不能作判错依据。"""
        cands = [{"type": "concept", "title": "T", "statement": "S",
                  "quote": "requests.Session 会复用底层 TCP 连接"}]
        a_seed_like = to_atoms(cands, "c", source_kind="material", source_ref="r")[0]
        a_derived = to_atoms(cands, "c", source_kind="note", source_ref="r")[0]
        self.assertEqual(a_seed_like["source"]["authority"], "authoritative")
        self.assertEqual(a_derived["source"]["authority"], "derived")

    def test_as_materials_authoritative_only_filters(self):
        atoms = self._atoms()
        atoms["a_1"]["source"]["authority"] = "authoritative"
        atoms["a_2"]["source"]["authority"] = "derived"
        mats = as_materials(atoms, "py-agent-03", authoritative_only=True)
        ids = [m["id"] for m in mats]
        self.assertIn("a_1", ids)
        self.assertNotIn("a_2", ids)

    def test_global_stats(self):
        s = global_stats(self._atoms())
        self.assertIn("知识库总计 5 个原子", s)


class TestNearDuplicates(unittest.TestCase):
    """抽取的两个相反失败模式：抽太松（叙事性内容）和抽太碎（近似重复）。
    这里锁住"抽太碎"的检测能力。"""

    def _atom(self, aid, title, statement=""):
        return {"atom_id": aid, "title": title, "statement": statement,
                "course": "c", "status": STATUS_CONFIRMED, "type": "concept",
                "source": {"kind": "material", "ref": "r", "verified": True}}

    def test_identical_scores_one(self):
        self.assertEqual(similarity("限速逻辑与站点无关", "限速逻辑与站点无关"), 1.0)

    def test_unrelated_scores_low(self):
        self.assertLess(similarity("限速逻辑与站点无关", "HTTP 429 表示请求过于频繁"), 0.3)

    def test_whitespace_insensitive(self):
        self.assertEqual(similarity("A B C 限速", "ABC限速"), 1.0)

    def test_finds_near_duplicate_pair(self):
        atoms = {
            "a_1": self._atom("a_1", "限速逻辑与站点无关", "polite_wait 的限速逻辑可以跨站点复用"),
            "a_2": self._atom("a_2", "限速处理与站点无关", "polite_wait 的限速逻辑可以跨站点复用"),
            "a_3": self._atom("a_3", "HTTP 429 语义", "请求过于频繁时应当降速并退避重试"),
        }
        pairs = find_near_duplicates(atoms)
        keys = {(p["a"], p["b"]) for p in pairs}
        self.assertIn(("a_1", "a_2"), keys)
        self.assertNotIn(("a_1", "a_3"), keys)

    def test_clusters_group_transitively(self):
        atoms = {
            "a_1": self._atom("a_1", "落盘与站点无关", "save_json 落盘方式可跨站点复用"),
            "a_2": self._atom("a_2", "落盘方式与站点无关", "save_json 落盘方式可跨站点复用"),
            "a_3": self._atom("a_3", "落盘逻辑与站点无关", "save_json 落盘方式可以跨站点复用"),
            "a_4": self._atom("a_4", "完全无关的一条", "今天天气不错适合出门散步"),
        }
        groups = cluster_duplicates(atoms)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0], ["a_1", "a_2", "a_3"])

    def test_no_pairs_when_all_distinct(self):
        # 注意：测试数据必须真的互不相似。用同一模板拼出来的标题
        # （例如都叫"完全不同的主题编号N"）会被正确判为近似重复——
        # 第一版测试就是栽在这里。
        distinct = [
            ("HTTP 状态码语义", "403 是拒绝执行，429 是频率超限"),
            ("robots.txt 的作用", "站点根目录声明爬虫可访问范围"),
            ("requests.Session 复用", "同一会话保持 Cookie 并复用 TCP 连接"),
            ("CSV 落盘编码", "写中文 CSV 要显式指定 utf-8"),
        ]
        atoms = {f"a_{i}": self._atom(f"a_{i}", t, s)
                 for i, (t, s) in enumerate(distinct)}
        self.assertEqual(find_near_duplicates(atoms), [])

    def test_course_filter(self):
        atoms = {
            "a_1": self._atom("a_1", "限速逻辑与站点无关", "polite_wait 可复用"),
            "a_2": self._atom("a_2", "限速逻辑与站点无关", "polite_wait 可复用"),
        }
        atoms["a_3"] = {**self._atom("a_3", "限速逻辑与站点无关", "polite_wait 可复用"),
                        "course": "other"}
        pairs = find_near_duplicates(atoms, course_id="c")
        self.assertEqual(len(pairs), 1)

    def test_render(self):
        self.assertIn("未发现", render_duplicates([]))
        pairs = [{"a": "a_1", "b": "a_2", "score": 0.9,
                  "a_title": "T1", "b_title": "T2"}]
        self.assertIn("建议人工合并", render_duplicates(pairs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
