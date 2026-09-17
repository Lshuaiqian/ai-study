"""确定性检查的单元测试：代码实践维度 + 笔记覆盖维度（不联网）。

运行：python -m unittest discover -s study/tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gate.codecheck import DEFAULT_CRITERIA, analyze, count_effective_lines  # noqa: E402
from notedoctor.doctor import check_coverage  # noqa: E402

GOOD_SOURCE = '''
import json, time, requests

HEADERS = {"User-Agent": "learn-bot/0.1"}

def fetch(url, retry=3):
    for i in range(retry):
        try:
            time.sleep(1)
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                return r
        except Exception as e:
            print("failed", e)
    return None

def main():
    rows = []
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    print(f"成功 {len(rows)} 条")
'''


class TestCodeCheck(unittest.TestCase):

    def test_full_hits(self):
        r = analyze(GOOD_SOURCE)
        self.assertEqual(r["misses"], [])
        self.assertEqual(r["score"], 1.0)

    def test_empty_source_scores_zero(self):
        r = analyze("")
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(len(r["misses"]), len(DEFAULT_CRITERIA))

    def test_missing_retry_is_detected(self):
        src = "import requests, time\n" \
              "h={'User-Agent':'x'}\n" \
              "time.sleep(1)\n" \
              "r=requests.get('http://x',headers=h)\n" \
              "import json; json.dump([], open('a.json','w'))\n" \
              "print(len([]))\n"
        r = analyze(src)
        self.assertIn("有异常处理与重试", r["misses"])

    def test_effective_lines_ignores_blank_and_comment(self):
        src = "# comment\n\n   \nimport os  # trailing\n\n# another\nx = 1\n"
        self.assertEqual(count_effective_lines(src), 2)

    def test_min_lines_flag(self):
        r = analyze(GOOD_SOURCE, min_lines=1000)
        self.assertFalse(r["meets_min_lines"])
        r2 = analyze(GOOD_SOURCE, min_lines=1)
        self.assertTrue(r2["meets_min_lines"])


DECLARES = {
    "knowledge": [
        {"id": "K1", "name": "流程", "level": "must",
         "keywords": [["请求"], ["解析"]]},
        {"id": "K2", "name": "robots", "level": "must",
         "keywords": [["robots"], ["限速", "sleep"]]},
        {"id": "K3", "name": "可选增强", "level": "should",
         "keywords": [["BeautifulSoup"]]},
    ]
}


class TestCoverage(unittest.TestCase):

    def test_full_coverage(self):
        note = "先发请求，再解析。robots.txt 要先看，并且限速 sleep(1)。"
        r = check_coverage(DECLARES, note)
        self.assertEqual(r["must_cover_ratio"], 1.0)
        self.assertEqual(r["must_missing"], [])

    def test_partial_coverage(self):
        note = "先发请求，再解析。限速 sleep(1)。"          # 缺 robots
        r = check_coverage(DECLARES, note)
        self.assertEqual(r["must_missing"], ["K2"])
        self.assertAlmostEqual(r["must_cover_ratio"], 0.5)

    def test_should_level_not_counted(self):
        note = "先发请求，再解析。robots 要先看，并且限速 sleep(1)。"
        r = check_coverage(DECLARES, note)
        self.assertEqual(r["must_cover_ratio"], 1.0)       # K3 是 should，不影响门禁
        self.assertNotIn("K3", r["must_ids"])

    def test_empty_note(self):
        r = check_coverage(DECLARES, "")
        self.assertEqual(r["must_cover_ratio"], 0.0)

    def test_keyword_group_requires_one_hit_each(self):
        # K1 需要 请求 + 解析 两组都命中
        r = check_coverage(DECLARES, "只提到请求，没有另一组")
        self.assertFalse(r["detail"]["K1"]["covered"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
