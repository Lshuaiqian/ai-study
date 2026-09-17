#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从 west2 原文抽取「学习目的 / 学习内容 / 学习要求」并注入体系文件。

为什么要这一步
    笔记模板最上面要放**真实的考核要求**。如果我手写，就会失真；
    直接从 refs/learn-AI 的原始 Markdown 里按标题抽，才是原话。

用法：
    python study\\system\\enrich_from_west2.py            # 预览
    python study\\system\\enrich_from_west2.py --write    # 写回体系文件
"""
import io
import json
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYSTEM_PATH = os.path.join(BASE, "system", "west2-ai-2026.json")
SRC = os.path.join(os.path.dirname(BASE), "refs", "learn-AI")

# west2 文档 → 课程 id
DOC_MAP = {
    "tasks(2026)/foundation/task0.md": "west2-f0",
    "tasks(2026)/foundation/task1.md": "west2-f1",
    "tasks(2026)/foundation/task2.md": "west2-f2",
    "tasks(2026)/foundation/task3.md": "west2-f3",
    "tasks(2026)/foundation/task4.md": "west2-f4",
    "tasks(2026)/application/application0.md": "west2-a0",
    "tasks(2026)/application/application1.md": "west2-a1",
    "tasks(2026)/scientific-research/research1.md": "west2-r1",
    "tasks(2026)/others/backend-routine.md": "west2-be",
    "tasks(2026)/others/frontend-routine.md": "west2-fe",
    "tasks(2026)/others/statistic-routine.md": "west2-st",
}

WANTED = ("学习目的", "学习内容", "学习要求")


def sections(md_text):
    """按 `## 标题` 切段，返回 {标题: 正文}。"""
    out, cur, buf = {}, None, []
    for line in md_text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if cur:
                out[cur] = "\n".join(buf).strip()
            cur, buf = m.group(1).strip(), []
            continue
        # 遇到更高层级（#）说明本节结束
        if re.match(r"^#\s+", line) and cur:
            out[cur] = "\n".join(buf).strip()
            cur, buf = None, []
            continue
        if cur is not None:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf).strip()
    return out


def clean(text):
    """去掉 NOTE/TIP 提示块与多余空行，保留正文原话。"""
    lines, skip = [], False
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith(">"):
            skip = True          # 引用块（[!NOTE] / [!TIP]）跳过
            continue
        skip = False
        lines.append(line)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    out = []
    blank = 0
    for line in lines:
        if not line.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(line)
    return "\n".join(out)


def main():
    write = "--write" in sys.argv
    with open(SYSTEM_PATH, "r", encoding="utf-8") as f:
        system = json.load(f)
    courses = {c["course_id"]: c for c in system["courses"]}

    filled, missing = 0, []
    for rel, cid in DOC_MAP.items():
        path = os.path.join(SRC, rel.replace("/", os.sep))
        if not os.path.isfile(path):
            missing.append(rel)
            continue
        with open(path, "r", encoding="utf-8") as f:
            secs = sections(f.read())
        c = courses.get(cid)
        if not c:
            continue
        got = []
        for name in WANTED:
            body = clean(secs.get(name, ""))
            if body:
                c[name] = body
                got.append(f"{name}({len(body)}字)")
        print(f"  {cid:10s} ← {rel:48s} {'、'.join(got) or '（没抽到）'}")
        if got:
            filled += 1

    if missing:
        print(f"\n⚠️ 缺这些源文件（先跑 fetch_gh_repo.py）：{missing}")

    print(f"\n填充了 {filled}/{len(DOC_MAP)} 门课")
    if write:
        with open(SYSTEM_PATH, "w", encoding="utf-8") as f:
            json.dump(system, f, ensure_ascii=False, indent=2)
        print(f"已写回 {os.path.relpath(SYSTEM_PATH, BASE)}")
    else:
        print("（预览模式，未写入；加 --write 生效）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
