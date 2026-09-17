"""Planner 与准入门禁的单测（纯逻辑，不联网）。

运行：python -m unittest discover -s study/tests
"""
import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flow import EntryDenied, entry_check, require_entry          # noqa: E402
from graph import build, kp_id                                     # noqa: E402
from plan import (INTERVALS, append_event, due_reviews,            # noqa: E402
                  filter_range, promote_review, read_events,
                  rework_items, start_review_clock, weekly_report)

TODAY = date(2026, 9, 16)


# ---------------- 测试用迷你图 ----------------

def _route():
    return {"title": "测试路线", "entry": {"name": "C++ 基础", "note": ""}, "courses": [
        {"course_id": "c1", "title": "第 1 课", "requires": []},
        {"course_id": "c2", "title": "第 2 课", "requires": ["c1"]},
        {"course_id": "c3", "title": "第 3 课", "requires": ["c2"]},
    ]}


def _curriculums():
    return {
        "c1": {"course_id": "c1", "declares": {"prerequisites": [], "unlocks": [
            {"course_id": "c2"}], "knowledge": [
            {"id": "K1", "name": "语法", "level": "must", "keywords": [["x"]], "requires": []},
            {"id": "K2", "name": "OOP", "level": "must", "keywords": [["y"]], "requires": ["K1"]}]}},
        "c2": {"course_id": "c2", "declares": {"prerequisites": [
            {"course_id": "c1"}], "unlocks": [{"course_id": "c3"}], "knowledge": [
            {"id": "K1", "name": "HTTP", "level": "must", "keywords": [["h"]], "requires": [
                {"course_id": "c1", "knowledge_id": "K1", "why": "w"}]}]}},
        "c3": {"course_id": "c3", "declares": {"prerequisites": [
            {"course_id": "c2"}], "unlocks": [], "knowledge": [
            {"id": "K1", "name": "爬虫", "level": "must", "keywords": [["s"]], "requires": [
                {"course_id": "c2", "knowledge_id": "K1", "why": "w"}]}]}},
    }


def G():
    return build(_route(), _curriculums())


# ---------------- 事件日志 ----------------

class TestEvents(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="study_ev_")
        self.path = os.path.join(self.dir, "events.jsonl")

    def test_append_and_read(self):
        append_event(self.path, "submission", course_id="c1", mastery=0.9, lines=120)
        append_event(self.path, "passed", course_id="c1", mastery=0.91, attempts=2)
        evs = read_events(self.path)
        self.assertEqual(len(evs), 2)
        self.assertEqual(evs[0]["kind"], "submission")
        self.assertEqual(evs[1]["mastery"], 0.91)
        self.assertIn("ts", evs[0])

    def test_rejects_unknown_kind(self):
        with self.assertRaises(ValueError):
            append_event(self.path, "definitely_not_a_kind")

    def test_missing_file_returns_empty(self):
        self.assertEqual(read_events(os.path.join(self.dir, "nope.jsonl")), [])

    def test_bad_line_is_skipped(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"ts":"2026-09-16T10:00:00","kind":"passed"}\n')
            f.write("这不是 JSON\n")
            f.write('{"ts":"2026-09-17T10:00:00","kind":"passed"}\n')
        self.assertEqual(len(read_events(self.path)), 2)

    def test_filter_range_is_half_open(self):
        evs = [{"ts": "2026-09-14T09:00:00"}, {"ts": "2026-09-20T23:59:59"},
               {"ts": "2026-09-21T00:00:00"}]
        got = filter_range(evs, date(2026, 9, 14), date(2026, 9, 21))
        self.assertEqual(len(got), 2)          # 右端点不含


# ---------------- 复习队列 ----------------

