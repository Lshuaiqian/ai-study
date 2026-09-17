#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
"""验证 python-tutor 已切到由体系生成的课程表，且与学习位置一致。

检查：
  1. lessons.json 能被导师正常加载
  2. 每课都带 course_id（桥接靠它定位课程）
  3. 每课的知识点/作业/自检题非空
  4. progress.json 的 current_lesson 指向的正是学习位置里的「下一步」
"""
import io
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

AGENT = r"E:\Agents\python-tutor"
STUDY = r"E:\Docs\Code\Java\book\study"

# 顺序要紧：STUDY 下有 `study/tutor/` 包，会抢走 `import tutor`。
# 先插 STUDY 再插 AGENT，让 AGENT 排在 sys.path[0]。
sys.path.insert(0, STUDY)
sys.path.insert(0, AGENT)

import tutor as _t  # noqa: E402

if os.path.dirname(os.path.abspath(_t.__file__)) != AGENT:
    raise SystemExit(f"import tutor 解析到了错误的文件：{_t.__file__}（应为 {AGENT} 下的 tutor.py）")

checks = []


def check(name, fn):
    try:
        detail = fn()
        checks.append((True, name, detail))
    except Exception as e:  # noqa: BLE001
        checks.append((False, name, f"{type(e).__name__}: {e}"))


def tutor_loads():
    import tutor
    lessons = tutor.load_lessons()
    assert lessons, "课程表为空"
    return f"加载到 {len(lessons)} 课"


def every_lesson_has_course_id():
    import tutor
    missing = [l["id"] for l in tutor.load_lessons() if not l.get("course_id")]
    assert not missing, f"缺 course_id 的课：{missing}"
    return "、".join(l["course_id"] for l in tutor.load_lessons())


def every_lesson_is_usable():
    import tutor
    bad = []
    for l in tutor.load_lessons():
        if not l.get("knowledge"):
            bad.append(f"{l['id']} 缺知识点")
        if not (l.get("exercise") or "").strip():
            bad.append(f"{l['id']} 缺作业")
        if not l.get("self_check"):
            bad.append(f"{l['id']} 缺自检题")
    assert not bad, bad
    return "每课都有知识点 / 作业 / 自检题"


def progress_matches_placement():
    from system import load_placement, load_system, placement_report
    # 对齐**活跃体系**：导师课程表现在是从 route + curriculum 导出的，
    # 还拿西二课表来比会得出「进度指向 py-agent-03，位置建议 west2-f2」这种假矛盾
    from system import active_paths
    system, placement = active_paths(STUDY)
    rep = placement_report(system, placement)
    with open(os.path.join(AGENT, "progress.json"), encoding="utf-8") as f:
        prog = json.load(f)
    with open(os.path.join(AGENT, "lessons.json"), encoding="utf-8") as f:
        lessons = json.load(f)["lessons"]
    cur = prog["current_lesson"]
    want = rep["next_course"]["course_id"]
    got = next((l["course_id"] for l in lessons if l["id"] == cur), None)
    assert got == want, f"导师进度指向 {got}，学习位置建议 {want}"
    return f"第 {cur} 课 = {got} = 学习位置的下一步 ✅"


def carried_over_reflected():
    with open(os.path.join(AGENT, "progress.json"), encoding="utf-8") as f:
        prog = json.load(f)
    fast = {k: v for k, v in prog["lessons_done"].items()
            if "快速过" in (v.get("status") or "")}
    assert fast, "快速过的课没体现在进度里"
    return "；".join(f"[{k}] {v['title'][:22]} → {v['status']}" for k, v in fast.items())


check("导师能加载课程表", tutor_loads)
check("每课带 course_id（桥接靠它定位）", every_lesson_has_course_id)
check("每课都有知识点/作业/自检题", every_lesson_is_usable)
check("进度与学习位置一致", progress_matches_placement)
check("快速过的课已挂账", carried_over_reflected)

print("python-tutor 课程表一致性检查")
print("=" * 64)
ok_all = True
for ok, name, detail in checks:
    print(f"  {'✅' if ok else '❌'} {name}")
    print(f"      {detail}")
    ok_all = ok_all and ok
print("=" * 64)
print(f"结论：{'PASS' if ok_all else 'FAIL'}")
sys.exit(0 if ok_all else 1)
