# -*- coding: utf-8 -*-
"""system · 活跃体系适配器。

问题：学习工具（scaffold / tidy / interrogate / export）都是围绕一份「体系文件」
（`west2-ai-2026.json` 那种 `{dimensions, stages, knowledge, courses}`）写的，
但真正在用的课程表是 `study/route.json` + `study/curriculum/*.json`。
两套东西并存的结果是：切了骨架之后，工具还在照着西二 11 门课找笔记。

做法：把 route + 全部 curriculum **合成**一份体系字典，字段与体系文件一一对应，
于是 to_curriculum / scaffold / 门禁全都不用改，直接吃合成结果。

**刻意不做的事**：不去反写一个假的 `*-2026.json` 体系文件。合成是只读的推导，
源头仍然是 route + curriculum——否则又多一份要同步的真相。
"""
import json
import os

STUDY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_active(study_dir=None):
    """从 route.json + curriculum/*.json 合成体系字典。"""
    study_dir = study_dir or STUDY
    route_path = os.path.join(study_dir, "route.json")
    cur_dir = os.path.join(study_dir, "curriculum")
    route = _load(route_path)

    curricula = {}
    for name in sorted(os.listdir(cur_dir)):
        if not name.endswith(".json"):
            continue
        cur = _load(os.path.join(cur_dir, name))
        cid = cur.get("course_id")
        if cid:
            curricula[cid] = cur

    knowledge, courses = [], []
    for entry in route["courses"]:
        cid = entry["course_id"]
        cur = curricula.get(cid) or {}
        declares = cur.get("declares") or {}
        kps = declares.get("knowledge") or []
        for kp in kps:
            knowledge.append({
                "id": f"{cid}:{kp['id']}",
                "name": kp.get("name", kp["id"]),
                "dim": kp.get("dim", ""),
                "level": kp.get("level", "must"),
                "keywords": kp.get("keywords") or [],
                # 保留出处，便于回查这个知识点是从西二哪个点来的
                "source_knowledge": kp.get("source_knowledge"),
            })
        courses.append({
            "course_id": cid,
            "title": entry.get("title", cid),
            "stage": entry.get("stage", ""),
            "requires": list(entry.get("requires") or []),
            "knowledge": [f"{cid}:{kp['id']}" for kp in kps],
            # 课程级内容原样带过来，scaffold 的「考核要求」区要有东西可渲染
            "学习目的": cur.get("goal", ""),
            "学习内容": cur.get("declares", {}).get("system_position", ""),
            "学习要求": "",
            "tasks": _tasks_with_course_id(cid, cur.get("tasks") or []),
            "self_check": cur.get("self_check") or [],
            "est_days": cur.get("est_days"),
        })

    return {
        "system_id": "py-agent-9",
        "title": route.get("title", ""),
        # source 必须是对象：to_curriculum 读的是 system["source"]["repo"]
        "source": {"repo": "local:study/route.json",
                   "origin": route.get("source", "")},
        "route_id": route.get("route_id", ""),
        "dimensions": [],          # 九课体系不再按维度分组，维度信息留在知识点上
        "stages": [],
        "knowledge": knowledge,
        "courses": courses,
        "_derived_from": ["route.json", "curriculum/*.json"],
    }


def active_paths(study_dir=None, west2=False):
    """工具统一的数据入口：返回 (system, placement)。

    默认 = 活跃体系（route + curriculum）配 placement-py9；
    `west2=True` 回到西二原课表——它现在是**内容来源**，留这个开关是为了对照与迁移，
    而不是日常学习路径。

    所有面向使用者的工具都从这里取，不要各自硬编码文件路径：
    骨架换过一次，硬编码的结果就是「工具还在照西二 11 门课找笔记」
    （实测 tidy.py 报「没有课程 py-agent-04」、system.py 还在报 F2）。
    """
    from .split import load_placement, load_system
    study_dir = study_dir or STUDY
    if west2:
        return (load_system(os.path.join(study_dir, "system",
                                         "west2-ai-2026.json")),
                load_placement(os.path.join(study_dir, "system",
                                            "placement-west2.json")))
    return (load_active(study_dir),
            load_placement(os.path.join(study_dir, "system",
                                        "placement-py9.json")))


def _tasks_with_course_id(cid, tasks):
    """把课程里的任务规整成体系文件的形状。

    curriculum 用 `task_id`，体系文件用 `id`——下游工具（导出导师课程表、
    脚手架）按体系文件的字段读，不统一就会 KeyError: 'id'。
    两个键都留着：谁也不吃亏，改一处总比在每个消费者里判两次好。
    """
    out = []
    for t in tasks:
        item = dict(t)
        item.setdefault("course_id", cid)
        if "id" not in item:
            item["id"] = item.get("task_id")
        out.append(item)
    return out