class TestReviewQueue(unittest.TestCase):

    def setUp(self):
        self.g = G()

    def test_empty_state_no_due(self):
        self.assertEqual(due_reviews(self.g, {}, TODAY), [])

    def test_review_queue_is_due_immediately(self):
        state = {"atoms": {kp_id("c1", "K1"): {"mastery": 0.6, "passed": False,
                                              "review_queue": True}}}
        q = due_reviews(self.g, state, TODAY)
        self.assertEqual(len(q), 1)
        self.assertIn("回炉未清", q[0]["reasons"])

    def test_recheck_due_is_due_immediately(self):
        state = {"atoms": {kp_id("c1", "K2"): {"mastery": 0.9, "passed": True,
                                              "recheck_due": True}}}
        q = due_reviews(self.g, state, TODAY)
        self.assertIn("待复查", q[0]["reasons"])

    def test_scheduled_review_due_and_not_due(self):
        state = {"atoms": {
            kp_id("c1", "K1"): {"mastery": 0.9, "passed": True, "next_review": "2026-09-15"},
            kp_id("c1", "K2"): {"mastery": 0.9, "passed": True, "next_review": "2026-10-01"}}}
        q = due_reviews(self.g, state, TODAY)
        ids = [i["id"] for i in q]
        self.assertIn(kp_id("c1", "K1"), ids)
        self.assertNotIn(kp_id("c1", "K2"), ids)

    def test_passed_without_schedule_is_not_due(self):
        state = {"atoms": {kp_id("c1", "K1"): {"mastery": 0.9, "passed": True}}}
        self.assertEqual(due_reviews(self.g, state, TODAY), [])

    def test_priority_order(self):
        state = {"atoms": {
            kp_id("c1", "K1"): {"passed": True, "next_review": "2026-09-01"},   # 到期
            kp_id("c1", "K2"): {"passed": True, "recheck_due": True},           # 待复查
            kp_id("c2", "K1"): {"passed": False, "review_queue": True}}}        # 回炉
        q = due_reviews(self.g, state, TODAY)
        self.assertEqual(q[0]["id"], kp_id("c2", "K1"))       # 回炉优先
        self.assertEqual(q[1]["id"], kp_id("c1", "K2"))       # 其次待复查

    def test_rework_excludes_passed_and_reflow(self):
        state = {"atoms": {
            kp_id("c1", "K1"): {"mastery": 0.9, "passed": True},
            kp_id("c1", "K2"): {"mastery": 0.4, "passed": False},
            kp_id("c2", "K1"): {"mastery": 0.5, "passed": False, "review_queue": True}}}
        ids = [i["id"] for i in rework_items(self.g, state)]
        self.assertEqual(ids, [kp_id("c1", "K2")])


class TestReviewLadder(unittest.TestCase):

    def test_success_advances_stage(self):
        rec = {"stage": 0}
        promote_review(rec, True, TODAY)
        self.assertEqual(rec["stage"], 1)
        self.assertEqual(rec["next_review"], "2026-09-19")     # +INTERVALS[1]=3
        self.assertFalse(rec["review_queue"])

    def test_failure_resets_stage(self):
        rec = {"stage": 3}
        promote_review(rec, False, TODAY)
        self.assertEqual(rec["stage"], 0)
        self.assertEqual(rec["next_review"], "2026-09-17")     # +1
        self.assertTrue(rec["review_queue"])

    def test_stage_is_capped(self):
        rec = {"stage": len(INTERVALS) - 1}
        promote_review(rec, True, TODAY)
        self.assertEqual(rec["stage"], len(INTERVALS) - 1)

    def test_success_clears_recheck_flags(self):
        rec = {"stage": 0, "recheck_due": True, "recheck_reason": "x", "recheck_depth": 1}
        promote_review(rec, True, TODAY)
        self.assertNotIn("recheck_due", rec)
        self.assertNotIn("recheck_reason", rec)

    def test_review_count_accumulates(self):
        rec = {}
        promote_review(rec, True, TODAY)
        promote_review(rec, True, TODAY)
        self.assertEqual(rec["review_count"], 2)

    def test_start_clock(self):
        rec = {}
        start_review_clock(rec, TODAY)
        self.assertEqual(rec["next_review"], "2026-09-17")     # +1


# ---------------- 周报 ----------------

