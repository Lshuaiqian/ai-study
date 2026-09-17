#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""知识体系 CLI（自上而下流程）。

用法：
    python study\\tools\\system.py check                 # 体系完整性校验
    python study\\tools\\system.py summary               # 体系概览
    python study\\tools\\system.py split --dry-run        # 看会派生哪些文件
    python study\\tools\\system.py split                 # 写 route.json + curriculum/*.json
    python study\\tools\\system.py show west2-f2         # 看某门课的拆分结果
"""
import io
import os
import shutil
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from system import (CODE_LABEL, course_index, load_placement,      # noqa: E402
                    load_system, placement_report, split_all, summary,
                    to_curriculum, topo_courses, validate_system,
                    write_derived)

SYSTEM_PATH = None      # 运行时由 active_paths 决定（见 system/active.py）
PLACEMENT_PATH = None      # 运行时由 active_paths 决定

ISSUE_LABEL = {
    "duplicate_knowledge": "知识点 id 重复",
    "unknown_dimension": "引用了不存在的维度",
    "bad_level": "level 只能是 must / should",
    "knowledge_without_keywords": "知识点缺 keywords（覆盖度检查需要）",
    "unknown_stage": "引用了不存在的阶段",
    "unknown_course_requires": "前置课程不存在",
    "unknown_knowledge_ref": "课程引用了不存在的知识点",
    "course_without_tasks": "课程没有任务",
    "knowledge_not_taught": "⚠️ 体系里声明了但没有任何课讲",
    "course_cycle": "课程依赖成环",
}


def cmd_check(system):
    issues = validate_system(system)
    if not issues:
        print("体系校验：✅ 无问题")
        return 0
    print(f"体系校验：⚠️ {len(issues)} 个问题")
    for it in issues:
        kind = it.get("kind")
        label = ISSUE_LABEL.get(kind, kind)
        detail = {k: v for k, v in it.items() if k not in ("kind", "note")}
        print(f"  - {label}：{detail}")
        if it.get("note"):
            print(f"      {it['note']}")
    return 1


def cmd_summary(system):
    s = summary(system)
    print(f"体系：{system['title']}")
    print(f"  来源：{(system.get('source') or {}).get('repo')}"
          f"（{(system.get('source') or {}).get('license')}）")
    print(f"  维度 {s['dimensions']}｜课程 {s['courses']}｜"
          f"知识点 {s['knowledge']}（必会 {s['must']} / 了解 {s['should']}）")
    print(f"  阶段分布：{s['by_stage']}")
    print("\n  拓扑序（学习顺序）：")
    courses = {c["course_id"]: c for c in system["courses"]}
    for i, cid in enumerate(s["topo"], 1):
        print(f"    {i:>2}. [{courses[cid]['stage']:11s}] {courses[cid]['title']}")
    return 0


def cmd_placement(system, placement):
    """「我的位置」：走过多少、卡在哪、下一步。"""
    rep = placement_report(system, placement)
    if not rep["has_placement"]:
        print(f"还没有学习位置文件：{os.path.relpath(PLACEMENT_PATH, BASE)}")
        return 1

    print(f"📍 我的位置 · {rep['placement_id']}（评估于 {rep['assessed_at']}）")
    print("=" * 62)
    print()
    print("| 代号 | 课程 | 已具备 / 知识点 | 状态 |")
    print("| --- | --- | --- | --- |")
    for r in rep["rows"]:
        code = CODE_LABEL.get(r["course_id"], r["course_id"])
        if r["done"]:
            mark = "✅ 已具备"
        elif r["fast_pass"]:
            mark = f"⏩ 快速过（挂账 {len(r['carried_over'])}）"
        elif r["met"]:
            mark = "🟡 部分"
        else:
            mark = "⬜ 未开始"
        print(f"| {code} | {r['title']} | {r['met']}/{r['total']} | {mark} |")

    if rep["carried_over"]:
        print()
        print(f"📌 挂账 {len(rep['carried_over'])} 个知识点（你选择带疑点前进，这些没被忘掉）：")
        by_course = {}
        for c in rep["carried_over"]:
            by_course.setdefault(c["course"], []).append(c["knowledge"])
        for course, ks in by_course.items():
            print(f"   {course}：{'、'.join(ks)}")
        recheck = {c["recheck_at"] for c in rep["carried_over"] if c.get("recheck_at")}
        if recheck:
            print(f"   复查时机：{'；'.join(sorted(recheck))}")

    print()
    nxt = rep["next_course"]
    if nxt:
        code = CODE_LABEL.get(nxt["course_id"], nxt["course_id"])
        print(f"▶️ 下一步：{code} {nxt['title']}"
              f"（已具备 {nxt['met']}/{nxt['total']}）")
        if rep["focus"]:
            print("\n   本课还需补的知识点：")
            for f in rep["focus"]:
                mark = {"not_started": "⬜", "unknown": "❓", "partial": "🟡"}.get(f["status"], "•")
                print(f"     {mark} [{f['label']}] `{f['knowledge']}`")
                if f.get("evidence"):
                    print(f"          证据：{f['evidence']}")
    else:
        print("▶️ 所有课程的知识点都标记为已具备 —— 该去答辩了。")

    if rep["weak_points"]:
        print("\n⚠️ 反复出错的点（来自对话历史，不是自评）：")
        for w in rep["weak_points"]:
            print(f"   - `{w['knowledge']}`：{w['issue']}")
            print(f"     处理：{w['action']}")

    if rep["evidence"]:
        print("\n📎 判断依据（每条状态都带证据，没有证据的一律标 unknown）：")
        for e in rep["evidence"]:
            print(f"   - {e['source']}\n       {e['says']}")

    if rep["notes"]:
        print("\n📌 顺带发现的问题：")
        for n in rep["notes"]:
            print(f"   - {n}")
    return 0


def cmd_next(system, placement):
    """只输出「下一步该做什么」——给每天开工时用。"""
    rep = placement_report(system, placement)
    if not rep["has_placement"]:
        print("还没有学习位置文件")
        return 1
    nxt = rep["next_course"]
    if not nxt:
        print("所有课程都已具备 —— 去准备答辩")
        return 0
    cid = nxt["course_id"]
    code = CODE_LABEL.get(cid, cid)
    print(f"▶️ {code} · {nxt['title']}")
    print(f"   已具备 {nxt['met']}/{nxt['total']} 个知识点")
    for f in rep["focus"]:
        mark = {"not_started": "⬜ 未开始", "unknown": "❓ 无证据",
                "partial": "🟡 部分具备"}.get(f["status"], f["status"])
        print(f"   {mark}  `{f['knowledge']}`")

    # 薄弱点要分「本课相关」和「其它课的」——否则下一步是 F0 却让你去修 F2 的爬虫解析
    own = {k for k in course_index(system)[cid]["knowledge"]}
    here = [w for w in rep["weak_points"] if w["knowledge"] in own]
    elsewhere = [w for w in rep["weak_points"] if w["knowledge"] not in own]

    if here:
        print("\n   本课要先清掉这些反复错的点：")
        for w in here:
            print(f"   - `{w['knowledge']}`：{w['action']}")
    if elsewhere:
        print("\n   ⏳ 其它课的遗留（不用现在处理，到那门课时再说）：")
        for w in elsewhere:
            print(f"   - `{w['knowledge']}`（{_course_of(system, w['knowledge'])}）：{w['action']}")
    return 0


def _course_of(system, knowledge_id):
    for c in system["courses"]:
        if knowledge_id in c["knowledge"]:
            return CODE_LABEL.get(c["course_id"], c["course_id"])
    return "?"


def cmd_split(system, argv):
    """派生 route.json + curriculum/*.json。

    默认写到 system/derived/（**非破坏性**），不会动现有的 route.json 与
    curriculum/py_agent_0*.json。确认要切换成 west2 体系时加 --activate：
    会先把旧的 route.json 与 curriculum/ 归档到 study/archive/ 再覆盖。
    """
    dry = "--dry-run" in argv
    activate = "--activate" in argv
    s = summary(system)

    if activate:
        out_dir = BASE
        archive = os.path.join(BASE, "archive", "route-before-west2")
        os.makedirs(archive, exist_ok=True)
        moved = []
        for rel in ("route.json",):
            src = os.path.join(BASE, rel)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(archive, rel))
                moved.append(rel)
        cdir = os.path.join(BASE, "curriculum")
        if os.path.isdir(cdir):
            dst = os.path.join(archive, "curriculum")
            os.makedirs(dst, exist_ok=True)
            for name in os.listdir(cdir):
                if name.endswith(".json"):
                    shutil.copy2(os.path.join(cdir, name), os.path.join(dst, name))
                    moved.append(f"curriculum/{name}")
        print(f"激活模式：已把 {len(moved)} 个文件归档到 "
              f"{os.path.relpath(archive, BASE)}")
    else:
        out_dir = os.path.join(BASE, "system", "derived")

    print(f"将派生 route.json + {s['courses']} 个课程文件 → "
          f"{os.path.relpath(out_dir, BASE)}")
    placement = _active_placement()
    if placement:
        rep = placement_report(system, placement)
        nxt = rep.get("next_course")
        if nxt:
            print(f"（已应用学习位置：下一步 {CODE_LABEL.get(nxt['course_id'], nxt['course_id'])}"
                  f" · {nxt['title']}）")
    written = write_derived(system, out_dir, dry_run=dry, placement=placement)
    for p in written:
        print(f"  {'(dry) ' if dry else ''}{os.path.relpath(p, out_dir)}")
    if not dry:
        print("\n派生完成。" + ("" if activate else
              "\n（这是非破坏性输出；要让 study 用上新体系，加 --activate）"))
    return 0


def cmd_show(system, course_id):
    courses = {c["course_id"]: c for c in system["courses"]}
    if course_id not in courses:
        print(f"没有课程 {course_id}；可用：{', '.join(sorted(courses))}")
        return 2
    cur = to_curriculum(system, courses[course_id])
    print(f"{cur['title']}   [{cur['course_id']}]")
    print(f"  阶段：{cur['stage']}｜{cur['goal']}")
    print(f"  体系位置：{cur['declares']['system_position']}")
    if cur["declares"]["prerequisites"]:
        print("  前置：" + "、".join(p["name"] for p in cur["declares"]["prerequisites"]))
    if cur["declares"]["unlocks"]:
        print("  解锁：" + "、".join(u["name"] for u in cur["declares"]["unlocks"]))
    print(f"\n  知识点（{len(cur['declares']['knowledge'])}）：")
    for k in cur["declares"]["knowledge"]:
        lvl = "必会" if k["level"] == "must" else "了解"
        print(f"    {k['id']} [{lvl}] {k['name']}")
        print(f"         维度 {k['dimension']} {k['dimension_name']}"
              f"｜体系 id {k['source_knowledge']}")
    print(f"\n  任务（{len(cur['tasks'])}）：")
    for t in cur["tasks"]:
        print(f"    [{t['type']:8s}] {t['task_id']:12s} {t['title']}")
    return 0


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    system = _active_system()
    cmd = argv[0]
    if cmd == "check":
        return cmd_check(system)
    if cmd == "summary":
        return cmd_summary(system)
    if cmd == "split":
        return cmd_split(system, argv)
    if cmd == "show":
        if len(argv) < 2:
            print("用法：show <course_id>")
            return 2
        return cmd_show(system, argv[1])
    if cmd == "placement":
        return cmd_placement(system, _active_placement())
    if cmd == "next":
        return cmd_next(system, _active_placement())
    print(f"未知子命令：{cmd}\n")
    print(__doc__)
    return 2



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
