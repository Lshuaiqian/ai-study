"""system · 知识体系 → 课程拆分器（自上而下流程的核心）。

思路反转
    旧流程（自下而上）：每课各自声明知识点 → 再拼成体系。
    新流程（自上而下）：**先建完整知识体系 → 再由本模块拆成课**。

    好处：体系是唯一真源，课程只是它的一种切法。想换切法（比如按周、
    按难度）不用改内容；也不会出现"某课漏讲了某个知识点却没人发现"。

派生关系
    system/west2-ai-2026.json   ← 唯一真源（人工维护）
        ├── route.json                      （课程级前置关系）
        └── curriculum/<course>.json        （每课的知识点声明 + 任务）

课程内的知识点会拿到 **课程本地 K-id**（K1、K2…），
并通过 `source_knowledge` 记住它来自体系里的哪个全局 id，
这样既与既有机制（atoms 用 `course:K` 键）兼容，又能回溯到体系。
"""
import json
import os

DEFAULT_GATE = {
    "min_mastery": 0.85,
    "min_each": 0.60,
    "require_transfer": False,
    "min_practice_lines": 0,
}

STAGE_LABEL = {
    "foundation": "Foundation（共通路线）",
    "application": "Application 路线",
    "research": "Scientific Research 路线",
    "routine": "方向日常训练",
}

# 课程短代号：用于花笺笔记的标题前缀（F2-网络爬虫与数据分析）。
# 放在这里而不是 scaffold.py —— 它是体系的数据，不是脚手架的实现细节；
# 而且早先放在 tools/ 下会导致 tools/system.py 把 study/system/ 包遮蔽掉。
CODE_LABEL = {
    # 活跃骨架：老 9 课（route.json 里的就是这 9 门）
    "py-agent-01": "L1", "py-agent-02": "L2", "py-agent-03": "L3",
    "py-agent-04": "L4", "py-agent-05": "L5", "py-agent-06": "L6",
    "py-agent-07": "L7", "py-agent-08": "L8", "py-agent-09": "L9",
    # 西二原课表：内容来源，保留代号以便回查与迁移
    "west2-f0": "F0", "west2-f1": "F1", "west2-f2": "F2",
    "west2-f3": "F3", "west2-f4": "F4",
    "west2-a0": "A0", "west2-a1": "A1", "west2-r1": "R1",
    "west2-be": "BE", "west2-fe": "FE", "west2-st": "ST",
}

# 代号必须能按字符串排序出正确课序（`L10` 会排在 `L2` 前面）。
# 九课是单位数，暂时安全；一旦超过 9 门，这里会报错提醒改成补零（L01..L09）。
LABEL_WIDTH = 1


def check_label_order(code_labels=None):
    """课序与代号字典序必须一致——花笺/文件列表都按字符串排序。"""
    labels = code_labels or {c: l for c, l in CODE_LABEL.items()
                             if c.startswith("py-agent-")}
    pairs = sorted(labels.items())
    codes = [l for _, l in pairs]
    if codes != sorted(codes):
        raise ValueError(f"代号字典序与课序不一致，列表会乱：{codes}")
    return codes


def code_of(course_id):
    return CODE_LABEL.get(course_id, course_id)


