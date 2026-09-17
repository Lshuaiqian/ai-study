"""一键整理（AI 质询）的单测（纯逻辑，不联网）。

运行：python -m unittest discover -s study/tests
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notedoctor.doctor import check_coverage                  # noqa: E402
from notedoctor.interrogator import (DEFAULT_SKIP_THRESHOLD,    # noqa: E402
                                     SCORE_WEIGHTS, empty_interrogation,
                                     interrogate, mastery_ratio, prior_gaps,
                                     render_prior, render_report, score,
                                     split_note, task_progress, write_state)

NOTE = """# F2 · 网络爬虫与数据分析

## 📋 考核要求

### 作业清单

- [x] `t2-1` **爬虫 1** — 抓福大教务通知
- [ ] `t2-2` **爬虫 2** — Selenium 爬知乎
- [ ] `t2-3` **爬虫 3** — 抓接口爬开源之夏

### 本课知识点

- [必会] `net.http` HTTP 方法、状态码与请求头

---

## ✍️ 我的笔记

### 1. 我学到的
HTTP 是无状态协议，状态码 200 表示成功，403 是拒绝，429 是频率超限。
用 requests 发请求，Session 可以复用连接并保持 cookie。
限速用 time.sleep，并且要先看 robots.txt，设置 User-Agent。
"""


def curriculum():
    return {
        "course_id": "west2-f2",
        "title": "Foundation Task 2 · 网络爬虫与数据分析",
        "declares": {
            "knowledge": [
                {"id": "K1", "name": "HTTP 方法、状态码与请求头", "level": "must",
                 "keywords": [["HTTP"], ["状态码", "200", "403", "429"], ["请求头", "Header", "User-Agent"]]},
                {"id": "K2", "name": "requests 用法与会话复用", "level": "must",
                 "keywords": [["requests"], ["Session", "会话", "cookie"]]},
                {"id": "K3", "name": "礼貌爬取", "level": "must",
                 "keywords": [["robots"], ["限速", "sleep", "频率"]]},
                {"id": "K4", "name": "Pandas 基础", "level": "must",
                 "keywords": [["pandas", "DataFrame"], ["分组", "groupby"]]},
            ]
        },
    }


class TestPriorGaps(unittest.TestCase):
    """整理的缺口 → 下一轮质询。这是「反馈给 AI」的入口，断了闭环就断在这。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def write_tidy(self, course_id, payload):
        d = os.path.join(self.state, "findings")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{course_id}-tidy.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

    TIDY = {
        "tidied_at": "2026-09-16T20:52:58",
        "coverage_ratio": 0.61,
        "coverage": [{"id": "K1", "status": "covered", "why": "讲清了"},
                     {"id": "K2", "status": "partial", "why": "没提 Session"},
                     {"id": "K3", "status": "missing", "why": "完全没提 robots"}],
        "todo": ["补 IDE 配置"],
        "uncertain": [{"quote": "8GB 不加空格", "reason": "可能记错"}],
        "summary": "主干清楚。",
    }

    def test_no_tidy_yet_returns_none(self):
        self.assertIsNone(prior_gaps(self.state, "west2-f2"))

    def test_reads_gaps_only(self):
        self.write_tidy("west2-f2", self.TIDY)
        prior = prior_gaps(self.state, "west2-f2")
        self.assertEqual([g["id"] for g in prior["gaps"]], ["K2", "K3"])
        self.assertEqual(prior["gaps"][0]["why"], "没提 Session")

    def test_other_course_does_not_leak(self):
        self.write_tidy("west2-f0", self.TIDY)
        self.assertIsNone(prior_gaps(self.state, "west2-f2"))

    def test_render_prior_marks_it_as_reference_not_verdict(self):
        """带着缺口去质询，但不能因此放行——必须让模型独立判断。"""
        self.write_tidy("west2-f2", self.TIDY)
        block = render_prior(prior_gaps(self.state, "west2-f2"))
        self.assertIn("K2", block)
        self.assertIn("没提 Session", block)
        self.assertIn("补 IDE 配置", block)
        self.assertIn("独立判断", block)
        self.assertIn("partial/missing", block)

    def test_render_prior_empty_when_no_history(self):
        self.assertEqual(render_prior(None), "")
        self.assertEqual(render_prior({"gaps": [], "todo": []}), "")

    def test_interrogate_prompt_carries_the_gaps(self):
        """端到端的一环：缺口必须真的进到送给模型的提示词里。"""
        captured = {}

        class FakeLLM:
            def chat(self, system, user, **kw):
                captured["user"] = user
                return {"verdicts": [{"id": "K2", "verdict": "partial", "why": "还是没讲 Session"}],
                        "questions": [], "errors": [], "uncertain": [],
                        "todo": [], "summary": "ok"}

        self.write_tidy("west2-f2", self.TIDY)
        prior = prior_gaps(self.state, "west2-f2")
        progress = task_progress(split_note(NOTE)[0])
        out = interrogate(FakeLLM(), curriculum(), "我的笔记正文", progress, prior=prior)
        self.assertIn("上一轮一键整理的缺口", captured["user"])
        self.assertIn("没提 Session", captured["user"])
        self.assertIn("我的笔记正文", captured["user"])
        self.assertEqual(out["verdicts"][0]["verdict"], "partial")

    def test_interrogate_without_prior_still_works(self):
        captured = {}

        class FakeLLM:
            def chat(self, system, user, **kw):
                captured["user"] = user
                return {"verdicts": [], "questions": [], "errors": [],
                        "uncertain": [], "todo": [], "summary": ""}

        progress = task_progress(split_note(NOTE)[0])
        interrogate(FakeLLM(), curriculum(), "正文", progress, prior=None)
        self.assertNotIn("上一轮", captured["user"])
        self.assertIn("正文", captured["user"])


