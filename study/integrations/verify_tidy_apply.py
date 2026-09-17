# -*- coding: utf-8 -*-
"""一键整理的端到端验证：**驱动真实的 CLI main()**，落到真实临时文件上。

不打模型（patch 掉 tidy 与 LLM），验的是"写文件那一段"到底有没有兑现承诺：

  A. 用户区字节级不变      —— AI 永不改动学习者写的东西
  B. 重复整理 = 覆写 AI 区  —— 不是一轮一轮堆叠
  C. 整理历史 append-only
  D. 预览零副作用           —— 不改笔记 / 不改 mastery.json / 不塞回炉队列
  E. 模型失败不毁稿
  F. metadata.json 写进 --data-dir，且不碰真实花笺目录
  G. --rollback 能回到旧整理稿，用户区仍然不动

运行：python study\\integrations\\verify_tidy_apply.py
"""
import difflib
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

from notedoctor.tidier import (AI_END, AI_HEADING, AI_START,     # noqa: E402
                               HISTORY_HEADING, USER_HEADING,
                               extract_user_notes)
from tools import tidy as tidy_cli                               # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name,
                         ("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def user_zone_diff(text, baseline):
    """返回 None 表示用户区逐字未变；否则给出可读的差异说明。"""
    got = extract_user_notes(text)
    if sha(got) == sha(baseline):
        return None
    d = list(difflib.unified_diff(baseline.splitlines(), got.splitlines(),
                                  "整理前", "整理后", lineterm=""))
    if d:
        return "\n".join(d[:24])
    return "仅空白差异：before=%r after=%r" % (baseline[-60:], got[-60:])


USER_BODY = """### 1. 我学到的（用自己的话）

装的是 3.12.3，必须勾 Add to PATH，不然命令行找不到 python。

```bash
python -m venv myenv
myenv\\Scripts\\activate
```

### 2. 作业记录

crazy-day.md 写完了，Hello World 和洛谷 5 题都过了。

### 3. 踩到的坑

一开始 python 命令不识别，重装勾 PATH 后好了。
洛谷 P1046 读入的是一整行数字，我当单个整数读了，错两次。

### 4. 待解决

虚拟环境和全局环境什么时候必须分开用？
"""

NOTE_TEMPLATE = """# F0 · 环境搭建与工程规范

## ⚡ 你的起点

已具备 5/9 个知识点。

## 📋 考核要求

- [ ] `t0-1` 装好 Python 与 IDE 并截图
- [ ] `t0-2` crazy-day.md 通过 markdownlint

---

{before}{user}

{after}"""


def make_note(before="", after=""):
    return NOTE_TEMPLATE.format(before=before, user=USER_HEADING + "\n\n" + USER_BODY,
                                after=after).rstrip() + "\n"


FEEDBACK = {
    "system_title": "Python·环境与工程规范",
    "theme": "Python 安装、venv 与 Git 基础",
    "preview": ["Python 安装与 PATH", "venv 隔离依赖"],
    "coverage": [{"id": "K1", "status": "covered", "why": "讲了安装与 PATH"},
                 {"id": "K2", "status": "partial", "why": "没提 IDE 配置"},
                 {"id": "K3", "status": "missing", "why": "没提 PEP 8"}],
    "glossary": [{"term": "虚拟环境", "def": "隔离项目依赖的独立运行环境"},
                 {"term": "PATH", "def": "系统查找可执行文件的环境变量"},
                 {"term": "venv", "def": "Python 自带的虚拟环境模块"}],
    "todo": ["补 IDE 配置"],
    "errors": [],
    "uncertain": [],
    "summary": "主干清楚，工具链要补。",
}

MARK_V1 = "## 一、Python 安装\n\n- 装了 3.12.3。\n"
MARK_V2 = "## 一、Python 安装（第二版）\n\n- 装了 3.12.3，并配好了 PATH。\n"


def run_cli(argv):
    """在真实 CLI 上跑一次，捕获 stdout。"""
    old_argv = sys.argv
    buf = io.StringIO()
    sys.argv = ["tidy.py"] + argv
    try:
        with redirect_stdout(buf):
            rc = tidy_cli.main()
    finally:
        sys.argv = old_argv
    return rc, buf.getvalue()


def main():
    tmp = tempfile.mkdtemp(prefix="tidyverify-")
    data_dir = os.path.join(tmp, "huajian")
    state_dir = os.path.join(tmp, "state")
    notes_dir = os.path.join(data_dir, "notes")
    category = os.path.join(notes_dir, "Python")
    os.makedirs(category, exist_ok=True)

    # 站在"别的笔记也要保住"的立场上，先放一篇无关笔记进索引
    other_id = str(uuid.uuid4())
    with open(os.path.join(category, f"{other_id}_别的课.md"), "w",
              encoding="utf-8") as f:
        f.write("# 别的课\n\n别人的笔记\n")
    with open(os.path.join(data_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump({"notes": [{"id": other_id, "title": "别的课", "fileName":
                              f"{other_id}_别的课.md", "category": "Python"}]},
                  f, ensure_ascii=False, indent=2)

    note_id = str(uuid.uuid4())
    note_path = os.path.join(category, f"{note_id}_F0-环境搭建与工程规范.md")
    pristine = make_note()
    with open(note_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(pristine)
    # 基准取自"同一函数在未动过的笔记上的输出"——整理后必须逐字相同。
    # （extract_user_notes 会 strip 首尾空行，所以不能直接拿 USER_BODY 比。）
    baseline_user = extract_user_notes(pristine)
    user_sha = sha(baseline_user)
    check("基准提取未丢正文", baseline_user.strip("\n") == USER_BODY.strip("\n"))

    real_data_dir = tidy_cli.discover()["data_dir"]
    real_meta = os.path.join(real_data_dir, "metadata.json")
    real_meta_before = (sha(open(real_meta, encoding="utf-8").read())
                        if os.path.isfile(real_meta) else None)

    calls = {"n": 0}

    def fake_tidy(llm, curriculum, note_text):
        calls["n"] += 1
        return {"markdown": MARK_V1 if calls["n"] == 1 else MARK_V2,
                "feedback": FEEDBACK, "notes_used": extract_user_notes(note_text)}

    orig_tidy, orig_llm, orig_state = tidy_cli.tidy, tidy_cli.LLM, tidy_cli.STATE_DIR
    tidy_cli.tidy, tidy_cli.LLM, tidy_cli.STATE_DIR = fake_tidy, (lambda *a, **k: None), state_dir
    try:
        # ---------- D. 预览零副作用 ----------
        rc, out = run_cli(["--course", "west2-f0", "--west2", "--data-dir", data_dir])
        check("D 预览返回 0", rc == 0, out[-400:])
        check("D 预览未写笔记", open(note_path, encoding="utf-8").read() == pristine)
        check("D 预览未建快照目录",
              not os.path.isdir(os.path.join(state_dir, "note_versions")),
              os.listdir(state_dir) if os.path.isdir(state_dir) else "no state dir")
        check("D 预览未写 mastery.json",
              not os.path.isfile(os.path.join(state_dir, "mastery.json")))
        check("D 预览未写 findings",
              not os.path.isdir(os.path.join(state_dir, "findings")))
        check("D 预览未写 events",
              not os.path.isfile(os.path.join(state_dir, "events.jsonl")))
        check("D 预览仍显示 note 维度", "note 维度" in out)
        check("D 预览提示零副作用", "掌握度" in out and "没有改动" in out)

        # ---------- A/B/C/F. 第一次 apply ----------
        rc, out = run_cli(["--course", "west2-f0", "--west2", "--data-dir", data_dir,
                           "--apply"])
        check("apply 返回 0", rc == 0, out[-600:])
        t1 = open(note_path, encoding="utf-8").read()

        check("A 用户区字节级不变", user_zone_diff(t1, baseline_user) is None,
              user_zone_diff(t1, baseline_user))
        check("A 笔记含 v1 整理稿", "Python 安装" in t1)
        check("B AI 标题只 1 个", t1.count(AI_HEADING) == 1,
              "count=%d" % t1.count(AI_HEADING))
        check("B AI 标记成对", t1.count(AI_START) == 1 and t1.count(AI_END) == 1)
        check("C 历史 1 行", t1.count(HISTORY_HEADING) == 1)
        hist1 = [l for l in t1.splitlines() if l.startswith("- `20")]
        check("C 历史有 1 条记录", len(hist1) == 1, hist1)

        # F. metadata 落在 --data-dir，真实花笺目录未被碰
        meta = json.load(open(os.path.join(data_dir, "metadata.json"), encoding="utf-8"))
        ids = [n["id"] for n in meta["notes"]]
        check("F 新笔记进索引", note_id in ids, ids)
        check("F 旧笔记未丢", other_id in ids, ids)
        check("F 标题取自文件名", next(n["title"] for n in meta["notes"]
                                       if n["id"] == note_id).startswith("F0-"),
              [n["title"] for n in meta["notes"]])
        real_meta_after = (sha(open(real_meta, encoding="utf-8").read())
                           if os.path.isfile(real_meta) else None)
        check("F 真实花笺 metadata 未被改动", real_meta_before == real_meta_after,
              "real dir touched: %s" % real_data_dir)

        # ---------- 掌握度反馈落地 ----------
        check("反馈写 findings",
              os.path.isfile(os.path.join(state_dir, "findings", "west2-f0-tidy.json")))
        mastery = json.load(open(os.path.join(state_dir, "mastery.json"), encoding="utf-8"))
        check("反馈入 mastery.lessons",
              "west2-f0" in mastery.get("lessons", {}),
              list(mastery.get("lessons", {})))
        check("note 维度已写入",
              mastery["lessons"]["west2-f0"]["dims"].get("note", 0) > 0,
              mastery["lessons"]["west2-f0"]["dims"])
        check("缺口进 atoms",
              set(mastery["atoms"]) == {"west2-f0:K2", "west2-f0:K3"},
              list(mastery["atoms"]))
        check("已覆盖的不进队列", "west2-f0:K1" not in mastery["atoms"])
        events = open(os.path.join(state_dir, "events.jsonl"), encoding="utf-8").read()
        check("事件流有 note_review", "note_review" in events, events[-200:])

        # ---------- B/C/A. 第二次 apply ----------
        rc, out = run_cli(["--course", "west2-f0", "--west2", "--data-dir", data_dir,
                           "--apply"])
        check("二次 apply 返回 0", rc == 0, out[-600:])
        t2 = open(note_path, encoding="utf-8").read()
        check("B 二次整理未堆叠（AI 标题仍 1）", t2.count(AI_HEADING) == 1,
              "count=%d" % t2.count(AI_HEADING))
        check("B 二次整理未堆叠（标记仍 1 对）",
              t2.count(AI_START) == 1 and t2.count(AI_END) == 1)
        check("B 旧整理稿被替换", "Python 安装（第二版）" in t2 and "Python 安装\n" not in t2)
        check("A 二次整理后用户区仍不变", user_zone_diff(t2, baseline_user) is None,
              user_zone_diff(t2, baseline_user))
        hist2 = [l for l in t2.splitlines() if l.startswith("- `20")]
        check("C 历史累计", len(hist2) >= len(hist1),
              "%r -> %r" % (hist1, hist2))

        # ---------- E. 模型失败不毁稿 ----------
        def boom(*a, **k):
            raise RuntimeError("network down")
        tidy_cli.tidy = boom
        snapshot = open(note_path, encoding="utf-8").read()
        mastery_path = os.path.join(state_dir, "mastery.json")
        mastery_snapshot = open(mastery_path, encoding="utf-8").read()
        rc, out = run_cli(["--course", "west2-f0", "--west2", "--data-dir", data_dir,
                           "--apply"])
        check("E 模型失败非零退出", rc != 0, rc)
        check("E 模型失败给的是人话不是栈", "整理失败" in out and "Traceback" not in out,
              out[-300:])
        check("E 模型失败不毁稿", open(note_path, encoding="utf-8").read() == snapshot)
        check("E 模型失败不动掌握度",
              open(mastery_path, encoding="utf-8").read() == mastery_snapshot)
        tidy_cli.tidy = fake_tidy

        # ---------- G. 回滚 ----------
        snaps = sorted(f[:-3] for f in
                       os.listdir(os.path.join(state_dir, "note_versions", note_id))
                       if f.endswith(".md"))
        check("G 有 >=2 份快照", len(snaps) >= 2, snaps)
        target = snaps[0]
        rc, out = run_cli(["--course", "west2-f0", "--west2", "--data-dir", data_dir,
                           "--rollback", target])
        check("G 回滚返回 0", rc == 0, out[-400:])
        t3 = open(note_path, encoding="utf-8").read()
        check("G 回滚后用户区仍不变", user_zone_diff(t3, baseline_user) is None,
              user_zone_diff(t3, baseline_user))
        check("G 回滚写进 AI 区", "已回滚到" in t3 and target in t3)
        check("G 回滚未堆叠", t3.count(AI_HEADING) == 1,
              "count=%d" % t3.count(AI_HEADING))
        check("G 回滚也在历史里留痕", "回滚" in t3)

        # ---------- 软整理：不该碰掌握度 ----------
        mastery_before = open(os.path.join(state_dir, "mastery.json"),
                              encoding="utf-8").read()
        rc, out = run_cli(["--course", "west2-f0", "--west2", "--data-dir", data_dir,
                           "--soft", "--apply"])
        check("soft apply 返回 0", rc == 0, out[-400:])
        check("soft 不改掌握度",
              open(os.path.join(state_dir, "mastery.json"), encoding="utf-8").read()
              == mastery_before)
        check("soft 后用户区仍不变（只动 AI 区）",
              user_zone_diff(open(note_path, encoding="utf-8").read(),
                             baseline_user) is None)

        # ---------- 脚手架模板不该被当成"有内容" ----------
        scaffold_id = str(uuid.uuid4())
        scaffold_path = os.path.join(category, f"{scaffold_id}_F2-网络爬虫与数据分析.md")
        with open(scaffold_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("# F2 · 网络爬虫与数据分析\n\n"
                    "（写完后运行：`python study\\tools\\interrogate.py --course west2-f2`）\n\n"
                    + USER_HEADING + "\n\n"
                    "### 1. 我学到的（用自己的话）\n\n"
                    "<!-- 不要抄资料；写你真正理解了什么 -->\n\n"
                    "### 2. 作业记录\n\n"
                    "<!-- 每道作业：做了什么、结果如何、卡在哪 -->\n")
        calls_before = calls["n"]
        rc, out = run_cli(["--course", "west2-f2", "--west2", "--data-dir", data_dir])
        check("脚手架模板被拒（非零退出）", rc != 0, rc)
        check("脚手架模板给出人话提示",
              "模板注释" in out and "Traceback" not in out, out[-300:])
        check("脚手架模板没白调模型", calls["n"] == calls_before,
              "%d -> %d" % (calls_before, calls["n"]))
        check("脚手架模板的笔记没被改",
              "不要抄资料" in open(scaffold_path, encoding="utf-8").read())
    finally:
        tidy_cli.tidy, tidy_cli.LLM, tidy_cli.STATE_DIR = orig_tidy, orig_llm, orig_state
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 62)
    if FAILS:
        print("失败 %d 项：" % len(FAILS))
        for f in FAILS:
            print("  · " + f)
        return 1
    print("全部通过：用户区零改动 / AI 区覆写不堆叠 / 历史只追加 / 预览零副作用")
    print("          / 模型失败不毁稿 / metadata 不越界 / 回滚可用")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
