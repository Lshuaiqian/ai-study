#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
"""往花笺的课程笔记里灌一段「示例笔记」，用于演示一键整理。

⚠️ 这是演示数据，不是你写的。看完可以把「✍️ 我的笔记」下面的内容清掉。

用法：
    python study\\integrations\\seed_demo_note.py --course west2-f0 --yes
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "tools"))

from notes import discover, make_entry, read_note, upsert_metadata  # noqa: E402
from interrogate import find_note                                   # noqa: E402
from system import load_system                                      # noqa: E402

SYSTEM_PATH = os.path.join(BASE, "system", "west2-ai-2026.json")

SAMPLE = {
    "west2-f0": """### 1. 我学到的（用自己的话）

Python 装 3.12.3，装的时候勾 Add Python to PATH，否则命令行找不到 python。
虚拟环境用 `python -m venv myenv`，Windows 激活是 `myenv\\Scripts\\activate`，
目的是隔离不同项目的依赖，避免版本冲突。pip 慢就挂清华源。

Markdown 基本语法：多级标题 `#`、图片 `![]()`、链接 `[]()`、代码块 ``` ```、表格用 `|`。
苹果规范我记的是：中英文之间要有空格（"Python 环境"而不是"Python环境"），
中文和数字之间也要空格（"3 天"），但数字和单位之间不加（"8GB"），
中文语境一律用全角标点。

Git 我学会了 add / commit / push 三个命令，.gitignore 用来排除不该传的文件，
commit 信息要写清楚做了什么。大文件不要传 GitHub。

### 2. 作业记录

- 环境搭好了，截图在 attachments 里
- crazy-day.md 写完了，暂时还没跑 markdownlint
- Hello World 和洛谷 5 题都过了

### 3. 踩到的坑

一开始 `python` 命令不认，重装勾了 Add to PATH 才好的。
P1046 那题读入的是一整行数字，我一开始当成一个整数读，错了两次。

### 4. 还没搞懂的

- 虚拟环境和全局环境到底什么时候必须分开
- commit 信息有没有固定格式
""",
}


def main():
    argv = sys.argv[1:]
    course_id = argv[argv.index("--course") + 1] if "--course" in argv else "west2-f0"
    if "--yes" not in argv:
        print("这是写操作：会往花笺的课程笔记里追加示例内容。确认后加 --yes。")
        return 2
    if course_id not in SAMPLE:
        print(f"没有 {course_id} 的示例笔记")
        return 2

    system = load_system(SYSTEM_PATH)
    d = discover()
    note = find_note(d["notes_dir"], course_id, system)
    if not note:
        print("先在花笺里建课程笔记：scaffold.py apply --yes")
        return 1

    text = read_note(note["path"])
    marker = "## ✍️ 我的笔记"
    idx = text.find(marker)
    if idx < 0:
        print("笔记结构不对，找不到「我的笔记」段")
        return 1

    head = text[:idx + len(marker)]
    new_text = head + "\n\n" + SAMPLE[course_id] + "\n"
    with open(note["path"], "w", encoding="utf-8") as f:
        f.write(new_text)
    upsert_metadata(d["data_dir"], make_entry(
        note["id"] or "", note["title"], os.path.basename(note["path"]),
        note["category"], new_text))
    print(f"✅ 已把示例笔记写入 {note['title']}（{len(SAMPLE[course_id])} 字）")
    print("   下一步：python study\\tools\\interrogate.py --course " + course_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
