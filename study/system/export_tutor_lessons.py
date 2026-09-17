#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
"""从知识体系生成 python-tutor 的课程表（lessons.json）。

要解决的问题
    导师原来的 lessons.json 是 9 课的老路线，与 west2 2026 体系对不上 ——
    实测出现过「导师说进入第 4 课（爬虫），而它自己的课程表里第 4 课是数据分析」。
    课程表的**唯一真源应该是体系**，导师只是体系的一个教学前端。

映射
    体系课程  →  导师的一课
    title     →  title
    学习目的  →  goal（west2 原文）
    knowledge →  knowledge（字符串列表）
    tasks     →  exercise（把任务标题与要求拼成一段作业说明）
    self_check→  self_check（只取问题，判定点留给 study 判分用）

用法
    python study\\system\\export_tutor_lessons.py                 # 预览
    python study\\system\\export_tutor_lessons.py --write         # 写入 E:\\Agents\\python-tutor\\lessons.json
    python study\\system\\export_tutor_lessons.py --write --out X  # 写到别处
"""
import io
import json
import os
import shutil
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from system import load_placement, placement_report, topo_courses  # noqa: E402

SYSTEM_PATH = None      # 运行时由 active_paths 决定（见 system/active.py）
PLACEMENT_PATH = None      # 运行时由 active_paths 决定
DEFAULT_OUT = r"E:\Agents\python-tutor\lessons.json"

# 导师先教这一段：Foundation 五课。分流后的课程等到那一步再切。
DEFAULT_SCOPE = ["west2-f0", "west2-f1", "west2-f2", "west2-f3", "west2-f4"]


def _arg(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def build_lessons(system, scope=None):
    # scope 默认取**体系的拓扑序**，而不是硬编码名单：名单是西二 F0–F4 五课时留下的，
    # 换成老 9 课之后它一条都对不上——表现是「生成 0 课」，静默地什么都没导出。
    scope = scope or topo_courses(system) or DEFAULT_SCOPE
    courses = {c["course_id"]: c for c in system["courses"]}
    know = {k["id"]: k for k in system["knowledge"]}
    out = []
    for i, cid in enumerate(scope, start=1):
        c = courses.get(cid)
        if not c:
            continue
        knowledge = [know[g]["name"] for g in c["knowledge"] if g in know]

        # 作业说明：把任务拼成一段可读文本，导师会照它布置作业
        lines = []
        for t in c.get("tasks") or []:
            deliverable = t.get("deliverable") or ""
            head = f"{t['title']}"
            if deliverable:
                head += f"（产出：{deliverable}）"
            lines.append(f"{head}：{t.get('brief', '')}")
        exercise = "\n".join(lines)

        self_check = [q["question"] for q in (c.get("self_check") or [])]

        out.append({
            "id": i,
            "course_id": cid,
            "title": c["title"],
            "goal": c.get("学习目的") or c.get("goal") or "",
            "knowledge": knowledge,
            "exercise": exercise,
            "self_check": self_check,
            "stage": c.get("stage", ""),
            "tasks": [{"id": t["id"], "type": t.get("type", "code"),
                       "title": t["title"], "brief": t.get("brief", ""),
                       "deliverable": t.get("deliverable", "")}
                      for t in (c.get("tasks") or [])],
        })
    return out


def build_progress(lessons, placement, system):
    """从学习位置推导导师的 progress.json。

    为什么必须由位置推导：导师的进度文件与学习位置是两套计数，实测出现过
    「导师说进入第 4 课，而进度文件还停在第 3 课」。让位置当唯一真源，
    导师只负责显示。
    """
    rep = placement_report(system, placement)
    by_course = {r["course_id"]: r for r in rep["rows"]}
    lessons_done, current = {}, 1
    for L in lessons:
        cid = L["course_id"]
        r = by_course.get(cid) or {}
        if r.get("done") or r.get("fast_pass"):
            mark = "已具备" if r.get("done") else f"快速过（挂账 {len(r.get('carried_over') or [])}）"
            lessons_done[str(L["id"])] = {"title": L["title"], "date": None,
                                          "status": mark, "course_id": cid}
        elif current == 1 and L["id"] > 1:
            current = L["id"]
    if not lessons_done:
        current = 1
    return {
        "current_lesson": current,
        "lessons_done": lessons_done,
        "log": [],
        "note": ("本文件由 study/system/export_tutor_lessons.py 从学习位置推导，请勿手改。"
                 "位置真源：study/system/placement-*.json"),
    }


def main():
    argv = sys.argv[1:]
    write = "--write" in argv
    sync_progress = "--sync-progress" in argv
    out_path = _arg(argv, "--out", DEFAULT_OUT)
    scope = (_arg(argv, "--scope") or "").split(",") if _arg(argv, "--scope") else None

    system = _active_system()

    lessons = build_lessons(system, scope)
    print(f"体系：{system['title']}")
    print(f"生成 {len(lessons)} 课（活跃体系：study/route.json + curriculum/*.json；"
          f"加 --west2 可导出西二原课表）\n")
    for L in lessons:
        print(f"  [{L['id']}] {L['title']}")
        print(f"      course_id : {L['course_id']}")
        print(f"      知识点    : {len(L['knowledge'])} 个")
        print(f"      作业      : {len(L['tasks'])} 项")
        print(f"      自检题    : {len(L['self_check'])} 题")

    payload = {
        "title": f"{system['title']} · 导师课程表",
        "note": (f"本文件由 study/system/export_tutor_lessons.py 从体系生成，请勿手改。"
                 f"体系：{system.get('source', {}).get('repo')}"
                 f"｜生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}"),
        "system_id": system.get("system_id"),
        "lessons": lessons,
    }

    if write:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        if os.path.isfile(out_path):
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(out_path, f"{out_path}.bak-{stamp}")
            print(f"\n已备份原课程表 → {os.path.basename(out_path)}.bak-{stamp}")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"已写入 {out_path}")

        if sync_progress:
            placement = _active_placement()
            if not placement:
                print("⚠️ 没有位置文件，跳过进度同步")
            else:
                prog = build_progress(lessons, placement, system)
                prog_path = os.path.join(os.path.dirname(out_path), "progress.json")
                if os.path.isfile(prog_path):
                    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                    shutil.copy2(prog_path, f"{prog_path}.bak-{stamp}")
                with open(prog_path, "w", encoding="utf-8") as f:
                    json.dump(prog, f, ensure_ascii=False, indent=2)
                print(f"已同步进度 → {prog_path}")
                print(f"  current_lesson = {prog['current_lesson']}（"
                      f"{lessons[prog['current_lesson'] - 1]['title'] if prog['current_lesson'] <= len(lessons) else '?'}）")
                for k, v in prog["lessons_done"].items():
                    print(f"  [{k}] {v['title']} —— {v['status']}")
    else:
        print("\n（预览模式，加 --write 生效）")
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