def load_system(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def knowledge_index(system):
    return {k["id"]: k for k in system.get("knowledge") or []}


def dimension_index(system):
    return {d["id"]: d for d in system.get("dimensions") or []}


def course_index(system):
    return {c["course_id"]: c for c in system.get("courses") or []}


# ---------------------------------------------------------------- 校验

def validate_system(system):
    """体系自身的完整性。返回问题列表（空表示健康）。

    这一步很关键：体系是人工维护的，一旦有悬空引用，
    拆分出来的课就会带着错误的依赖关系。
    """
    issues = []
    dims = dimension_index(system)
    know = knowledge_index(system)
    courses = course_index(system)
    stages = {s["id"]: s for s in system.get("stages") or []}

    # 维度 / 知识点
    seen = set()
    for k in system.get("knowledge") or []:
        kid = k.get("id")
        if not kid:
            issues.append({"kind": "knowledge_missing_id", "entry": k.get("name")})
            continue
        if kid in seen:
            issues.append({"kind": "duplicate_knowledge", "id": kid})
        seen.add(kid)
        if k.get("dim") not in dims:
            issues.append({"kind": "unknown_dimension", "id": kid, "dim": k.get("dim")})
        if k.get("level") not in ("must", "should"):
            issues.append({"kind": "bad_level", "id": kid, "level": k.get("level")})
        if not k.get("keywords"):
            issues.append({"kind": "knowledge_without_keywords", "id": kid,
                           "note": "笔记覆盖度检查需要 keywords"})

    # 课程
    used_knowledge = set()
    for c in system.get("courses") or []:
        cid = c.get("course_id")
        if not cid:
            issues.append({"kind": "course_missing_id", "title": c.get("title")})
            continue
        if c.get("stage") not in stages:
            issues.append({"kind": "unknown_stage", "course": cid, "stage": c.get("stage")})
        for ref in c.get("requires") or []:
            if ref not in courses:
                issues.append({"kind": "unknown_course_requires", "course": cid, "target": ref})
        for kid in c.get("knowledge") or []:
            if kid not in know:
                issues.append({"kind": "unknown_knowledge_ref", "course": cid, "knowledge": kid})
            else:
                used_knowledge.add(kid)
        if not c.get("tasks"):
            issues.append({"kind": "course_without_tasks", "course": cid})

    # 悬空知识点：体系里有，但没有任何课讲 —— 自上而下流程最容易漏的正是这个
    for kid in know:
        if kid not in used_knowledge:
            issues.append({"kind": "knowledge_not_taught", "id": kid,
                           "name": know[kid]["name"],
                           "note": "体系里声明了，但没有任何课程引用它"})

    # 环
    cycles = find_course_cycles(system)
    for cyc in cycles:
        issues.append({"kind": "course_cycle", "cycle": cyc})

    return issues


def find_course_cycles(system):
    courses = course_index(system)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {cid: WHITE for cid in courses}
    stack, cycles = [], []

    def dfs(node):
        color[node] = GRAY
        stack.append(node)
        for pre in courses.get(node, {}).get("requires") or []:
            if pre not in courses:
                continue
            if color.get(pre) == GRAY:
                cycles.append(stack[stack.index(pre):] + [pre])
            elif color.get(pre) == WHITE:
                dfs(pre)
        stack.pop()
        color[node] = BLACK

    for cid in sorted(courses):
        if color[cid] == WHITE:
            dfs(cid)
    return cycles


def topo_courses(system):
    courses = course_index(system)
    order, seen = [], set()

    def visit(cid):
        if cid in seen or cid not in courses:
            return
        seen.add(cid)
        for pre in courses[cid].get("requires") or []:
            visit(pre)
        order.append(cid)

    for cid in sorted(courses):
        visit(cid)
    return order


def derived_unlocks(system):
    """由 requires 反推 unlocks（不手写，避免不一致）。"""
    courses = course_index(system)
    out = {cid: [] for cid in courses}
    for cid, c in courses.items():
        for pre in c.get("requires") or []:
            if pre in out:
                out[pre].append(cid)
    for cid in out:
        out[cid].sort()
    return out


# ---------------------------------------------------------------- 拆分

def to_curriculum(system, course, placement=None):
    """把体系里的一门课拆成既有机制能吃的 curriculum 结构。

    placement 不为 None 时，会额外标出每个知识点"你是否已具备"
    （见 apply_placement），但**不改课程内容本身**。
    """
    know = knowledge_index(system)
    dims = dimension_index(system)
    courses = course_index(system)
    unlocks = derived_unlocks(system)
    cid = course["course_id"]

    # 课程本地 K-id：按体系里的声明顺序编号
    knowledge = []
    for i, gid in enumerate(course.get("knowledge") or [], start=1):
        k = know[gid]
        knowledge.append({
            "id": f"K{i}",
            "name": k["name"],
            "level": k.get("level", "must"),
            "keywords": k.get("keywords") or [],
            "dimension": k.get("dim"),
            "dimension_name": dims.get(k.get("dim"), {}).get("name", ""),
            "source_knowledge": gid,
        })

    prereq = []
    for pre in course.get("requires") or []:
        if pre in courses:
            prereq.append({"course_id": pre, "name": courses[pre]["title"]})

    stage = course.get("stage", "")
    stage_name = STAGE_LABEL.get(stage, stage)
    prereq_txt = ("本课是路线起点" if not prereq
                  else "本课直接依赖：" + "、".join(p["name"] for p in prereq))

    cur = {
        "course_id": cid,
        "route": system.get("title", ""),
        "title": course["title"],
        "goal": f"{stage_name}｜{prereq_txt}",
        "stage": stage,
        "source": (system.get("source") or {}).get("repo", ""),
        "status": "declares-ready",
        "learning_goal": course.get("学习目的", ""),
        "learning_content": course.get("学习内容", ""),
        "learning_requirement": course.get("学习要求", ""),
        "declares": {
            "system_position": f"{stage_name}｜维度：" + "、".join(
                sorted({k["dimension_name"] for k in knowledge if k["dimension_name"]})),
            "prerequisites": prereq,
            "unlocks": [{"course_id": u, "name": courses[u]["title"]}
                        for u in unlocks.get(cid, [])],
            "knowledge": knowledge,
        },
        "theory": [],
        # 自检题（问题 + 判定点）来自体系：这是 quiz 维度能被结构化判分的唯一依据
        "self_check": [
            {"id": q.get("id", f"Q{i}"), "question": q.get("question", ""),
             "points": q.get("points") or []}
            for i, q in enumerate(course.get("self_check") or [], start=1)
        ],
        "tasks": [
            {
                "task_id": t.get("id", f"{cid}-{i}"),
                "type": t.get("type", "code"),
                "title": t.get("title", ""),
                "brief": t.get("brief", ""),
                "deliverable": t.get("deliverable", ""),
                "acceptance": t.get("acceptance") or _default_acceptance(t),
                "atoms": [],
                "est_minutes": t.get("est_minutes", 0),
            }
            for i, t in enumerate(course.get("tasks") or [], start=1)
        ],
        "materials": {
            "note": "由体系拆分生成；知识点来自 system/*.json，原子库待用真实资料抽取填充。",
            "atoms": [],
        },
        "gate": dict(DEFAULT_GATE, **({"require_transfer": True}
                                      if any(t.get("type") == "transfer"
                                             for t in course.get("tasks") or [])
                                      else {})),
    }
    return apply_placement(cur, placement)


def _default_acceptance(task):
    """体系里没写验收标准时，按任务类型给一个可执行的默认值。"""
    t = task.get("type", "code")
    if t == "note":
        return ["覆盖本课全部必会知识点", "用你自己的话写", "无事实错误"]
    if t == "practice":
        return ["有可运行的产出", "写清卡住的地方与解法"]
    return ["能跑通并产出非空结果", "代码可读、有必要的注释",
            "写清你踩到的坑与怎么解决的"]


def split_all(system, placement=None):
    return {c["course_id"]: to_curriculum(system, c, placement)
            for c in system.get("courses") or []}


def to_route(system):
    return {
        "route_id": system.get("system_id", "route"),
        "title": system.get("title", ""),
        "source": (system.get("source") or {}).get("repo", ""),
        "entry": {
            "name": "前置：C/C++ 基础",
            "note": "本路线从 Python 环境搭建开始；有编程基础可直接跳过语法细节",
        },
        "note": "本文件由 system/split.py 从体系文件派生，请勿手改。",
        "courses": [
            {"course_id": c["course_id"], "title": c["title"],
             "requires": c.get("requires") or []}
            for c in system.get("courses") or []
        ],
    }


# ---------------------------------------------------------------- 落盘

def _fname(course_id):
    return course_id.replace("-", "_") + ".json"


# ---------------------------------------------------------------- 学习位置

STATUS_LABEL = {
    "met": "已具备",
    "partial": "部分具备",
    "unknown": "无证据",
    "not_started": "未开始",
}
# 计入"已具备"的状态：unknown 不算（没证据不等于会）
COUNTED_MET = ("met",)


def load_placement(path):
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def apply_placement(curriculum, placement):
    """把学习位置应用到课程：标出每个知识点是已具备还是还需补。

    只在**副本**上加字段，不改体系文件——位置是"关于学习者的判断"，
    体系是"课程内容"，两者必须分开，否则换个学习者就要改体系。
    """
    if not placement:
        return curriculum
    status = placement.get("knowledge_status") or {}
    weak = {w["knowledge"] for w in placement.get("weak_points") or []}

    out = json.loads(json.dumps(curriculum))       # 深拷贝，避免污染调用方
    met, partial, unknown, not_started = [], [], [], []
    for k in out["declares"]["knowledge"]:
        gid = k.get("source_knowledge")
        rec = status.get(gid) or {}
        st = rec.get("status", "unknown")
        k["prior_status"] = st
        k["prior_label"] = STATUS_LABEL.get(st, st)
        k["prior_evidence"] = rec.get("evidence", "")
        k["is_weak_point"] = gid in weak
        {"met": met, "partial": partial, "unknown": unknown,
         "not_started": not_started}.get(st, unknown).append(k["id"])

    total = len(out["declares"]["knowledge"])
    met_n = len(met)
    remaining = [k for k in out["declares"]["knowledge"]
                 if k["prior_status"] not in COUNTED_MET]
    out["placement"] = {
        "met": met, "partial": partial, "unknown": unknown,
        "not_started": not_started,
        "met_count": met_n, "total": total,
        "met_ratio": round(met_n / total, 4) if total else 0.0,
        "likely_fast_pass": bool(total) and met_n == total,
        "remaining_ids": [k["id"] for k in remaining],
        "focus": [{"id": k["id"], "name": k["name"], "status": k["prior_status"],
                   "label": k["prior_label"], "evidence": k["prior_evidence"],
                   "weak": k["is_weak_point"]}
                  for k in remaining],
        "weak_points": [w for w in (placement.get("weak_points") or [])
                        if any(k.get("source_knowledge") == w["knowledge"]
                               for k in out["declares"]["knowledge"])],
    }

    # 学习者的显式决策（例如"F0/F1 快速过，直接进 F2"）——带疑点前进必须挂账
    decisions = {d["course_id"]: d for d in (placement.get("decisions") or [])}
    dec = decisions.get(out["course_id"])
    if dec:
        # 坑：carried_over 在决策文件里写的是**体系级** id（如 env.ide），
        # 而 met/partial/unknown 用的是**本课本地** id（如 K2）。同一个 placement
        # 字典里混了两套 id 空间，不翻译就永远匹配不上——挂账点会静默失去保护，
        # 被"笔记里没写到"误判成未通过（实测 F0 的 4 个挂账点全中）。
        g2l = {k.get("source_knowledge"): k["id"]
               for k in out["declares"]["knowledge"]}
        src_carried = [g for g in (dec.get("carried_over") or []) if g in g2l]
        carried = [g2l[g] for g in src_carried]
        out["placement"]["decision"] = dec.get("decision")
        out["placement"]["fast_pass"] = dec.get("decision") == "fast_pass"
        out["placement"]["carried_over"] = carried
        # 保留体系级 id 便于回查决策文件
        out["placement"]["carried_over_source_ids"] = src_carried
        out["placement"]["decision_reason"] = dec.get("reason", "")
        out["placement"]["recheck_at"] = dec.get("recheck_at", "")
        out["placement"]["decision_warning"] = dec.get("warning", "")
    return out


def protection_map(curriculum):
    """有证据的知识点 → 证据种类：{本地 K-id: "met" | "carried_over"}。

    整理或质询发现「笔记里没写到」这些点时**不许摘牌**：
    placement 已经带着证据判过它们，笔记没写 ≠ 没掌握。

    两种证据要分开，因为它们不是一回事：
      - `met`          已具备（有实证）
      - `carried_over` 带着疑点前进、下一课开头必须复查（挂账）
    """
    p = curriculum.get("placement") or {}
    out = {kid: "met" for kid in (p.get("met") or [])}
    for kid in (p.get("carried_over") or []):
        out.setdefault(kid, "carried_over")
    return out


def protected_ids(curriculum):
    """有「已具备 / 已挂账」证据的知识点（本地 K-id）集合。"""
    return set(protection_map(curriculum))


def placement_report(system, placement):
    """给学习者看的「我的位置」：走过多少、卡在哪、下一步。"""
    if not placement:
        return {"has_placement": False}
    status = placement.get("knowledge_status") or {}
    courses = course_index(system)
    order = topo_courses(system)
    decisions = {d["course_id"]: d for d in (placement.get("decisions") or [])}

    rows = []
    carried_all = []
    for cid in order:
        c = courses[cid]
        known = [k for k in c["knowledge"] if (status.get(k) or {}).get("status") == "met"]
        total = len(c["knowledge"])
        dec = decisions.get(cid) or {}
        fast = dec.get("decision") == "fast_pass"
        # 挂账只保留本课真实存在的知识点
        carried = [g for g in (dec.get("carried_over") or []) if g in set(c["knowledge"])]
        for g in carried:
            carried_all.append({"knowledge": g, "course_id": cid,
                                "course": CODE_LABEL.get(cid, cid),
                                "reason": dec.get("reason", ""),
                                "recheck_at": dec.get("recheck_at", "")})
        rows.append({
            "course_id": cid, "title": c["title"], "stage": c["stage"],
            "met": len(known), "total": total,
            "ratio": round(len(known) / total, 4) if total else 0.0,
            "done": total > 0 and len(known) == total,
            "fast_pass": fast,
            "carried_over": carried,
            "decision_reason": dec.get("reason", ""),
        })

    # 下一门建议：拓扑序里第一门**既没全具备、也没被决定快速过**的
    nxt = next((r for r in rows if not r["done"] and not r["fast_pass"]), None)
    focus = []
    if nxt:
        c = courses[nxt["course_id"]]
        for gid in c["knowledge"]:
            rec = status.get(gid) or {}
            if rec.get("status") != "met":
                focus.append({"knowledge": gid, "status": rec.get("status", "unknown"),
                              "label": STATUS_LABEL.get(rec.get("status", "unknown")),
                              "evidence": rec.get("evidence", "")})
    return {
        "has_placement": True,
        "placement_id": placement.get("placement_id"),
        "assessed_at": placement.get("assessed_at"),
        "rows": rows,
        "done_courses": [r["course_id"] for r in rows if r["done"]],
        "fast_pass_courses": [r["course_id"] for r in rows if r["fast_pass"]],
        "carried_over": carried_all,
        "next_course": nxt,
        "focus": focus,
        "weak_points": placement.get("weak_points") or [],
        "evidence": placement.get("evidence") or [],
        "notes": placement.get("notes") or [],
    }


def write_derived(system, study_dir, dry_run=False, placement=None):
    """把派生结果写进 study/（route.json + curriculum/*.json）。

    返回写出的文件列表；dry_run 时只返回将要写入的路径。
    placement 不为 None 时，每门课会带上"你已具备/还需补"的标注。
    """
    written = []
    os.makedirs(study_dir, exist_ok=True)
    route_path = os.path.join(study_dir, "route.json")
    written.append(route_path)
    if not dry_run:
        with open(route_path, "w", encoding="utf-8") as f:
            json.dump(to_route(system), f, ensure_ascii=False, indent=2)

    cdir = os.path.join(study_dir, "curriculum")
    if not dry_run:
        os.makedirs(cdir, exist_ok=True)
    for cid, cur in split_all(system, placement).items():
        path = os.path.join(cdir, _fname(cid))
        written.append(path)
        if not dry_run:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cur, f, ensure_ascii=False, indent=2)
    return written


def summary(system):
    courses = system.get("courses") or []
    know = system.get("knowledge") or []
    by_stage = {}
    for c in courses:
        by_stage.setdefault(c.get("stage", "?"), []).append(c["course_id"])
    must = sum(1 for k in know if k.get("level") == "must")
    return {
        "courses": len(courses),
        "knowledge": len(know),
        "must": must,
        "should": len(know) - must,
        "dimensions": len(system.get("dimensions") or []),
        "by_stage": {k: len(v) for k, v in by_stage.items()},
        "topo": topo_courses(system),
    }