class TestWriteState(unittest.TestCase):
    """质询结论进掌握度：写证据，不越权改判定。"""

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

    def result(self, percent=0.82, can_skip=True):
        return {"percent": percent, "level": "已达标", "can_skip": can_skip,
                "threshold": 0.70, "parts": {"coverage": 1.0, "mastery": 0.75,
                                             "tasks": 1.0},
                "coverage_detail": {"must_cover_ratio": 1.0, "must_missing": []},
                "blockers": []}

    INTER = {"verdicts": [{"id": "K1", "verdict": "pass", "why": "讲清了"},
                          {"id": "K2", "verdict": "partial", "why": "没讲 Session"},
                          {"id": "K3", "verdict": "missing", "why": "没提 robots"}],
             "questions": [{"for": "K2", "question": "Session 解决了什么问题？"}],
             "errors": [], "uncertain": [], "todo": ["补 robots"], "summary": "还行。"}

    def test_writes_findings_and_verdicts(self):
        self.seed()
        payload, queued = write_state(self.state, "west2-f2", "n1",
                                      self.result(), self.INTER)
        self.assertEqual(queued, ["west2-f2:K2", "west2-f2:K3"])
        self.assertEqual(payload["percent"], 0.82)
        with open(os.path.join(self.state, "findings",
                               "west2-f2-interrogate.json"), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(len(saved["verdicts"]), 3)
        self.assertIn("Session 解决了什么问题", json.dumps(saved, ensure_ascii=False))

    def test_pass_verdict_does_not_enter_queue(self):
        self.seed()
        write_state(self.state, "west2-f2", "n1", self.result(), self.INTER)
        self.assertNotIn("west2-f2:K1", self.mastery()["atoms"])

    def test_passed_atom_is_not_demoted(self):
        """质询说'没讲到' ≠ 没掌握：已通过的只挂复核，不摘牌。"""
        self.seed(atoms={"west2-f2:K2": {"passed": True, "mastery": 0.91}})
        write_state(self.state, "west2-f2", "n1", self.result(), self.INTER)
        rec = self.mastery()["atoms"]["west2-f2:K2"]
        self.assertTrue(rec["passed"])
        self.assertEqual(rec["mastery"], 0.91)
        self.assertTrue(rec["recheck_due"])
        self.assertEqual(rec["source"], "note-interrogate")

    def test_no_evidence_atom_becomes_unmet(self):
        self.seed()
        write_state(self.state, "west2-f2", "n1", self.result(), self.INTER)
        rec = self.mastery()["atoms"]["west2-f2:K3"]
        self.assertFalse(rec["passed"])
        self.assertNotIn("mastery", rec)

    def test_placement_met_is_not_demoted(self):
        """placement 判「已具备/挂账」的点，质询说没写到也不摘牌。"""
        self.seed()
        write_state(self.state, "west2-f2", "n1", self.result(), self.INTER,
                    protected={"K2": "met", "K3": "carried_over"})
        m = self.mastery()
        self.assertTrue(m["atoms"]["west2-f2:K2"]["passed"], "K2 被摘牌了")
        self.assertTrue(m["atoms"]["west2-f2:K3"]["passed"], "K3 被摘牌了")
        self.assertTrue(m["atoms"]["west2-f2:K3"]["carried_over"])
        self.assertTrue(m["atoms"]["west2-f2:K2"]["recheck_due"])
        self.assertEqual(m["atoms"]["west2-f2:K2"]["mastery_source"], "placement-met")

    def test_records_percent_without_revoking_lesson_pass(self):
        self.seed(lessons={"west2-f2": {"passed": True, "dims": {
            "code": 0.9, "quiz": 0.9, "note": 0.9, "transfer": 0.9}}})
        write_state(self.state, "west2-f2", "n1", self.result(), self.INTER)
        entry = self.mastery()["lessons"]["west2-f2"]
        self.assertTrue(entry["passed"], "质询不该把已通过的课摘牌")
        self.assertEqual(entry["interrogation_percent"], 0.82)
        self.assertTrue(entry["can_skip"])

    def test_can_skip_false_is_recorded(self):
        self.seed()
        write_state(self.state, "west2-f2", "n1",
                    self.result(percent=0.44, can_skip=False), self.INTER)
        self.assertFalse(self.mastery()["lessons"]["west2-f2"]["can_skip"])

    def test_event_appended(self):
        self.seed()
        write_state(self.state, "west2-f2", "n1", self.result(), self.INTER)
        with open(os.path.join(self.state, "events.jsonl"), encoding="utf-8") as f:
            events = f.read()
        self.assertIn("interrogation", events)
        self.assertIn("west2-f2", events)

    def test_does_not_touch_other_courses(self):
        self.seed(atoms={"west2-f0:K1": {"passed": True, "mastery": 0.9}})
        write_state(self.state, "west2-f2", "n1", self.result(), self.INTER)
        m = self.mastery()
        self.assertEqual(m["atoms"]["west2-f0:K1"]["mastery"], 0.9)
        self.assertNotIn("recheck_due", m["atoms"]["west2-f0:K1"])


class TestSplitNote(unittest.TestCase):

    def test_splits_at_notes_heading(self):
        req, notes = split_note(NOTE)
        self.assertIn("考核要求", req)
        self.assertNotIn("我学到的", req)
        self.assertIn("我学到的", notes)
        self.assertIn("robots.txt", notes)

    def test_without_heading_everything_is_requirements(self):
        req, notes = split_note("# 只有要求\n没有笔记段")
        self.assertIn("只有要求", req)
        self.assertEqual(notes, "")

    def test_empty_text(self):
        self.assertEqual(split_note(""), ("", ""))

    def test_ai_tidy_block_is_not_treated_as_student_notes(self):
        """回归：AI 整理稿曾被当成学生笔记，于是 AI 给自己打分。"""
        text = NOTE + ("\n\n---\n\n## 🤖 AI 整理\n\n<!-- tidy:start ts=x -->\n"
                       "## 一、HTTP 与 requests\n\n- 状态码 200/403/429 语义。\n"
                       "Session 复用连接、保持 cookie。robots.txt 与限速。\n"
                       "Pandas DataFrame 与 groupby 分组统计。\n"
                       "<!-- tidy:end -->\n\n---\n\n## 📚 整理历史\n\n- `x` 覆盖 100%\n")
        _, notes = split_note(text)
        self.assertIn("robots.txt", notes)              # 学生自己写的那段还在
        self.assertNotIn("AI 整理", notes)
        self.assertNotIn("整理历史", notes)
        self.assertNotIn("Pandas DataFrame", notes)     # AI 补写的内容不算数
        self.assertNotIn("tidy:start", notes)

    def test_coverage_does_not_jump_after_tidy(self):
        """整理一次不该让覆盖率虚高——那是 AI 写的字，不是学生学会的。"""
        req, notes_before = split_note(NOTE)
        text = NOTE + ("\n\n---\n\n## 🤖 AI 整理\n\n<!-- tidy:start ts=x -->\n"
                       "Pandas DataFrame 与 groupby 分组统计，"
                       "robots.txt 与限速 sleep，requests 与 Session。\n"
                       "<!-- tidy:end -->\n")
        _, notes_after = split_note(text)
        self.assertNotIn("Pandas DataFrame", notes_after)
        cov_before = check_coverage(curriculum()["declares"], notes_before)
        cov_after = check_coverage(curriculum()["declares"], notes_after)
        self.assertEqual(cov_before["must_cover_ratio"], cov_after["must_cover_ratio"])


class TestTaskProgress(unittest.TestCase):

    def test_counts_checked_and_unchecked(self):
        p = task_progress(NOTE)
        self.assertEqual(p["total"], 3)
        self.assertEqual(p["done"], 1)
        self.assertAlmostEqual(p["ratio"], 1 / 3, places=3)

    def test_stops_at_next_heading(self):
        p = task_progress(NOTE)
        # 「本课知识点」里的列表项不该被当成作业
        self.assertEqual(len(p["items"]), 3)

    def test_no_tasks(self):
        p = task_progress("# 没有作业清单")
        self.assertEqual((p["total"], p["done"], p["ratio"]), (0, 0, 0.0))

    def test_uppercase_x_counts_as_done(self):
        p = task_progress("### 作业清单\n- [X] 做完了\n")
        self.assertEqual(p["done"], 1)


class TestMasteryRatio(unittest.TestCase):

    def test_mean_of_verdicts(self):
        self.assertEqual(mastery_ratio([{"verdict": "pass"}, {"verdict": "missing"}]), 0.5)

    def test_partial_counts_half(self):
        self.assertEqual(mastery_ratio([{"verdict": "partial"}]), 0.5)

    def test_empty(self):
        self.assertEqual(mastery_ratio([]), 0.0)

    def test_unknown_verdict_counts_zero(self):
        self.assertEqual(mastery_ratio([{"verdict": "???"}]), 0.0)


class TestScore(unittest.TestCase):

    def _progress(self):
        return task_progress(NOTE)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(SCORE_WEIGHTS.values()), 1.0)

    def test_perfect_score(self):
        inter = {"verdicts": [{"id": f"K{i}", "verdict": "pass"} for i in range(1, 5)]}
        # 笔记覆盖 K1/K2/K3（K4 Pandas 没写）
        prog = {"items": [], "done": 0, "total": 0, "ratio": 1.0}
        r = score(curriculum(), NOTE.split("我的笔记")[1], inter, prog)
        self.assertAlmostEqual(r["parts"]["coverage"], 0.75)
        self.assertAlmostEqual(r["percent"], 0.4 * 0.75 + 0.4 * 1.0 + 0.2 * 1.0, places=4)

    def test_missing_must_blocks_skip(self):
        inter = {"verdicts": [{"id": f"K{i}", "verdict": "pass"} for i in range(1, 5)]}
        prog = {"items": [], "done": 0, "total": 0, "ratio": 1.0}
        r = score(curriculum(), "完全没写笔记", inter, prog)
        self.assertFalse(r["can_skip"])
        self.assertTrue(any("未覆盖" in b for b in r["blockers"]))

    def test_error_with_source_blocks_skip(self):
        inter = {
            "verdicts": [{"id": f"K{i}", "verdict": "pass"} for i in range(1, 5)],
            "errors": [{"quote": "x", "reason": "y", "source_ref": "M1"}],
        }
        prog = {"items": [], "done": 0, "total": 0, "ratio": 1.0}
        notes = NOTE.split("我的笔记")[1] + " pandas DataFrame 分组 groupby"
        r = score(curriculum(), notes, inter, prog)
        self.assertFalse(r["can_skip"])
        self.assertTrue(any("错误" in b for b in r["blockers"]))

    def test_error_without_source_does_not_block(self):
        """无依据的存疑不能当成错误拦人（沿用 D7）。"""
        inter = {
            "verdicts": [{"id": f"K{i}", "verdict": "pass"} for i in range(1, 5)],
            "errors": [{"quote": "x", "reason": "y", "source_ref": ""}],
        }
        prog = {"items": [], "done": 0, "total": 0, "ratio": 1.0}
        notes = NOTE.split("我的笔记")[1] + " pandas DataFrame 分组 groupby"
        r = score(curriculum(), notes, inter, prog)
        self.assertTrue(r["can_skip"])

    def test_levels(self):
        inter = empty_interrogation()
        prog = {"items": [], "done": 0, "total": 0, "ratio": 0.0}
        r = score(curriculum(), NOTE.split("我的笔记")[1], inter, prog)
        self.assertIn(r["level"], ("已达标", "接近达标", "差距较大"))

    def test_threshold_default(self):
        r = score(curriculum(), NOTE, empty_interrogation(), task_progress(NOTE))
        self.assertEqual(r["threshold"], DEFAULT_SKIP_THRESHOLD)


