# -*- coding: utf-8 -*-
"""「一键整理 ⇄ AI 质询」交替循环的端到端验证（真实文件，只把模型换成替身）。

验的是两个 AI 区块**能不能长期共存**，以及整理结果**有没有真的喂回给 AI**：

  A. 用户区在多轮交替后仍字节级不变
  B. 整理区 / 质询区各自整块替换：标题与标记恒为 1 份，不越滚越长
  C. 整理不吃质询、质询不吃整理
  D. 结构分隔线不随轮次增长
  E. 整理的缺口真的进了质询提示词（反馈给 AI 的硬证据）
  F. 覆盖率不被 AI 自己写的整理稿抬高（AI 不能给自己打分）
  G. metadata 只写 --data-dir，真实花笺目录零改动

运行：python study\\integrations\\verify_note_loop.py
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import uuid
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
if STUDY not in sys.path:
    sys.path.insert(0, STUDY)

from notedoctor.doctor import check_coverage                      # noqa: E402
from notedoctor.interrogator import split_note                    # noqa: E402
from notedoctor.tidier import (AI_HEADING, HISTORY_HEADING,       # noqa: E402
                               QUIZ_HEADING, USER_HEADING,
                               extract_user_notes)
from system import course_index, load_system, to_curriculum       # noqa: E402
from tools import interrogate as inter_cli                        # noqa: E402
from tools import tidy as tidy_cli                                # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name,
                         ("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


USER_BODY = """### 1. 我学到的（用自己的话）

装的是 3.12.3，必须勾 Add to PATH，不然命令行找不到 python。
用 python -m venv myenv 建虚拟环境隔离依赖；pip 慢就换清华源。

### 2. 作业记录

crazy-day.md 写完了，Hello World 和洛谷 5 题都过了。

### 3. 踩到的坑

一开始 python 命令不识别，重装勾 PATH 后好了。
洛谷 P1046 读入的是一整行数字，我当单个整数读了，错两次。

### 4. 还没搞懂的

虚拟环境和全局环境什么时候必须分开用？
"""

NOTE = """# F0 · 环境搭建与工程规范

## ⚡ 你的起点

已具备 5/9 个知识点。

## 📋 考核要求

### 作业清单

- [ ] `t0-1` 装好 Python 与 IDE 并截图
- [ ] `t0-2` crazy-day.md 通过 markdownlint

---

