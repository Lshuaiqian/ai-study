#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
"""一键整理：在花笺笔记上跑「AI 质询 + 查缺补漏 + 达成度」。

用法：
    python study\\tools\\interrogate.py --course west2-f2              # 正常（调用模型做质询）
    python study\\tools\\interrogate.py --course west2-f2 --offline     # 只算覆盖率与作业进度
    python study\\tools\\interrogate.py --course west2-f2 --write-back  # 把结果回填到笔记末尾
    python study\\tools\\interrogate.py --list                          # 列出已有的课程笔记
"""
import os
import re
import sys
from datetime import datetime

# 用 reconfigure 而不是新建 TextIOWrapper：后者在「一个工具 import 另一个工具」时
# 会重复包装同一个 buffer，先前那个被回收时把 buffer 关掉，报 I/O operation on closed file。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.config import load_config                              # noqa: E402
from core.llm import LLM                                         # noqa: E402
from core.store import write_text                                # noqa: E402
from notedoctor.interrogator import (empty_interrogation,        # noqa: E402
                                     interrogate, prior_gaps,
                                     render_prior, render_report,
                                     score, split_note, task_progress,
                                     write_state)
from notedoctor.tidier import compose_quiz, user_substance          # noqa: E402
from notes import discover, make_entry, read_note, scan, upsert_metadata  # noqa: E402
from system import (CODE_LABEL, course_index, load_placement,     # noqa: E402
                    load_system, protection_map, to_curriculum)
# 课程标记 / 按路径定位与 tidy.py 共用同一份实现：两处各写一遍必然漂移，
# 而花笺按钮传的正是 --path —— 两个工具必须给出同一个答案。
from tools.tidy import (find_note_by_path, resolve_course_from_path,  # noqa: E402
                        synthesize_note)

SYSTEM_PATH = None      # 运行时由 active_paths 决定（见 system/active.py）
PLACEMENT_PATH = None      # 运行时由 active_paths 决定
STATE_DIR = os.path.join(BASE, "state")   # 与体系路径分开：测试只重定向 state