class TestRender(unittest.TestCase):

    def _report(self):
        cur = curriculum()
        prog = task_progress(NOTE)
        inter = {
            "verdicts": [{"id": "K1", "verdict": "pass", "why": "写清了"},
                         {"id": "K2", "verdict": "partial", "why": "没提 Session 复用"}],
            "questions": [{"for": "K2", "question": "Session 为什么能复用连接？"}],
            "errors": [{"quote": "403 是频率超限", "reason": "429 才是", "source_ref": "M3"}],
            "uncertain": [{"quote": "某句话", "reason": "资料未覆盖"}],
            "todo": ["补 Session 的说明"],
            "summary": "整体不错，Session 那块要补。",
        }
        r = score(cur, NOTE.split("我的笔记")[1], inter, prog)
        return render_report(cur, r, inter, prog)

    def test_has_all_sections(self):
        rep = self._report()
        for sec in ("达成度", "知识点覆盖", "掌握判定", "逐点掌握判定",
                    "质询", "错误（带依据）", "待你核对", "查缺补漏清单", "总评"):
            self.assertIn(sec, rep)

    def test_shows_percentage(self):
        self.assertRegex(self._report(), r"达成度 \d+%")

    def test_shows_skip_decision(self):
        rep = self._report()
        self.assertTrue("跳过" in rep)

    def test_offline_interrogation_is_labelled(self):
        cur = curriculum()
        prog = task_progress(NOTE)
        inter = empty_interrogation()
        r = score(cur, NOTE, inter, prog)
        self.assertIn("离线模式", render_report(cur, r, inter, prog))


if __name__ == "__main__":
    unittest.main(verbosity=2)