class TestWeeklyReport(unittest.TestCase):

    def setUp(self):
        self.g = G()
        self.dir = tempfile.mkdtemp(prefix="study_rp_")
        self.path = os.path.join(self.dir, "events.jsonl")

    def _seed(self):
        append_event(self.path, "submission", course_id="c1", mastery=0.60,
                     passed=False, lines=90)
        append_event(self.path, "submission", course_id="c1", mastery=0.92,
                     passed=True, lines=140)
        append_event(self.path, "passed", course_id="c1", mastery=0.92, attempts=2)
        append_event(self.path, "note_review", course_id="c1", note_score=0.8,
                     parts={"coverage": 1.0, "accuracy": 1.0, "structure": 0.5,
                            "linking": 0.6, "own_words": 0.85})
        append_event(self.path, "note_review", course_id="c1", note_score=0.79,
                     source="note-tidy", parts={"coverage": 0.61})
        append_event(self.path, "interrogation", course_id="c1", percent=0.82,
                     can_skip=True, parts={"coverage": 1.0, "mastery": 0.75,
                                           "tasks": 1.0})
        append_event(self.path, "reflow", atom=kp_id("c1", "K1"), before=0.9, after=0.63)
        return read_events(self.path)

    def test_report_sections(self):
        r = weekly_report(self._seed(), self.g, {}, week_start=date(2026, 9, 14))
        for section in ("本周概览", "代码量", "掌握度变化", "笔记质量",
                        "薄弱点与回炉", "课末复盘三问", "下周建议"):
            self.assertIn(section, r)

    def test_code_total_and_arrow(self):
        r = weekly_report(self._seed(), self.g, {}, week_start=date(2026, 9, 14))
        self.assertIn("230", r)                      # 90 + 140
        self.assertIn("↑", r)                        # 0.60 → 0.92

    def test_review_questions_left_blank_for_user(self):
        r = weekly_report(self._seed(), self.g, {}, week_start=date(2026, 9, 14))
        self.assertIn("AI 不打分", r)
        self.assertIn("答：", r)

    def test_tidy_and_checkup_are_counted_separately(self):
        """体检五维与整理覆盖率形状不同，混在一起算"最弱维度"会得出错的结论。"""
        r = weekly_report(self._seed(), self.g, {}, week_start=date(2026, 9, 14))
        self.assertIn("笔记体检      1 次", r)
        self.assertIn("一键整理      1 次", r)
        self.assertIn("整理后笔记维度", r)

    def test_interrogation_shows_percent_and_skip(self):
        """质询结论必须出现在周报里，否则它写进事件流也没人看。"""
        r = weekly_report(self._seed(), self.g, {}, week_start=date(2026, 9, 14))
        self.assertIn("AI 质询", r)
        self.assertIn("82%", r)
        self.assertIn("可跳过", r)

    def test_not_ready_interrogation_gets_a_nudge(self):
        append_event(self.path, "interrogation", course_id="c1", percent=0.44,
                     can_skip=False, parts={})
        r = weekly_report(read_events(self.path), self.g, {},
                          week_start=date(2026, 9, 14))
        self.assertIn("未达标", r)
        self.assertIn("别跳", r)

    def test_empty_week_is_graceful(self):
        r = weekly_report([], self.g, {}, week_start=date(2026, 9, 14))
        self.assertIn("本周没有提交", r)
        self.assertIn("没有体检记录", r)
        # 空状态下第 1 课本来就是可开的，所以建议里应该出现"可以开新课"而不是"没待办"
        self.assertIn("可以开新课", r)

    def test_blocked_entry_counted(self):
        append_event(self.path, "blocked_entry", course_id="c3", missing=["c2"])
        r = weekly_report(read_events(self.path), self.g, {}, week_start=date(2026, 9, 14))
        self.assertIn("被门禁拦下", r)

    def test_today_param_keeps_queue_count_consistent(self):
        """周报与今日视图必须对同一个 today 得出一致的待复习数量。"""
        from plan import daily_view
        state = {"atoms": {kp_id("c1", "K1"): {"passed": True, "next_review": "2026-10-01"}}}
        r_default = weekly_report([], self.g, state, week_start=date(2026, 9, 14))
        self.assertNotIn("待复习", r_default)                 # 10-01 还没到期
        r_late = weekly_report([], self.g, state,
                               week_start=date(2026, 9, 14), today=date(2026, 10, 2))
        self.assertIn("当前待复习 1 个", r_late)
        self.assertIn("复习 1", daily_view(self.g, state, today=date(2026, 10, 2)))


# ---------------- 课程准入 ----------------

class TestEntryGate(unittest.TestCase):

    def setUp(self):
        self.g = G()

    def test_first_course_allowed(self):
        c = entry_check(self.g, {}, "c1")
        self.assertTrue(c["allowed"])
        self.assertEqual(c["status"], "available")

    def test_locked_course_denied_with_reason(self):
        c = entry_check(self.g, {}, "c3")
        self.assertFalse(c["allowed"])
        self.assertEqual(c["missing_prerequisites"], ["c2"])
        self.assertIn("缺前置", c["reason"])

    def test_denied_lists_transitive_reach(self):
        c = entry_check(self.g, {}, "c3")
        self.assertIn("连带未通过", c["reason"])        # c3→c2→c1

    def test_allowed_after_prereq_passed(self):
        state = {"lessons": {"c1": {"passed": True}, "c2": {"passed": True}}}
        self.assertTrue(entry_check(self.g, state, "c3")["allowed"])

    def test_passed_course_not_reenterable(self):
        state = {"lessons": {"c1": {"passed": True}}}
        c = entry_check(self.g, state, "c1")
        self.assertFalse(c["allowed"])
        self.assertEqual(c["status"], "passed")
        self.assertIn("重修", c["reason"])

    def test_unknown_course(self):
        c = entry_check(self.g, {}, "nope")
        self.assertFalse(c["allowed"])
        self.assertEqual(c["status"], "unknown_course")

    def test_require_entry_raises(self):
        with self.assertRaises(EntryDenied) as ctx:
            require_entry(self.g, {}, "c3")
        self.assertEqual(ctx.exception.course_id, "c3")

    def test_blocked_points_reported(self):
        c = entry_check(self.g, {}, "c2")
        self.assertFalse(c["allowed"])
        # c2:K1 的前置 c1:K1 未通过 → 应被列入 blocked_points
        self.assertIn(kp_id("c2", "K1"), c["blocked_points"])

    def test_in_progress_course_allowed(self):
        state = {"lessons": {"c1": {"passed": True}},
                 "atoms": {kp_id("c2", "K1"): {"mastery": 0.5, "passed": False}}}
        c = entry_check(self.g, state, "c2")
        self.assertTrue(c["allowed"])
        self.assertEqual(c["status"], "in_progress")


if __name__ == "__main__":
    unittest.main(verbosity=2)