def _arg(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def find_note(notes_dir, course_id, system=None):
    """按课程短代号前缀在花笺里找对应笔记。"""
    code = CODE_LABEL.get(course_id, course_id)
    for n in scan(notes_dir):
        if n["title"].startswith(code + "-") or n["title"].startswith(code + " "):
            return n
    return None


def cmd_list(system):
    d = discover()
    courses = course_index(system)
    print(f"花笺 notesDir：{d['notes_dir']}\n")
    for cid in courses:
        n = find_note(d["notes_dir"], cid, system)
        code = CODE_LABEL.get(cid, cid)
        if n:
            print(f"  ✅ {code:3s} {n['title']}  ({os.path.basename(n['path'])})")
        else:
            print(f"  ⬜ {code:3s} （还没建：{courses[cid]['title']}）")
    return 0


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    system = _active_system()
    if argv[0] == "--list":
        return cmd_list(system)

    course_id = _arg(argv, "--course")
    path_arg = _arg(argv, "--path")
    if not course_id and not path_arg:
        print("需要 --course <course_id> 或 --path <笔记路径>（可用 --list 查看）")
        return 2

    d = discover(_arg(argv, "--data-dir"))

    # --path 优先：花笺按钮只传路径；标题改名（= 改文件名）后仍要认得出课程
    if path_arg:
        if not os.path.isfile(path_arg):
            print(f"❌ 找不到笔记文件：{path_arg}")
            return 3
        resolved, _stage, how = resolve_course_from_path(path_arg, d["notes_dir"])
        if not resolved:
            print("❌ 这不是课程笔记：正文没有课程标记，标题也匹配不上课程代号")
            print("   先跑 scaffold.py apply --yes 建立课程笔记")
            return 3
        course_id = resolved
        print(f"🔎 已识别课程 {course_id}（来源：{how}）")

    courses = course_index(system)
    if course_id not in courses:
        print(f"没有课程 {course_id}")
        return 2
    curriculum = to_curriculum(system, courses[course_id],
                               _active_placement())
    protected = protection_map(curriculum)

    if path_arg:
        note = find_note_by_path(d["notes_dir"], path_arg) or synthesize_note(path_arg)
    else:
        note = find_note(d["notes_dir"], course_id, system)
    if not note:
        print(f"❌ 花笺里找不到 {course_id} 的笔记。先跑："
              f"python study\\tools\\scaffold.py apply --yes")
        return 3

    text = read_note(note["path"])
    req_part, notes_part = split_note(text)
    progress = task_progress(req_part)

    n_substance = len(re.sub(r"\s+", "", user_substance(text)))
    print(f"📄 {note['title']}  ({os.path.basename(note['path'])})")
    print(f"   考核要求 {len(req_part)} 字｜我的笔记 {n_substance} 字（模板注释不计）｜"
          f"知识点 {len(curriculum['declares']['knowledge'])} 个")

    if "--offline" in argv or n_substance < 10:
        if n_substance < 10:
            print("   （我的笔记还是空的或只有模板注释，跳过 AI 质询）")
        inter = empty_interrogation()
    else:
        # 上一轮「一键整理」发现的缺口 → 本轮质询优先追问（反馈给 AI 的入口）
        prior = prior_gaps(STATE_DIR, course_id)
        if prior and prior["gaps"]:
            print(f"   ↻ 带入上一轮整理的 {len(prior['gaps'])} 个缺口"
                  f"（{prior['tidied_at'][:19]}）作为重点追问方向")
        print("   ⏳ 正在做 AI 质询……")
        llm = LLM(load_config())
        inter = interrogate(llm, curriculum, notes_part, progress, prior=prior)
        print("   " + llm.report())

    result = score(curriculum, notes_part, inter, progress)
    report = render_report(curriculum, result, inter, progress)
    print()
    print(report)

    # 反馈进掌握度：真实质询过才写。离线/空笔记不写——
    # 否则一次「没质询」会把状态刷成空结果，等于拿噪声改掌握度。
    if n_substance >= 10 and "--offline" not in argv:
        payload, queued = write_state(STATE_DIR, course_id,
                                      note["id"] or "", result, inter,
                                      protected=protected)
        held = [k for k in queued if k.split(":", 1)[1] in protected]
        print(f"\n↳ 已反馈进掌握度：达成度 {payload['percent']:.0%}"
              f"（{payload['level']}）｜缺口 {len(queued)} 个进补练与复习队列")
        if held:
            print(f"   其中 {len(held)} 个 placement 判定「已具备/挂账」——"
                  f"只标待复核，没有摘牌：{'、'.join(held)}")

    if "--write-back" in argv:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        body = (f"### 结论（{stamp}）\n\n"
                f"- 达成度 **{result['percent']:.0%}**（{result['level']}）\n"
                f"- {'✅ 可以选择跳过进下一课' if result['can_skip'] else '⛔ 暂不建议跳过'}\n"
                + "".join(f"- ⛔ {b}\n" for b in result["blockers"])
                + ("\n### 质询（先自己答，再看下一轮整理）\n\n"
                   + "".join(f"- ❓ {q.get('question')}\n"
                            for q in inter.get("questions") or [])
                   if inter.get("questions") else ""))
        new_text = compose_quiz(text, body, ts=stamp, percent=result["percent"])
        write_text(note["path"], new_text)
        upsert_metadata(d["data_dir"], make_entry(
            note["id"] or "", note["title"], os.path.basename(note["path"]),
            note["category"], new_text))
        print(f"\n✅ 已写入「🧪 AI 质询」区（整块替换，不会越写越长）："
              f"{os.path.basename(note['path'])}")

    print(f"\n【下一步由你决定】{course_id}：" +
          ("可以跳过，直接学下一课" if result["can_skip"] else "建议先把上面的缺口补掉"))
    return 0



# ---------------------------------------------------------------- 数据入口
# 体系换过一次骨架（西二 11 门课 → 老 9 课）。硬编码文件路径的结果是
# 「工具还在照旧课表找课程」，所以统一从这里取。`--west2` 可切回原课表做对照。

def _active_system():
    from system import active_paths
    return active_paths(BASE, west2="--west2" in sys.argv)[0]


def _active_placement():
    from system import active_paths
    return active_paths(BASE, west2="--west2" in sys.argv)[1]

if __name__ == "__main__":
    sys.exit(main())
