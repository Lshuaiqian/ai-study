"""笔记整理的单测（纯逻辑，不联网）。

运行：python -m unittest discover -s study/tests
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notedoctor.tidier import (AI_END, AI_HEADING, AI_START,        # noqa: E402
                               HISTORY_HEADING, QUIZ_END, QUIZ_HEADING,
                               QUIZ_START, USER_HEADING, compose,
                               compose_quiz, compose_rollback,
                               coverage_ratio, extract_user_notes,
                               note_dimension, save_version, soft_tidy,
                               split_zones, user_notes_clean, user_substance,
                               write_state)

USER_BODY = """### 1. 我学到的（用自己的话）

HTTP 是无状态协议，状态码 200 表示成功，403 是拒绝执行。

### 2. 作业记录

爬虫 1 做完了。

### 3. 踩到的坑

一开始不知道 429 要退避。
"""


def note_with(ai_block="", history=""):
    parts = [
        "# F2 · 网络爬虫与数据分析",
        "",
        "## ⚡ 你的起点",
        "",
        "已具备 3/9 个知识点。",
        "",
        "## 📋 考核要求",
        "",
        "### 作业清单",
        "",
        "- [ ] `t2-1` 爬取福大教务通知",
        "",
        "---",
        "",
        USER_HEADING,
        "",
        USER_BODY.rstrip(),
    ]
    if ai_block:
        parts += ["", "---", "", ai_block]
    if history:
        parts += ["", "---", "", history]
    return "\n".join(parts) + "\n"


FEEDBACK = {
    "system_title": "网络爬虫·请求与解析",
    "theme": "HTTP 请求与反爬处理",
    "preview": ["状态码语义", "限速与退避", "robots.txt"],
    "coverage": [{"id": "K1", "status": "covered", "why": "讲清了状态码"},
                 {"id": "K2", "status": "partial", "why": "没提 Session"},
                 {"id": "K3", "status": "missing", "why": "没写解析"}],
    "glossary": [{"term": "幂等", "def": "多次执行结果一致"}],
    "todo": ["补 HTML 解析"],
    "errors": [],
    "uncertain": [],
    "summary": "主干清楚，解析那块要补。",
}


class TestSplitZones(unittest.TestCase):

    def test_splits_user_section(self):
        z = split_zones(note_with())
        self.assertIn(USER_HEADING, z["user"])
        self.assertIn("HTTP 是无状态协议", z["user"])
        self.assertNotIn("考核要求", z["user"])
        self.assertIn("考核要求", z["skeleton"])
        self.assertFalse(z["has_ai"])

    def test_splits_ai_and_history(self):
        ai = f"{AI_HEADING}\n\n{AI_START} ts=x -->\n旧整理\n{AI_END}"
        hist = f"{HISTORY_HEADING}\n\n- `x`　覆盖 50%"
        z = split_zones(note_with(ai, hist))
        self.assertTrue(z["has_ai"])
        self.assertIn("旧整理", z["ai"])
        self.assertIn(HISTORY_HEADING, z["after"])
        self.assertNotIn("旧整理", z["user"])

    def test_note_without_user_heading(self):
        z = split_zones("# 标题\n\n## 📋 考核要求\n\n随便写点")
        self.assertEqual(z["user"], "")
        self.assertIn("考核要求", z["skeleton"])

    def test_empty_text(self):
        z = split_zones("")
        self.assertEqual(z["user"], "")
        self.assertFalse(z["has_ai"])


class TestExtractUserNotes(unittest.TestCase):

    def test_takes_only_user_section(self):
        got = extract_user_notes(note_with())
        self.assertIn("HTTP 是无状态协议", got)
        self.assertNotIn("考核要求", got)
        self.assertNotIn("- [ ] `t2-1`", got)

    def test_excludes_ai_block(self):
        ai = f"{AI_HEADING}\n\n{AI_START} ts=x -->\nAI 写的\n{AI_END}"
        got = extract_user_notes(note_with(ai))
        self.assertNotIn("AI 写的", got)

    def test_legacy_note_without_markers_returns_text(self):
        got = extract_user_notes("# 标题\n\n我随手写的笔记")
        self.assertIn("我随手写的笔记", got)


class TestCompose(unittest.TestCase):
    """核心：多次整理**不是覆写**——用户正文永不动，AI 区整块替换，历史只追加。"""

    def test_first_tidy_adds_ai_block_and_history(self):
        new = compose(note_with(), "# F2\n\n整理后的正文", FEEDBACK, ts="2026-01-01 10:00")
        self.assertIn(AI_HEADING, new)
        self.assertIn("整理后的正文", new)
        self.assertIn(HISTORY_HEADING, new)
        self.assertIn("2026-01-01 10:00", new)
        self.assertTrue(new.rstrip().endswith("|") or "覆盖" in new)

    def test_user_content_is_never_touched(self):
        new = compose(note_with(), "整理稿 v1", FEEDBACK, ts="t1")
        self.assertIn("HTTP 是无状态协议", new)
        self.assertIn("一开始不知道 429 要退避", new)
        self.assertIn("爬虫 1 做完了", new)

    def test_second_tidy_replaces_ai_block_instead_of_appending(self):
        v1 = compose(note_with(), "整理稿 v1", FEEDBACK, ts="t1")
        v2 = compose(v1, "整理稿 v2", FEEDBACK, ts="t2")
        self.assertIn("整理稿 v2", v2)
        self.assertNotIn("整理稿 v1", v2)          # 旧 AI 区被替换，不是叠加
        self.assertEqual(v2.count(AI_START), 1)     # 只有一个 AI 区
        self.assertEqual(v2.count(AI_END), 1)

    def test_history_is_append_only(self):
        v1 = compose(note_with(), "整理稿 v1", FEEDBACK, ts="t1")
        v2 = compose(v1, "整理稿 v2", FEEDBACK, ts="t2")
        self.assertIn("t1", v2)                     # 第一次的记录还在
        self.assertIn("t2", v2)
        self.assertEqual(v2.count(HISTORY_HEADING), 1)

    def test_same_timestamp_not_duplicated_in_history(self):
        v1 = compose(note_with(), "整理稿 v1", FEEDBACK, ts="t1")
        v2 = compose(v1, "整理稿 v2", FEEDBACK, ts="t1")
        self.assertEqual(v2.count("- `t1`"), 1)

    def test_user_section_survives_three_rounds(self):
        text = note_with()
        for i in range(3):
            text = compose(text, f"整理稿 v{i}", FEEDBACK, ts=f"t{i}")
        self.assertIn("HTTP 是无状态协议", text)
        self.assertIn("爬虫 1 做完了", text)
        self.assertEqual(text.count(AI_HEADING), 1)

    def test_ai_block_mentions_it_will_be_replaced(self):
        new = compose(note_with(), "x", FEEDBACK, ts="t")
        self.assertIn("整块替换", new)

    def test_missing_system_title_is_tolerated(self):
        new = compose(note_with(), "x", {"coverage": []}, ts="t")
        self.assertIn(AI_HEADING, new)

    def test_user_zone_is_byte_identical_after_many_rounds(self):
        """回归：分隔线曾被算进用户区，每整理一次就多沉淀一条 ---。"""
        baseline = extract_user_notes(note_with())
        text = note_with()
        for i in range(5):
            text = compose(text, f"整理稿 v{i}", FEEDBACK, ts=f"t{i}")
        self.assertEqual(extract_user_notes(text), baseline)
        self.assertNotIn("---\n\n---", text)

    def test_history_separator_does_not_accumulate_either(self):
        once = compose(note_with(), "整理稿", FEEDBACK, ts="t0")
        text = once
        for i in range(1, 4):
            text = compose(text, "整理稿", FEEDBACK, ts=f"t{i}")
        self.assertEqual(text.count(HISTORY_HEADING), 1)
        # 结构分隔线跨轮稳定，不随整理次数增长
        self.assertEqual(text.count("---"), once.count("---"),
                         "分隔线从 %d 涨到 %d" % (once.count("---"), text.count("---")))


class TestQuizZone(unittest.TestCase):
    """质询区与整理区并列：各自整块替换，互不吞并，也不无脑追加。"""

    def quiz_block(self, ts="q1", body="质询结论 v1"):
        return (f"{QUIZ_HEADING}\n\n<!-- quiz:start ts={ts} -->\n"
                f"> 本次质询于 {ts}\n\n{body}\n{QUIZ_END}")

    def test_split_recognizes_quiz_and_keeps_it_out_of_user_zone(self):
        text = note_with(ai_block=f"{AI_HEADING}\n\n{AI_START} ts=x -->\n稿\n{AI_END}",
                         history=f"{QUIZ_HEADING}\n\n{QUIZ_START} ts=q -->\n问\n{QUIZ_END}")
        z = split_zones(text)
        self.assertTrue(z["has_quiz"])
        self.assertIn("问", z["quiz"])
        self.assertNotIn("问", z["user"])
        self.assertNotIn(QUIZ_HEADING, z["user"])

    def test_tidy_does_not_wipe_quiz_zone(self):
        text = note_with() + "\n\n---\n\n" + self.quiz_block()
        out = compose(text, "整理稿", FEEDBACK, ts="t1")
        self.assertIn("质询结论 v1", out)
        self.assertEqual(out.count(QUIZ_HEADING), 1)
        self.assertIn("整理稿", out)

    def test_quiz_does_not_wipe_tidy_zone(self):
        v1 = compose(note_with(), "整理稿 v1", FEEDBACK, ts="t1")
        out = compose_quiz(v1, "质询结论", ts="q1", percent=0.44)
        self.assertIn("整理稿 v1", out)
        self.assertIn("质询结论", out)
        self.assertIn("44%", out)

    def test_second_quiz_replaces_instead_of_appending(self):
        base = compose(note_with(), "整理稿", FEEDBACK, ts="t1")
        q1 = compose_quiz(base, "质询结论 v1", ts="q1")
        q2 = compose_quiz(q1, "质询结论 v2", ts="q2")
        self.assertIn("质询结论 v2", q2)
        self.assertNotIn("质询结论 v1", q2)
        self.assertEqual(q2.count(QUIZ_HEADING), 1)
        self.assertEqual(q2.count(QUIZ_START), 1)
        self.assertEqual(q2.count(QUIZ_END), 1)

    def test_five_rounds_of_alternating_ops_stay_stable(self):
        base = extract_user_notes(note_with())
        text = note_with()
        for i in range(5):
            text = compose(text, f"整理稿 v{i}", FEEDBACK, ts=f"t{i}")
            text = compose_quiz(text, f"质询 v{i}", ts=f"q{i}")
        self.assertEqual(extract_user_notes(text), base)
        self.assertEqual(text.count(AI_HEADING), 1)
        self.assertEqual(text.count(QUIZ_HEADING), 1)
        self.assertEqual(text.count(HISTORY_HEADING), 1)
        self.assertIn("整理稿 v4", text)
        self.assertIn("质询 v4", text)

    def test_separator_count_stable_across_rounds(self):
        once = compose_quiz(compose(note_with(), "整理稿", FEEDBACK, ts="t0"),
                            "质询", ts="q0")
        text = once
        for i in range(1, 4):
            text = compose(text, "整理稿", FEEDBACK, ts=f"t{i}")
            text = compose_quiz(text, "质询", ts=f"q{i}")
        self.assertEqual(text.count("---"), once.count("---"),
                         "分隔线从 %d 涨到 %d" % (once.count("---"), text.count("---")))

    def test_rollback_keeps_quiz_zone(self):
        text = compose_quiz(compose(note_with(), "整理稿 v1", FEEDBACK, ts="t1"),
                            "质询结论", ts="q1")
        out = compose_rollback(text, "旧整理稿", "20260101-000000")
        self.assertIn("质询结论", out)
        self.assertIn("旧整理稿", out)
        self.assertIn("已回滚到", out)
        self.assertNotIn("整理稿 v1", out)


class TestSaveVersion(unittest.TestCase):
    """快照落盘：可回滚的前提是每一版都真的留下来了。"""

    def test_same_second_does_not_overwrite_previous(self):
        with tempfile.TemporaryDirectory() as d:
            p1 = save_version(d, "n1", "第一版")
            p2 = save_version(d, "n1", "第二版")
            self.assertNotEqual(p1, p2)
            files = os.listdir(os.path.dirname(p1))
            self.assertEqual(len(files), 2, files)
            self.assertIn("第一版", open(p1, encoding="utf-8").read())

    def test_keeps_only_most_recent(self):
        with tempfile.TemporaryDirectory() as d:
            save_version(d, "n1", "v0")
            for i in range(4):
                save_version(d, "n1", f"v{i + 1}", keep=3)
            files = sorted(os.listdir(os.path.join(d, "note_versions", "n1")))
            self.assertEqual(len(files), 3, files)

    def test_separate_notes_do_not_share_history(self):
        with tempfile.TemporaryDirectory() as d:
            save_version(d, "a", "甲的稿")
            save_version(d, "b", "乙的稿")
            self.assertIn("甲的稿", open(
                save_version(d, "a", "甲的稿2"), encoding="utf-8").read())
            self.assertNotIn("乙", open(
                os.path.join(d, "note_versions", "a", sorted(
                    os.listdir(os.path.join(d, "note_versions", "a")))[0]),
                encoding="utf-8").read())


class TestUserSubstance(unittest.TestCase):
    """脚手架模板有 200 来字，按字数判断会把"还没写"当成"有内容"。"""

    SCAFFOLD = """（写完后运行：`python study\\tools\\interrogate.py --course west2-f2`）