{user}
"""


def make_note():
    return NOTE.format(user=USER_HEADING + "\n\n" + USER_BODY)


FEEDBACK = {
    "system_title": "Python·环境与工程规范",
    "theme": "Python 安装、venv 与 Git 基础",
    "preview": ["Python 安装与 PATH", "venv 隔离依赖"],
    "coverage": [{"id": "K1", "status": "covered", "why": "讲了安装与 PATH"},
                 {"id": "K2", "status": "partial", "why": "完全没提 IDE 与编辑器配置"},
                 {"id": "K3", "status": "missing", "why": "没提 PEP 8 与类型检查"}],
    "glossary": [{"term": "虚拟环境", "def": "隔离项目依赖的独立运行环境"}],
    "todo": ["补 IDE 配置", "运行 markdownlint 检查 crazy-day.md"],
    "errors": [],
    "uncertain": [{"quote": "8GB 不加空格", "reason": "可能记错"}],
    "summary": "主干清楚，工具链要补。",
}


def run(fn):
    old_argv = sys.argv
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = fn()
    finally:
        sys.argv = old_argv
    return rc, buf.getvalue()


class FakeLLM:
    """替身模型：记录提示词，回一个结构合法的质询结果。"""

    def __init__(self):
        self.prompts = []

    def chat(self, system, user, **kw):
        self.prompts.append(user)
        return {"verdicts": [{"id": "K1", "verdict": "pass", "why": "讲了安装"}],
                "questions": [{"for": "K2", "question": "VS Code 里怎么做保存即格式化？"}],
                "errors": [], "uncertain": [], "todo": [], "summary": "主干可以。"}

    def report(self):
        return "[替身模型：1 次调用]"


def main():
    tmp = tempfile.mkdtemp(prefix="noteloop-")
    data_dir = os.path.join(tmp, "huajian")
    state_dir = os.path.join(tmp, "state")
    notes_dir = os.path.join(data_dir, "notes")
    category = os.path.join(notes_dir, "西二AI-2026")
    os.makedirs(category, exist_ok=True)

    note_id = str(uuid.uuid4())
    note_path = os.path.join(category, f"{note_id}_F0-环境搭建.md")
    pristine = make_note()
    with open(note_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(pristine)
    baseline_user = extract_user_notes(pristine)
    user_sha = sha(baseline_user)
    check("基准提取未丢正文", baseline_user.strip("\n") == USER_BODY.strip("\n"))

    real_data_dir = tidy_cli.discover()["data_dir"]
    real_meta = os.path.join(real_data_dir, "metadata.json")
    real_before = (sha(open(real_meta, encoding="utf-8").read())
                   if os.path.isfile(real_meta) else None)

    fake = FakeLLM()
    tidy_calls = {"n": 0}

    def fake_tidy(llm, curriculum, note_text):
        tidy_calls["n"] += 1
        return {"markdown": f"## 一、Python 安装（第 {tidy_calls['n']} 版）\n\n- 3.12.3。\n",
                "feedback": FEEDBACK,
                "notes_used": extract_user_notes(note_text)}

    orig = (tidy_cli.tidy, tidy_cli.LLM, tidy_cli.STATE_DIR,
            inter_cli.LLM, inter_cli.STATE_DIR)
    tidy_cli.tidy, tidy_cli.LLM, tidy_cli.STATE_DIR = fake_tidy, (lambda *a, **k: None), state_dir
    inter_cli.LLM = lambda *a, **k: fake
    inter_cli.STATE_DIR = state_dir
    try:
        def tidy_apply():
            sys.argv = ["tidy.py", "--course", "west2-f0", "--west2", "--data-dir", data_dir, "--apply"]
            return tidy_cli.main()

        def quiz_writeback():
            sys.argv = ["interrogate.py", "--course", "west2-f0",
                        "--west2", "--data-dir", data_dir, "--write-back"]
            return inter_cli.main()

        # ---------- 第 1 轮：整理 → 质询 ----------
        rc, out = run(tidy_apply)
        check("第1轮整理成功", rc == 0, out[-400:])
        t1 = open(note_path, encoding="utf-8").read()
        check("A 整理后用户区不变", sha(extract_user_notes(t1)) == user_sha)
        check("整理稿已写入", "（第 1 版）" in t1)

        rc, out = run(quiz_writeback)
        check("第1轮质询成功", rc == 0, out[-500:])
        q1 = open(note_path, encoding="utf-8").read()
        check("A 质询后用户区不变", sha(extract_user_notes(q1)) == user_sha)
        check("C 质询没吃掉整理稿", "（第 1 版）" in q1)
        check("质询区已写入", QUIZ_HEADING in q1 and "保存即格式化" in q1)

        # E. 反馈给 AI 的硬证据：缺口进了提示词
        check("E 质询确实调了模型", len(fake.prompts) == 1, len(fake.prompts))
        prompt = fake.prompts[-1] if fake.prompts else ""
        check("E 提示词带入上一轮缺口", "上一轮一键整理的缺口" in prompt, prompt[:200])
        check("E 缺口具体内容在里面", "完全没提 IDE 与编辑器配置" in prompt, prompt[:400])
        check("E 待办也在里面", "补 IDE 配置" in prompt)
        check("E 要求模型独立判断不放行", "独立判断" in prompt)
        check("E 提示词里没有 AI 整理稿",
              "## 一、Python 安装" not in prompt, "AI 稿混进了学生笔记")

        # ---------- 第 2 轮：再整理 ----------
        rc, out = run(tidy_apply)
        check("第2轮整理成功", rc == 0, out[-400:])
        t2 = open(note_path, encoding="utf-8").read()
        check("A 二次整理后用户区仍不变", sha(extract_user_notes(t2)) == user_sha)
        check("C 整理没吃掉质询区", "保存即格式化" in t2)
        check("B 整理区已替换为第 2 版", "（第 2 版）" in t2)
        check("B 整理区只有 1 份", t2.count(AI_HEADING) == 1, t2.count(AI_HEADING))

        # ---------- 第 3 轮：再质询 ----------
        rc, out = run(quiz_writeback)
        check("第2轮质询成功", rc == 0, out[-500:])
        q2 = open(note_path, encoding="utf-8").read()
        check("A 二次质询后用户区仍不变", sha(extract_user_notes(q2)) == user_sha)
        check("C 质询没吃掉整理稿（第 2 版还在）", "（第 2 版）" in q2)
        check("B 质询区只有 1 份", q2.count(QUIZ_HEADING) == 1, q2.count(QUIZ_HEADING))
        check("B 整理区仍只有 1 份", q2.count(AI_HEADING) == 1)
        check("B 历史区仍只有 1 个", q2.count(HISTORY_HEADING) == 1)
        check("B 质询标记成对且只有 1 对",
              q2.count("<!-- quiz:start") == 1 and q2.count("<!-- quiz:end -->") == 1)
        check("D 分隔线未随轮次增长",
              q2.count("---") == q1.count("---"),
              "%d -> %d" % (q1.count("---"), q2.count("---")))
        check("B 质询区是替换而非追加",
              q2.count("保存即格式化") == 1, q2.count("保存即格式化"))

        # F. AI 不能给自己打分：覆盖率只按学生写的内容算
        system = load_system(os.path.join(STUDY, "system", "west2-ai-2026.json"))
        curriculum = to_curriculum(system, course_index(system)["west2-f0"])
        _, notes_pristine = split_note(pristine)
        _, notes_final = split_note(q2)
        cov_a = check_coverage(curriculum["declares"], notes_pristine)
        cov_b = check_coverage(curriculum["declares"], notes_final)
        check("F 覆盖率未被 AI 稿抬高",
              cov_a["must_cover_ratio"] == cov_b["must_cover_ratio"],
              "%s -> %s" % (cov_a["must_cover_ratio"], cov_b["must_cover_ratio"]))
        check("F 学生笔记部分不含质询区", "保存即格式化" not in notes_final)
        check("F 学生笔记部分不含整理区", "## 一、Python 安装" not in notes_final)

        # G. metadata 落在 --data-dir
        with open(os.path.join(data_dir, "metadata.json"), encoding="utf-8") as f:
            meta = json.load(f)
        check("G 笔记在索引里", note_id in [n["id"] for n in meta["notes"]])
        real_after = (sha(open(real_meta, encoding="utf-8").read())
                      if os.path.isfile(real_meta) else None)
        check("G 真实花笺 metadata 未被动", real_before == real_after, real_data_dir)

        # 结论：三轮交替后文件结构仍然干净
        print("\n---- 交替三轮后的笔记结构 ----")
        for line in q2.splitlines():
            if line.startswith("#") or line.startswith("<!--"):
                print("   " + line)
    finally:
        (tidy_cli.tidy, tidy_cli.LLM, tidy_cli.STATE_DIR,
         inter_cli.LLM, inter_cli.STATE_DIR) = orig
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 62)
    if FAILS:
        print("失败 %d 项：" % len(FAILS))
        for f in FAILS:
            print("  · " + f)
        return 1
    print("全部通过：两个 AI 区块长期共存 / 各自覆写不堆叠 / 缺口真的喂回给 AI")
    print("          / 覆盖率不被 AI 稿抬高 / 用户区零改动 / 不越界写真实花笺")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
