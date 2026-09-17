# -*- coding: utf-8 -*-
"""tidy.py 的 **GUI 契约** 单测（P0 验收）：`--path` 定位、`--json` JSONL、退出码。

对应 docs/一键整理按钮-花笺集成方案（plan）.md 的 P0：
  - 改名后仍能定位课程（花笺改标题＝改文件名，靠标题前缀找笔记会失灵）
  - `--json` 每行都能 json.loads
  - 四个退出码（0 / 1 / 2 / 3）各有用例

不联网、不调模型：patch 掉 tidy_cli.tidy / LLM / STATE_DIR，落到临时目录。

运行：python -m unittest discover -s study/tests
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import tidy as tidy_cli                                    # noqa: E402

USER_BODY = """### 1. 我学到的（用自己的话）

HTTP 是无状态协议；状态码 200 成功，403 是拒绝执行，429 要退避。

### 2. 作业记录

爬虫作业做完了，能拿到 star 数。
"""

FEEDBACK = {
    "system_title": "Python·Agent 路线",
    "theme": "网络基础与 HTTP",
    "preview": ["HTTP 方法", "状态码"],
    "coverage": [{"id": "K1", "status": "covered", "why": "讲了状态码"},
                 {"id": "K2", "status": "partial", "why": "没提 Header"},
                 {"id": "K3", "status": "missing", "why": "没提 JSON"}],
    "glossary": [{"term": "HTTP", "def": "超文本传输协议"}],
    "todo": ["补 Header 说明"],
    "errors": [],
    "uncertain": [],
    "summary": "主干清楚，Header 要补。",
}


def note_text(marker="<!-- study: course=west2-f0 stage=F0 -->",
              user=USER_BODY, title="# F0 · 环境搭建"):
    head = ([marker, ""] if marker else []) + [
        title, "",
        "## 📋 考核要求", "",
        "### 作业清单", "",
        "- [ ] `t0-1` 装好环境", "",
        "---", "",
        "## ✍️ 我的笔记", "",
    ]
    return "\n".join(head) + "\n" + user + "\n"


class _CliHarness(unittest.TestCase):
    """共享脚手架：临时花笺目录 + patch 掉模型 + 驱动真实 CLI main()。

    本身不含 test_* 方法（unittest 不会收集它），两个具体测试类各自继承。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tidycli-")
        self.data_dir = os.path.join(self.tmp, "huajian")
        self.notes_dir = os.path.join(self.data_dir, "notes")
        self.category = os.path.join(self.notes_dir, "西二AI-2026")
        self.state_dir = os.path.join(self.tmp, "state")
        os.makedirs(self.category, exist_ok=True)
        with open(os.path.join(self.data_dir, "metadata.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"notes": []}, f)

        self.note_id = str(uuid.uuid4())
        self.note_path = os.path.join(self.category,
                                      f"{self.note_id}_F0-环境搭建.md")
        self.write(self.note_path, note_text())

        self.orig = (tidy_cli.tidy, tidy_cli.LLM, tidy_cli.STATE_DIR,
                     dict(tidy_cli.JSON_MODE))
        tidy_cli.tidy = lambda llm, curriculum, text: {
            "markdown": "## 一、环境\n\n- 装好了 Python。\n",
            "feedback": FEEDBACK,
        }
        tidy_cli.LLM = lambda *a, **k: None
        tidy_cli.STATE_DIR = self.state_dir
        tidy_cli.JSON_MODE["on"] = False

    def tearDown(self):
        (tidy_cli.tidy, tidy_cli.LLM, tidy_cli.STATE_DIR, saved) = self.orig
        tidy_cli.JSON_MODE.update(saved)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------------- 工具 ----------------

    def write(self, path, text):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def run_cli(self, argv):
        old = sys.argv
        out, err = io.StringIO(), io.StringIO()
        sys.argv = ["tidy.py"] + argv
        try:
            with redirect_stdout(out), redirect_stderr(err):
                rc = tidy_cli.main()
        finally:
            sys.argv = old
        return rc, out.getvalue(), err.getvalue()

    def json_lines(self, stdout):
        """把 stdout 按 JSONL 解析；任何一行解析失败即断言失败。"""
        lines = [ln for ln in stdout.splitlines() if ln.strip()]
        parsed = []
        for ln in lines:
            try:
                parsed.append(json.loads(ln))
            except json.JSONDecodeError as e:      # pragma: no cover - 失败信息
                self.fail(f"stdout 不是纯 JSONL：{ln[:120]!r} -> {e}")
        return parsed

    def base_argv(self, extra):
        return ["--west2", "--data-dir", self.data_dir] + extra

class TidyCliContractTest(_CliHarness):
    """tidy.py 的 P0 契约。"""

    # ---------------- P0：--path 定位 ----------------

    def test_path_with_marker_preview_ok(self):
        """--path 读课程标记，预览成功（退出码 0）。"""
        rc, out, _ = self.run_cli(self.base_argv(["--path", self.note_path]))
        self.assertEqual(rc, 0, out)
        self.assertIn("你的笔记", out)

    def test_rename_keeps_course_resolvable(self):
        """P-1 验收：把标题改掉（= 花笺改文件名），--path 仍能找到课程。"""
        renamed = os.path.join(self.category, f"{self.note_id}_环境搭建.md")
        os.replace(self.note_path, renamed)          # 模拟花笺改名
        self.note_path = renamed
        rc, out, _ = self.run_cli(self.base_argv(["--path", renamed]))
        self.assertEqual(rc, 0, out)
        self.assertIn("你的笔记", out)

    def test_legacy_note_without_marker_uses_title_prefix(self):
        """老笔记没有标记：退回「标题前缀反查课程」，仍可用。"""
        legacy_id = str(uuid.uuid4())
        legacy = os.path.join(self.category, f"{legacy_id}_F0-环境搭建.md")
        self.write(legacy, note_text(marker=None, title="# 环境搭建"))
        rc, out, _ = self.run_cli(self.base_argv(["--path", legacy]))
        self.assertEqual(rc, 0, out)
        self.assertIn("title-prefix", out)           # 人类日志里标明来源

    def test_non_course_note_is_exit_3(self):
        """既没标记也匹配不上代号 → 退出码 3 + NOT_A_COURSE_NOTE。"""
        plain = os.path.join(self.category, f"{uuid.uuid4()}_随手记.md")
        self.write(plain, "# 随手记\n\n今天天气不错。\n")
        rc, _, _ = self.run_cli(self.base_argv(["--path", plain, "--json"]))
        self.assertEqual(rc, 3)

    def test_path_not_found_is_exit_3(self):
        missing = os.path.join(self.category, "不存在.md")
        rc, _, _ = self.run_cli(self.base_argv(["--path", missing, "--json"]))
        self.assertEqual(rc, 3)

    # ---------------- P0：退出码 ----------------

    def test_exit_2_when_no_target(self):
        rc, _, _ = self.run_cli(self.base_argv(["--json"]))
        self.assertEqual(rc, 2)

    def test_exit_2_when_course_unknown(self):
        rc, _, _ = self.run_cli(self.base_argv(["--course", "west2-nope", "--json"]))
        self.assertEqual(rc, 2)

    def test_exit_3_when_note_missing_for_course(self):
        """课程存在但花笺里没有对应笔记 → 3（不是 1）。"""
        empty_data = os.path.join(self.tmp, "empty-huajian")
        os.makedirs(os.path.join(empty_data, "notes"), exist_ok=True)
        rc, _, _ = self.run_cli(["--west2", "--data-dir", empty_data,
                                 "--course", "west2-f0", "--json"])
        self.assertEqual(rc, 3)

    def test_default_system_path_resolution(self):
        """不传 --west2（= 真实学习路径 py-agent 体系）时，--path 同样能定位。"""
        p = os.path.join(self.category, f"{uuid.uuid4()}_第一课.md")
        self.write(p, note_text(marker="<!-- study: course=py-agent-01 -->",
                                title="# L1 · 语法速览"))
        rc, out, _ = self.run_cli(["--data-dir", self.data_dir, "--path", p,
                                   "--soft"])
        self.assertEqual(rc, 0, out)
        self.assertIn("py-agent-01", out)

    def test_exit_1_when_notes_empty(self):
        self.write(self.note_path, note_text(user=""))
        rc, out, _ = self.run_cli(self.base_argv(["--course", "west2-f0"]))
        self.assertEqual(rc, 1)
        self.assertIn("空", out)

    def test_exit_1_when_model_fails(self):
        def boom(*a, **k):
            raise RuntimeError("模拟断网")
        tidy_cli.tidy = boom
        rc, out, _ = self.run_cli(self.base_argv(["--course", "west2-f0"]))
        self.assertEqual(rc, 1)
        self.assertIn("整理失败", out)

    def test_exit_0_and_apply_writes(self):
        rc, out, _ = self.run_cli(self.base_argv(["--course", "west2-f0",
                                                  "--apply"]))
        self.assertEqual(rc, 0, out)
        self.assertIn("AI 整理", self.read(self.note_path))

    # ---------------- P0：--json 契约 ----------------

    def test_json_preview_stream_shape(self):
        """--json：stdout 是纯 JSONL，含 stage/report/done 且字段齐全。"""
        rc, out, _ = self.run_cli(self.base_argv(["--path", self.note_path,
                                                  "--json"]))
        self.assertEqual(rc, 0)
        events = self.json_lines(out)
        kinds = [e["type"] for e in events]
        self.assertIn("stage", kinds)
        self.assertIn("report", kinds)
        self.assertIn("done", kinds)

        report = next(e for e in events if e["type"] == "report")["payload"]
        for key in ("coverage", "note_dimension", "gaps", "todo",
                    "glossary_count"):
            self.assertIn(key, report)
        self.assertEqual(report["coverage"], 0.5)          # K1 覆盖 + K2 部分 = 1.5/3
        self.assertEqual(report["glossary_count"], 1)
        self.assertEqual([g["id"] for g in report["gaps"]], ["K2", "K3"])
        self.assertEqual(report["gaps"][0]["status"], "partial")

        done = next(e for e in events if e["type"] == "done")
        self.assertTrue(done["ok"])
        self.assertFalse(done["applied"])
        self.assertEqual(done["note_id"], self.note_id)
        self.assertEqual(done["changed"]["ai_zone"], "unchanged")

    def test_json_apply_reports_replaced(self):
        rc, out, _ = self.run_cli(self.base_argv(["--path", self.note_path,
                                                  "--json", "--apply"]))
        self.assertEqual(rc, 0)
        done = next(e for e in self.json_lines(out) if e["type"] == "done")
        self.assertTrue(done["applied"])
        self.assertEqual(done["changed"]["ai_zone"], "replaced")
        self.assertEqual(done["changed"]["history_appended"], 1)
        self.assertTrue(done["version"])

    def test_json_error_event_carries_code(self):
        plain = os.path.join(self.category, f"{uuid.uuid4()}_随手记.md")
        self.write(plain, "# 随手记\n\n无。\n")
        rc, out, _ = self.run_cli(self.base_argv(["--path", plain, "--json"]))
        self.assertEqual(rc, 3)
        events = self.json_lines(out)
        err = next(e for e in events if e["type"] == "error")
        self.assertEqual(err["code"], "NOT_A_COURSE_NOTE")

    def test_json_keeps_human_logs_off_stdout(self):
        """JSON 模式下人类日志走 stderr，stdout 只有 JSONL。"""
        rc, out, err = self.run_cli(self.base_argv(["--path", self.note_path,
                                                    "--json"]))
        self.assertEqual(rc, 0)
        self.json_lines(out)                     # 解析失败即不纯
        self.assertIn("你的笔记", err)            # 人话在 stderr

    def test_human_mode_stdout_unchanged(self):
        """不带 --json 时人话仍在 stdout（既有验证脚本依赖这个）。"""
        rc, out, err = self.run_cli(self.base_argv(["--path", self.note_path]))
        self.assertEqual(rc, 0)
        self.assertIn("你的笔记", out)
        self.assertNotIn("{", out.splitlines()[0])   # 第一行不是 JSON


class InterrogateCliPathTest(_CliHarness):
    """interrogate.py 的 `--path`（方案 §3.2）：与 tidy.py 共用同一份定位实现。

    用 `--offline` 跑，不调模型。
    """

    def run_interrogate(self, argv):
        from tools import interrogate as inter_cli
        old = sys.argv
        out = io.StringIO()
        sys.argv = ["interrogate.py"] + argv
        try:
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                rc = inter_cli.main()
        finally:
            sys.argv = old
        return rc, out.getvalue()

    def test_path_resolves_course(self):
        rc, out = self.run_interrogate(self.base_argv(["--path", self.note_path,
                                                       "--offline"]))
        self.assertEqual(rc, 0, out)
        self.assertIn("已识别课程 west2-f0", out)

    def test_rename_keeps_course_resolvable(self):
        renamed = os.path.join(self.category, f"{self.note_id}_环境搭建.md")
        os.replace(self.note_path, renamed)
        self.note_path = renamed
        rc, out = self.run_interrogate(self.base_argv(["--path", renamed,
                                                       "--offline"]))
        self.assertEqual(rc, 0, out)
        self.assertIn("已识别课程 west2-f0", out)

    def test_non_course_note_is_exit_3(self):
        plain = os.path.join(self.category, f"{uuid.uuid4()}_随手记.md")
        self.write(plain, "# 随手记\n\n无。\n")
        rc, _ = self.run_interrogate(self.base_argv(["--path", plain]))
        self.assertEqual(rc, 3)

    def test_no_target_is_exit_2(self):
        rc, _ = self.run_interrogate(self.base_argv([]))
        self.assertEqual(rc, 2)


class ScaffoldMarkerTest(unittest.TestCase):
    """P0：脚手架写出的笔记顶部带课程标记（按钮靠它认课，不靠文件名）。"""

    @classmethod
    def setUpClass(cls):
        from system import active_paths, course_index
        from tools import scaffold
        cls.scaffold = scaffold
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        system, placement = active_paths(base, west2=True)
        cls.course = course_index(system)["west2-f0"]
        cls.text = scaffold.course_note(system, cls.course, placement)

    def test_first_line_is_course_marker(self):
        first = self.text.splitlines()[0]
        # stage 用**内部键**（foundation）而不是显示标签（F0）：稳定标识，
        # 且正文里已经用 STAGE_LABEL 渲染出人话，标记只需机器可读。
        self.assertEqual(
            first,
            f"<!-- study: course=west2-f0 stage={self.course['stage']} -->")

    def test_marker_parses_back_to_course(self):
        cid, stage = tidy_cli.parse_course_marker(self.text)
        self.assertEqual(cid, "west2-f0")
        self.assertEqual(stage, self.course["stage"])

    def test_marker_is_invisible_in_markdown_render(self):
        """HTML 注释：花笺渲染时不可见（正文第一个可见元素仍是标题）。"""
        visible = [ln for ln in self.text.splitlines()
                   if ln.strip() and not ln.startswith("<!--")]
        self.assertTrue(visible[0].startswith("# F0 ·"), visible[0])

    def test_update_mode_scope_keeps_marker(self):
        """update 只替换「✍️ 我的笔记」之前的头部 —— 标记落在头部，故幂等刷新。"""
        heading = self.scaffold.NOTES_HEADING
        self.assertIn(heading, self.text)
        head = self.text.split(heading)[0]
        self.assertIn(
            f"<!-- study: course=west2-f0 stage={self.course['stage']} -->", head)


class ScaffoldMarkerDefaultSystemTest(unittest.TestCase):
    """九课体系（route.json，真实学习路径）的 course.stage 是空串。

    标记不能因此留下难看的 `stage=`；不传 --west2 时也该按路径定位。
    """

    @classmethod
    def setUpClass(cls):
        from system import active_paths, course_index
        from tools import scaffold
        cls.scaffold = scaffold
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        system, placement = active_paths(base)          # 不传 west2 = 活跃体系
        cls.course = course_index(system)["py-agent-01"]
        cls.text = scaffold.course_note(system, cls.course, placement)

    def test_marker_omits_empty_stage(self):
        self.assertEqual(self.text.splitlines()[0],
                         "<!-- study: course=py-agent-01 -->")

    def test_marker_parses_with_none_stage(self):
        cid, stage = tidy_cli.parse_course_marker(self.text)
        self.assertEqual(cid, "py-agent-01")
        self.assertIsNone(stage)


if __name__ == "__main__":
    unittest.main()