### 1. 我学到的（用自己的话）

<!-- 不要抄资料；写你真正理解了什么 -->

### 2. 作业记录

<!-- 每道作业：做了什么、结果如何、卡在哪 -->
"""

    def wrap(self, body):
        return f"# F2\n\n{USER_HEADING}\n\n{body}\n"

    def test_scaffold_template_has_no_substance(self):
        self.assertEqual(user_substance(self.wrap(self.SCAFFOLD)), "")

    def test_real_content_counts(self):
        got = user_substance(self.wrap(self.SCAFFOLD + "\nHTTP 是无状态协议。\n"))
        self.assertIn("HTTP 是无状态协议", got)

    def test_comments_are_stripped_from_what_is_sent_to_model(self):
        self.assertNotIn("不要抄资料", user_notes_clean(self.wrap(self.SCAFFOLD)))

    def test_parenthetical_written_by_user_is_kept(self):
        """只剥脚手架的提醒行，不误伤用户自己写的括号。"""
        got = user_substance(self.wrap(self.SCAFFOLD + "\n（这里我还是没懂）\n"))
        self.assertIn("这里我还是没懂", got)


class TestWriteState(unittest.TestCase):
    """反馈给 AI 的落点：只记录证据，不越权改判定。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def seed(self, atoms=None, lessons=None):
        with open(os.path.join(self.state, "mastery.json"), "w", encoding="utf-8") as f:
            json.dump({"atoms": atoms or {}, "lessons": lessons or {}}, f)

    def mastery(self):
        with open(os.path.join(self.state, "mastery.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_unknown_gap_becomes_unmet(self):
        self.seed()
        write_state(self.state, "west2-f0", "n1", FEEDBACK, "")
        rec = self.mastery()["atoms"]["west2-f0:K2"]
        self.assertFalse(rec["passed"])
        # 没有测量过就不写 mastery 这个键——不编数字，也别写 None
        self.assertNotIn("mastery", rec)
        self.assertTrue(rec["note_gap"])
        self.assertEqual(rec["stage"], 0)

    def test_placement_met_is_not_demoted(self):
        """placement 已判「已具备」的点：笔记没写也不许摘牌、不许编分数。"""
        self.seed()
        write_state(self.state, "west2-f0", "n1", FEEDBACK, "",
                    protected={"K2": "met", "K3": "met"})
        for kid in ("K2", "K3"):
            rec = self.mastery()["atoms"][f"west2-f0:{kid}"]
            self.assertTrue(rec["passed"], f"{kid} 被摘牌了")
            self.assertEqual(rec["mastery_source"], "placement-met")
            self.assertNotIn("mastery", rec)
            self.assertTrue(rec["recheck_due"])
            self.assertTrue(rec["review_queue"])

    def test_carried_over_gap_is_marked_as_carried(self):
        """挂账与已具备不是一回事：挂账要留痕，下一课开头必须复查。"""
        self.seed()
        write_state(self.state, "west2-f0", "n1", FEEDBACK, "",
                    protected={"K2": "carried_over"})
        rec = self.mastery()["atoms"]["west2-f0:K2"]
        self.assertTrue(rec["passed"])
        self.assertTrue(rec["carried_over"])
        self.assertEqual(rec["mastery_source"], "placement-carried_over")
        self.assertTrue(rec["recheck_due"])

    def test_plain_set_is_accepted_as_protection(self):
        self.seed()
        write_state(self.state, "west2-f0", "n1", FEEDBACK, "",
                    protected={"K2"})
        self.assertTrue(self.mastery()["atoms"]["west2-f0:K2"]["passed"])

    def test_placement_met_upgrades_an_existing_failed_atom(self):
        """回归：整理先写 passed=False，质询后跑时 placement 的证据必须把它提回来。

        只判"键不存在"不够——键已存在且为 False 的情况才是真实顺序。
        """
        self.seed(atoms={"west2-f0:K2": {"passed": False, "mastery": None,
                                         "source": "note-tidy", "stage": 0}})
        write_state(self.state, "west2-f0", "n1", FEEDBACK, "",
                    protected={"K2": "met"})
        rec = self.mastery()["atoms"]["west2-f0:K2"]
        self.assertTrue(rec["passed"], "placement 说已具备，却没提回来")
        self.assertEqual(rec["mastery_source"], "placement-met")
        self.assertNotIn("mastery", rec, "mastery=null 应被清掉")

    def test_evidence_free_atom_keeps_no_mastery_key(self):
        self.seed(atoms={"west2-f0:K3": {"passed": False, "mastery": None}})
        write_state(self.state, "west2-f0", "n1", FEEDBACK, "")
        self.assertNotIn("mastery", self.mastery()["atoms"]["west2-f0:K3"])

    def test_real_mastery_number_is_never_erased(self):
        self.seed(atoms={"west2-f0:K3": {"passed": False, "mastery": 0.62}})
        write_state(self.state, "west2-f0", "n1", FEEDBACK, "")
        self.assertEqual(self.mastery()["atoms"]["west2-f0:K3"]["mastery"], 0.62)

    def test_placement_protection_is_per_knowledge_point(self):
        self.seed()
        write_state(self.state, "west2-f0", "n1", FEEDBACK, "",
                    protected={"K2": "met"})
        m = self.mastery()
        self.assertTrue(m["atoms"]["west2-f0:K2"]["passed"])
        self.assertFalse(m["atoms"]["west2-f0:K3"]["passed"],
                         "不在保护集里的缺口仍应判为未达成")

    def test_passed_atom_is_not_demoted_by_missing_note(self):
        """笔记没写到 ≠ 没掌握：已通过的知识点只挂待复核，不摘牌。"""
        self.seed(atoms={"west2-f0:K2": {"passed": True, "mastery": 0.9}})
        write_state(self.state, "west2-f0", "n1", FEEDBACK, "")
        rec = self.mastery()["atoms"]["west2-f0:K2"]
        self.assertTrue(rec["passed"], "笔记缺失不该把已通过的知识点摘牌")
        self.assertEqual(rec["mastery"], 0.9)
        self.assertTrue(rec["review_queue"])
        self.assertTrue(rec["recheck_due"])
        self.assertEqual(rec["recheck_reason"], "笔记未覆盖：west2-f0")

    def test_covered_atom_is_not_touched(self):
        self.seed(atoms={"west2-f0:K1": {"passed": True, "mastery": 0.9}})
        write_state(self.state, "west2-f0", "n1", FEEDBACK, "")
        rec = self.mastery()["atoms"]["west2-f0:K1"]
        self.assertTrue(rec["passed"])
        self.assertNotIn("note_gap", rec)
        self.assertNotIn("recheck_due", rec)

    def test_passing_a_lesson_is_not_revoked_by_tidy(self):
        self.seed(lessons={"west2-f0": {"passed": True, "dims": {
            "code": 0.9, "quiz": 0.9, "transfer": 0.9, "note": 0.9}}})
        write_state(self.state, "west2-f0", "n1", FEEDBACK, "")
        entry = self.mastery()["lessons"]["west2-f0"]
        self.assertTrue(entry["passed"], "整理笔记不该把已通过的课摘牌")
        self.assertEqual(entry["dims"]["note_gaps"], 2)   # K2 partial + K3 missing

    def test_records_note_dimension_and_event(self):
        self.seed()
        payload, queued = write_state(self.state, "west2-f0", "n1", FEEDBACK, "/v/1.md")
        self.assertEqual(queued, ["west2-f0:K2", "west2-f0:K3"])
        self.assertGreater(payload["note_dimension"], 0.0)
        self.assertEqual(payload["coverage_ratio"], 0.5)
        with open(os.path.join(self.state, "events.jsonl"), encoding="utf-8") as f:
            events = f.read()
        self.assertIn("note_review", events)
        self.assertTrue(os.path.isfile(
            os.path.join(self.state, "findings", "west2-f0-tidy.json")))

    def test_no_coverage_means_no_fabricated_score(self):
        """没有覆盖信息时 note 维度必须是 0，而不是"没错所以满分"。"""
        self.seed()
        payload, _ = write_state(self.state, "west2-f0", "n1",
                                 {"coverage": [], "errors": []}, "")
        self.assertEqual(payload["note_dimension"], 0.0)


class TestCoverage(unittest.TestCase):

    def test_weighted_ratio(self):
        # covered 1 + partial 0.5 + missing 0 = 1.5 / 3
        self.assertAlmostEqual(coverage_ratio(FEEDBACK), 0.5)

    def test_empty(self):
        self.assertEqual(coverage_ratio({}), 0.0)

    def test_all_covered(self):
        self.assertEqual(coverage_ratio(
            {"coverage": [{"status": "covered"}, {"status": "covered"}]}), 1.0)


class TestNoteDimension(unittest.TestCase):

    def test_within_range(self):
        v = note_dimension(FEEDBACK)
        self.assertGreaterEqual(v, 0.0)
        self.assertLessEqual(v, 1.0)

    def test_errors_lower_accuracy(self):
        good = note_dimension(FEEDBACK)
        bad = note_dimension({**FEEDBACK, "errors": [{"quote": "x"}]})
        self.assertLess(bad, good)

    def test_empty_feedback_is_low(self):
        self.assertLess(note_dimension({}), 0.5)


class TestSoftTidy(unittest.TestCase):

    def test_normalizes_heading_spacing(self):
        self.assertIn("# 标题", soft_tidy("###标题"))

    def test_collapses_blank_lines(self):
        out = soft_tidy("a\n\n\n\n\nb")
        self.assertNotIn("\n\n\n", out)

    def test_strips_trailing_whitespace(self):
        self.assertNotIn("a   \n", soft_tidy("a   \nb"))

    def test_keeps_code_fence_content_verbatim(self):
        src = "```python\nx = 1   \nif x:\n\n\n    pass\n```"
        out = soft_tidy(src)
        self.assertIn("x = 1   ", out)          # 代码块内不动行尾空白
        self.assertIn("if x:\n\n\n    pass", out)

    def test_blank_line_before_heading(self):
        out = soft_tidy("正文\n## 小节\n内容")
        self.assertIn("正文\n\n## 小节", out)

    def test_does_not_change_words(self):
        src = "这是一段 中文  文本，里面 有 空格。"
        self.assertIn("这是一段 中文  文本，里面 有 空格。", soft_tidy(src))

    def test_empty_input(self):
        self.assertEqual(soft_tidy(""), "\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
