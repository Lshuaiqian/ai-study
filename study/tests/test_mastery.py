"""门禁逻辑单元测试（纯计算，不联网）。

运行：python -m unittest discover -s study/tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gate import (  # noqa: E402
    DEFAULT_GATE, carry_over, compute_mastery, evaluate, next_action,
    note_score, reflow,
)

FULL = {"code": 1.0, "quiz": 1.0, "note": 1.0, "transfer": 1.0}


class TestMastery(unittest.TestCase):

    def test_weights_sum_to_one(self):
        from gate import WEIGHTS
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0, places=9)

    def test_all_perfect(self):
        self.assertEqual(compute_mastery(FULL), 1.0)

    def test_weighted_value(self):
        dims = {"code": 1.0, "quiz": 0.0, "note": 0.0, "transfer": 0.0}
        self.assertEqual(compute_mastery(dims), 0.35)

    def test_missing_dim_counts_zero(self):
        self.assertEqual(compute_mastery({"code": 1.0}), 0.35)

    def test_clamped(self):
        self.assertEqual(compute_mastery({"code": 5.0, "quiz": -3}), 0.35)


class TestGate(unittest.TestCase):

    def test_pass_when_all_good(self):
        r = evaluate(FULL, must_cover_ratio=1.0)
        self.assertTrue(r["passed"])
        self.assertEqual(r["failures"], [])
        self.assertFalse(r["carry_allowed"])

    def test_fail_on_low_total(self):
        dims = {"code": 0.7, "quiz": 0.7, "note": 0.7, "transfer": 0.7}
        r = evaluate(dims)
        self.assertFalse(r["passed"])
        self.assertTrue(any("总分" in f for f in r["failures"]))
        self.assertTrue(r["carry_allowed"])

    def test_fail_on_single_weak_dim_even_if_total_ok(self):
        # 0.35*1 + 0.25*1 + 0.20*0.5 + 0.20*1 = 0.90，总分够但 note 不达标
        dims = {"code": 1.0, "quiz": 1.0, "note": 0.5, "transfer": 1.0}
        r = evaluate(dims)
        self.assertEqual(r["mastery"], 0.9)
        self.assertFalse(r["passed"])
        self.assertIn("note", r["weak_dims"])
        self.assertTrue(any("笔记质量" in f for f in r["failures"]))

    def test_fatal_blocks_carry_over(self):
        dims = {"code": 0.7, "quiz": 0.7, "note": 0.7, "transfer": 0.7}
        r = evaluate(dims, fatal=True)
        self.assertFalse(r["passed"])
        self.assertFalse(r["carry_allowed"])
        self.assertTrue(any("致命误解" in f for f in r["failures"]))

    def test_coverage_must_be_full(self):
        r = evaluate(FULL, must_cover_ratio=0.8)
        self.assertFalse(r["passed"])
        self.assertTrue(any("覆盖率" in f for f in r["failures"]))

    def test_transfer_required(self):
        dims = {"code": 1.0, "quiz": 1.0, "note": 1.0, "transfer": 0.0}
        r = evaluate(dims)
        self.assertIn("transfer", r["weak_dims"])
        r2 = evaluate(dims, {"require_transfer": False, "min_each": 0.0})
        self.assertTrue(any("迁移" in f for f in r["failures"]))

    def test_min_practice_lines(self):
        r = evaluate(FULL, {"min_practice_lines": 120}, practice_lines=40)
        self.assertFalse(r["passed"])
        self.assertTrue(any("代码量" in f for f in r["failures"]))
        r2 = evaluate(FULL, {"min_practice_lines": 120}, practice_lines=200)
        self.assertTrue(r2["passed"])

    def test_defaults_unchanged(self):
        self.assertEqual(evaluate(FULL)["gate"], DEFAULT_GATE)


class TestNextAction(unittest.TestCase):

    def test_L1_on_first_failure(self):
        dims = {"code": 1.0, "quiz": 1.0, "note": 0.4, "transfer": 1.0}
        r = evaluate(dims)
        a = next_action(r, attempt=1)
        self.assertEqual(a["level"], "L1_补练")
        self.assertEqual(a["target_dim"], "note")

    def test_L2_on_second(self):
        r = evaluate({"code": 0.7, "quiz": 0.7, "note": 0.7, "transfer": 0.7})
        self.assertEqual(next_action(r, 2)["level"], "L2_降粒度")

    def test_L3_rotates_methods(self):
        r = evaluate({"code": 0.5, "quiz": 0.5, "note": 0.5, "transfer": 0.5})
        a3 = next_action(r, 3)
        a4 = next_action(r, 4)
        self.assertEqual(a3["level"], "L3_换表征")
        self.assertNotEqual(a3["detail"], a4["detail"])

    def test_no_action_when_passed(self):
        self.assertIsNone(next_action(evaluate(FULL), 1)["level"])


class TestCarryOver(unittest.TestCase):

    def test_carry_over_record(self):
        r = evaluate({"code": 0.8, "quiz": 0.8, "note": 0.8, "transfer": 0.8})
        rec = carry_over("py-agent-03", r, ["K3", "K5"])
        self.assertTrue(rec["carried_over"])
        self.assertEqual(rec["points"], ["K3", "K5"])
        self.assertEqual(rec["mastery_at_carry"], 0.8)
        self.assertTrue(rec["review_queue"])

    def test_carry_over_rejected_when_fatal(self):
        r = evaluate({"code": 0.8, "quiz": 0.8, "note": 0.8, "transfer": 0.8}, fatal=True)
        with self.assertRaises(ValueError):
            carry_over("py-agent-03", r, ["K3"])

    def test_carry_over_rejected_when_passed(self):
        with self.assertRaises(ValueError):
            carry_over("py-agent-03", evaluate(FULL), [])


class TestReflow(unittest.TestCase):

    def test_reflow_discounts_and_requeues(self):
        state = {"atoms": {"a1": {"mastery": 1.0, "passed": True},
                           "a2": {"mastery": 0.9, "passed": True},
                           "a3": {"mastery": 0.5, "passed": False}}}
        changes = reflow(state, ["a1", "a2", "a3", "missing"])
        self.assertEqual(len(changes), 2)          # 只有已通过的会被回炉
        self.assertAlmostEqual(state["atoms"]["a1"]["mastery"], 0.7)
        self.assertFalse(state["atoms"]["a1"]["passed"])
        self.assertTrue(state["atoms"]["a1"]["review_queue"])
        self.assertEqual(state["atoms"]["a1"]["reflow_count"], 1)
        self.assertEqual(state["atoms"]["a3"]["mastery"], 0.5)   # 未通过的不打折

    def test_reflow_is_idempotent_while_unresolved(self):
        """已被打回的原子再次暴露时不得重复打折——否则是重复惩罚。"""
        state = {"atoms": {"a1": {"mastery": 1.0, "passed": True}}}
        first = reflow(state, ["a1"])
        second = reflow(state, ["a1"])
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])                       # 第二次无变更
        self.assertEqual(state["atoms"]["a1"]["reflow_count"], 1)
        self.assertAlmostEqual(state["atoms"]["a1"]["mastery"], 0.7)

    def test_reflow_accumulates_after_recovery(self):
        """重新通过后再次暴露 → 才应累计打折。"""
        state = {"atoms": {"a1": {"mastery": 1.0, "passed": True}}}
        reflow(state, ["a1"])
        state["atoms"]["a1"]["passed"] = True              # 模拟补练后重新通过
        reflow(state, ["a1"])
        self.assertEqual(state["atoms"]["a1"]["reflow_count"], 2)
        self.assertAlmostEqual(state["atoms"]["a1"]["mastery"], 0.49)


class TestNoteScore(unittest.TestCase):

    def test_note_weights(self):
        self.assertAlmostEqual(sum(__import__("gate").NOTE_WEIGHTS.values()), 1.0, places=9)

    def test_full_marks(self):
        self.assertEqual(note_score({k: 1.0 for k in
                                     ("structure", "coverage", "accuracy", "linking", "own_words")}), 1.0)

    def test_coverage_and_accuracy_dominate(self):
        # 只有覆盖+准确满分：0.3+0.3 = 0.6
        self.assertEqual(note_score({"coverage": 1.0, "accuracy": 1.0}), 0.6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
