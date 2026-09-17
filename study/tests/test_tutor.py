"""Tutor 侧确定性逻辑的单测：代码执行器安全边界 + code 维度合成公式（不联网）。

运行：python -m unittest discover -s study/tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gate.codecheck import (MAX_QUALITY_PENALTY, combine_code_dimension)  # noqa: E402
from tutor.reviewer import extract_knowledge_gaps                 # noqa: E402
from tutor.runner import (UnsafePathError, check_imports, check_syntax,   # noqa: E402
                          resolve_inside, run_file)


class TestPathGuard(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="study_test_")
        self.other = tempfile.mkdtemp(prefix="study_outside_")

    def test_allows_inside(self):
        p = os.path.join(self.root, "a.py")
        self.assertEqual(resolve_inside(p, [self.root]), os.path.abspath(p))

    def test_blocks_outside(self):
        p = os.path.join(self.other, "a.py")
        with self.assertRaises(UnsafePathError):
            resolve_inside(p, [self.root])

    def test_blocks_prefix_trick(self):
        """同前缀但不同目录（/work2 vs /work）不得放行。"""
        sibling = self.root + "2"
        os.makedirs(sibling, exist_ok=True)
        p = os.path.join(sibling, "a.py")
        with self.assertRaises(UnsafePathError):
            resolve_inside(p, [self.root])

    def test_blocks_parent_escape(self):
        p = os.path.join(self.root, "..", "evil.py")
        with self.assertRaises(UnsafePathError):
            resolve_inside(p, [self.root])


class TestCheckSyntax(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="study_syn_")

    def _w(self, name, text):
        p = os.path.join(self.root, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_ok(self):
        p = self._w("ok.py", "x = 1\nprint(x)\n")
        self.assertTrue(check_syntax(p, [self.root])["ok"])

    def test_syntax_error(self):
        p = self._w("bad.py", "def f(:\n")
        r = check_syntax(p, [self.root])
        self.assertFalse(r["ok"])
        self.assertIn("SyntaxError", r["error"])

    def test_rejects_non_python(self):
        p = self._w("a.txt", "hello")
        self.assertFalse(check_syntax(p, [self.root])["ok"])


class TestCheckImports(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="study_imp_")

    def _w(self, text):
        p = os.path.join(self.root, "m.py")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_detects_missing_third_party(self):
        p = self._w("import os, json\nimport definitely_not_a_real_module_xyz\n")
        r = check_imports(p, [self.root])
        self.assertFalse(r["ok"])
        self.assertIn("definitely_not_a_real_module_xyz", r["missing"])
        self.assertIn("os", r["modules"])

    def test_stdlib_only_is_ok(self):
        p = self._w("import os, json, csv\nfrom html.parser import HTMLParser\n")
        r = check_imports(p, [self.root])
        self.assertTrue(r["ok"])
        self.assertEqual(r["missing"], [])

    def test_syntax_error_reported(self):
        p = self._w("import (:\n")
        r = check_imports(p, [self.root])
        self.assertFalse(r["ok"])
        self.assertIn("SyntaxError", r["error"])


class TestRunFile(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="study_run_")

    def _w(self, name, text):
        p = os.path.join(self.root, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_runs_and_captures_stdout(self):
        p = self._w("hello.py", "print('hello-study')\n")
        r = run_file(p, [self.root], timeout=20)
        self.assertTrue(r["ran"])
        self.assertEqual(r["exit_code"], 0)
        self.assertIn("hello-study", r["stdout"])

    def test_captures_stderr_and_nonzero_exit(self):
        p = self._w("boom.py", "raise SystemExit(3)\n")
        r = run_file(p, [self.root], timeout=20)
        self.assertEqual(r["exit_code"], 3)

    def test_timeout_is_killed(self):
        p = self._w("loop.py", "import time\nwhile True:\n    time.sleep(0.2)\n")
        r = run_file(p, [self.root], timeout=2)
        self.assertTrue(r["timeout"])
        self.assertIn("超时", r["stderr"])

    def test_output_is_truncated(self):
        p = self._w("noisy.py", "print('x' * 20000)\n")
        r = run_file(p, [self.root], timeout=20)
        self.assertIn("已截断", r["stdout"])

    def test_blocks_outside_path(self):
        outside = tempfile.mkdtemp(prefix="study_out_")
        p = os.path.join(outside, "x.py")
        with open(p, "w", encoding="utf-8") as f:
            f.write("print(1)\n")
        with self.assertRaises(UnsafePathError):
            run_file(p, [self.root])


class TestCombineCodeDimension(unittest.TestCase):
    """首版公式在真跑时翻了车：点评越认真→warn 越多→分数越低。这些测试锁住修正后的行为。"""

    def test_perfect(self):
        r = combine_code_dimension(1.0, {})
        self.assertEqual(r["score"], 1.0)

    def test_style_alone_does_not_penalize(self):
        r = combine_code_dimension(1.0, {"style": 10})
        self.assertEqual(r["score"], 1.0)
        self.assertEqual(r["penalty"], 0.0)

    def test_praise_does_not_penalize(self):
        self.assertEqual(combine_code_dimension(1.0, {"praise": 5})["penalty"], 0.0)

    def test_good_review_with_many_warns_still_scores_high(self):
        """真实场景：Tutor 给出 4 warn + 3 style，代码本身是好的。"""
        r = combine_code_dimension(1.0, {"warn": 4, "style": 3, "praise": 4})
        self.assertGreater(r["score"], 0.85)

    def test_error_penalizes(self):
        r = combine_code_dimension(1.0, {"error": 1})
        self.assertAlmostEqual(r["penalty"], 0.30)
        self.assertAlmostEqual(r["score"], 0.88)

    def test_penalty_is_capped(self):
        r = combine_code_dimension(1.0, {"error": 10})
        self.assertAlmostEqual(r["penalty"], MAX_QUALITY_PENALTY)
        self.assertTrue(r["penalty_capped"])
        self.assertGreater(r["score"], 0.0)
        self.assertAlmostEqual(r["score"], 0.6 + 0.4 * 0.5)

    def test_criteria_ratio_dominates_lower_bound(self):
        # 即使点评全错（扣满），机检通过率仍保住 0.6×ratio
        r = combine_code_dimension(1.0, {"error": 99})
        self.assertGreaterEqual(r["score"], 0.6)

    def test_zero_criteria_still_gets_quality_credit(self):
        r = combine_code_dimension(0.0, {})
        self.assertAlmostEqual(r["score"], 0.4)

    def test_weights_sum(self):
        from gate.codecheck import CRITERIA_WEIGHT, QUALITY_WEIGHT
        self.assertAlmostEqual(CRITERIA_WEIGHT + QUALITY_WEIGHT, 1.0)


class TestExtractKnowledgeGaps(unittest.TestCase):
    """`extract_knowledge_gaps` 把导师的自由文本点评转成结构化薄弱点。

    模型回复本身不可测，但**回复的校验与过滤**是可测的：模型给出不存在的 K-id
    必须被丢掉，否则会往掌握度模型里写进幽灵知识点。
    """

    class _StubLLM:
        def __init__(self, payload):
            self.payload = payload
            self.seen = None

        def chat(self, system, user, **kwargs):
            self.seen = {"system": system, "user": user, "kwargs": kwargs}
            return self.payload

    def _curriculum(self):
        return {
            "course_id": "py-agent-03",
            "title": "第 3 课",
            "declares": {"knowledge": [
                {"id": "K1", "name": "爬虫流程", "level": "must"},
                {"id": "K3", "name": "礼貌爬取", "level": "must"},
            ]},
        }

    def test_filters_unknown_ids(self):
        llm = self._StubLLM({
            "gaps": [{"id": "K3", "reason": "没提 robots"}, {"id": "K99", "reason": "幽灵"}],
            "solid": ["K1", "K404"],
            "summary": "一句话",
        })
        res = extract_knowledge_gaps(llm, self._curriculum(), "点评原文")
        self.assertEqual([g["id"] for g in res["gaps"]], ["K3"])
        self.assertEqual(res["solid"], ["K1"])
        self.assertEqual(res["summary"], "一句话")

    def test_tolerates_missing_fields(self):
        llm = self._StubLLM({})
        res = extract_knowledge_gaps(llm, self._curriculum(), "点评原文")
        self.assertEqual(res, {"gaps": [], "solid": [], "summary": ""})

    def test_uses_zero_temperature_and_json_mode(self):
        llm = self._StubLLM({"gaps": [], "solid": []})
        extract_knowledge_gaps(llm, self._curriculum(), "点评原文")
        self.assertTrue(llm.seen["kwargs"]["json_mode"])
        self.assertEqual(llm.seen["kwargs"]["temperature"], 0.0)

    def test_prompt_carries_review_and_criteria(self):
        llm = self._StubLLM({"gaps": [], "solid": []})
        extract_knowledge_gaps(
            llm, self._curriculum(), "导师说这里有问题",
            {"hits": ["带 User-Agent"], "misses": ["有重试"]})
        user = llm.seen["user"]
        self.assertIn("导师说这里有问题", user)
        self.assertIn("带 User-Agent", user)
        self.assertIn("有重试", user)
        self.assertIn("K1", user)
        self.assertIn("K3", user)


if __name__ == "__main__":
    unittest.main(verbosity=2)
