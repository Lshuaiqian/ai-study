"""graph · 知识点 DAG 的构建与校验（纯逻辑，无网络依赖）。

两层节点：
  - course     课程（来自 route.json）
  - knowledge  课程知识点（来自各 curriculum 的 declares.knowledge，全局 id 形如 py-agent-03:K3）

四类边：
  - requires   硬前置（课程级 + 知识点级）—— 门禁与回炉的依据
  - part_of    知识点 → 所属课程（结构边）
  - contrast   软边：同一问题的不同解法 / 语言对照（默认不渲染）
  - applies_to 软边：这个知识点在哪里会被用到（指向课程）

构建时会做一致性校验，把"人写错的地方"报出来而不是默默忽略——
route.json 与各 curriculum 的 declares 是两处独立手写的，最容易不一致。
"""
import json
import os

NODE_COURSE = "course"
NODE_KNOWLEDGE = "knowledge"

E_REQUIRES = "requires"
E_PART_OF = "part_of"
E_CONTRAST = "contrast"
E_APPLIES = "applies_to"

SOFT_EDGES = (E_CONTRAST, E_APPLIES)


def kp_id(course_id, k_id):
    """知识点的全局 id。掌握度状态也用这个 key，保证 DAG 与门禁对得上。"""
    return f"{course_id}:{k_id}"


def load_route(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_curriculums(curriculum_dir):
    out = {}
    for name in sorted(os.listdir(curriculum_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(curriculum_dir, name), "r", encoding="utf-8") as f:
            data = json.load(f)
        cid = data.get("course_id")
        if cid:
            out[cid] = data
    return out


def build(route, curriculums):
    """构建图。返回 {nodes, edges, issues, route}。"""
    nodes, edges, issues = {}, [], []
    courses = route.get("courses") or []
    course_ids = {c["course_id"] for c in courses}

    # ---- 课程节点 ----
    for c in courses:
        cid = c["course_id"]
        nodes[cid] = {
            "id": cid, "type": NODE_COURSE, "title": c.get("title", cid),
            "requires": list(c.get("requires") or []),
        }

    # ---- 课程级硬前置边 ----
    for c in courses:
        cid = c["course_id"]
        for pre in nodes[cid]["requires"]:
            if pre not in course_ids:
                issues.append({"kind": "unknown_course_requires",
                               "course": cid, "target": pre})
                continue
            edges.append({"src": pre, "dst": cid, "type": E_REQUIRES,
                          "why": "课程级前置"})

    # ---- 知识点节点 ----
    for cid, cur in curriculums.items():
        if cid not in course_ids:
            issues.append({"kind": "course_not_in_route", "course": cid})
        declares = cur.get("declares") or {}
        seen = set()
        for kp in declares.get("knowledge") or []:
            nid = kp_id(cid, kp["id"])
            if nid in nodes:
                issues.append({"kind": "duplicate_node", "id": nid})
            if kp["id"] in seen:
                issues.append({"kind": "duplicate_kp_in_course", "id": nid})
            seen.add(kp["id"])
            nodes[nid] = {
                "id": nid, "type": NODE_KNOWLEDGE, "course": cid, "kp": kp["id"],
                "title": kp.get("name", kp["id"]), "level": kp.get("level", "must"),
                "keywords": kp.get("keywords") or [],
                "requires": kp.get("requires") or [],
                "contrast": kp.get("contrast") or [],
                "applies_to": kp.get("applies_to") or [],
            }
            edges.append({"src": cid, "dst": nid, "type": E_PART_OF, "why": ""})

    # ---- 空壳课程：route 声明了，却没有 declares ----
    # 不加这条检查，「9 门课里 6 门其实没有内容」是**完全静默**的：
    # 建图不报错、门禁不报错，学习者一路学下去到第 4 课才撞墙。
    for c in courses:
        cid = c["course_id"]
        cur = curriculums.get(cid)
        if not cur or not ((cur.get("declares") or {}).get("knowledge")):
            issues.append({"kind": "missing_curriculum", "course": cid,
                           "title": c.get("title", cid)})

    # ---- 知识点级边 ----
    all_kp_ids = {nid for nid, n in nodes.items() if n["type"] == NODE_KNOWLEDGE}
    for nid, node in list(nodes.items()):
        if node["type"] != NODE_KNOWLEDGE:
            continue
        for ref in node["requires"]:
            # requires 有两种写法：
            #   "K1"  → 同课知识点的简写（最常见）
            #   dict  → 跨课显式引用 {course_id, knowledge_id, why}
            if isinstance(ref, str):
                tgt = kp_id(node["course"], ref)
                why = "同课前置"
                if tgt not in all_kp_ids:
                    issues.append({"kind": "unknown_knowledge_requires",
                                   "src": nid, "target": tgt,
                                   "why": "同课简写但该知识点不存在"})
                    continue
            else:
                tgt = kp_id(ref["course_id"], ref["knowledge_id"])
                why = ref.get("why", "")
                if tgt not in nodes:
                    issues.append({"kind": "unknown_knowledge_requires",
                                   "src": nid, "target": tgt, "why": why})
                    continue
            edges.append({"src": tgt, "dst": nid, "type": E_REQUIRES, "why": why})
        for ref in node["contrast"]:
            # contrast 有两种写法：
            #   dict → 指向本图内的另一个知识点（真正的对比边）
            #   str  → 指向图外的对照概念（如 "C++ RAII"），不是节点，只作标注
            if isinstance(ref, str):
                node.setdefault("contrast_external", []).append(ref)
                continue
            tgt = kp_id(ref["course_id"], ref["knowledge_id"])
            if tgt not in nodes:
                issues.append({"kind": "unknown_contrast", "src": nid, "target": tgt})
                continue
            edges.append({"src": nid, "dst": tgt, "type": E_CONTRAST,
                          "why": ref.get("why", "")})
        for ref in node["applies_to"]:
            cid = ref["course_id"]
            if cid not in course_ids:
                issues.append({"kind": "unknown_applies_to", "src": nid, "target": cid})
                continue
            edges.append({"src": nid, "dst": cid, "type": E_APPLIES,
                          "why": ref.get("why", "")})

    # ---- 与人写的 declares 对一致性 ----
    for cid, cur in curriculums.items():
        declares = cur.get("declares") or {}
        route_pre = set(nodes.get(cid, {}).get("requires") or [])
        declared_pre = {p["course_id"] for p in (declares.get("prerequisites") or [])}
        if declared_pre != route_pre:
            issues.append({"kind": "prereq_mismatch", "course": cid,
                           "route": sorted(route_pre), "declares": sorted(declared_pre)})

        derived_unlocks = {c["course_id"] for c in courses
                           if cid in (c.get("requires") or [])}
        declared_unlocks = {u["course_id"] for u in (declares.get("unlocks") or [])}
        if declared_unlocks and declared_unlocks != derived_unlocks:
            issues.append({"kind": "unlocks_mismatch", "course": cid,
                           "derived": sorted(derived_unlocks),
                           "declares": sorted(declared_unlocks)})

    graph = {"nodes": nodes, "edges": edges, "issues": issues, "route": route}
    cycles = find_cycles(graph)
    if cycles:
        issues.append({"kind": "cycle", "cycles": cycles})
    return graph


# ---------------- 查询与校验 ----------------

def course_nodes(graph):
    return [n for n in graph["nodes"].values() if n["type"] == NODE_COURSE]


def knowledge_nodes(graph, course_id=None):
    out = [n for n in graph["nodes"].values() if n["type"] == NODE_KNOWLEDGE]
    if course_id:
        out = [n for n in out if n["course"] == course_id]
    return sorted(out, key=lambda n: (n["course"], n["kp"]))


def out_edges(graph, src, edge_type=None, include_soft=False):
    for e in graph["edges"]:
        if e["src"] != src:
            continue
        if edge_type and e["type"] != edge_type:
            continue
        if not include_soft and e["type"] in SOFT_EDGES:
            continue
        yield e


def in_edges(graph, dst, edge_type=None, include_soft=False):
    for e in graph["edges"]:
        if e["dst"] != dst:
            continue
        if edge_type and e["type"] != edge_type:
            continue
        if not include_soft and e["type"] in SOFT_EDGES:
            continue
        yield e


def _hard_adjacency(graph, node_filter=None):
    adj = {}
    for nid, n in graph["nodes"].items():
        if node_filter and n["type"] != node_filter:
            continue
        adj[nid] = set()
    for e in graph["edges"]:
        if e["type"] != E_REQUIRES:
            continue
        if e["src"] in adj and e["dst"] in adj:
            adj[e["dst"]].add(e["src"])       # dst 依赖 src
    return adj


def find_cycles(graph, node_filter=None):
    """在 requires 硬边上找环（DFS + 回溯栈）。返回环列表（每个环是节点 id 列表）。"""
    adj = _hard_adjacency(graph, node_filter)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in adj}
    stack, cycles = [], []

    def dfs(node):
        color[node] = GRAY
        stack.append(node)
        for pre in sorted(adj.get(node, ())):
            if color.get(pre, WHITE) == GRAY:
                idx = stack.index(pre)
                cycles.append(stack[idx:] + [pre])
            elif color.get(pre, WHITE) == WHITE:
                dfs(pre)
        stack.pop()
        color[node] = BLACK

    for n in sorted(adj):
        if color[n] == WHITE:
            dfs(n)
    return cycles


def topo_order_courses(graph):
    """课程按硬前置做拓扑排序（Kahn）。有环时返回已排序部分 + 剩余部分。"""
    adj = _hard_adjacency(graph, NODE_COURSE)      # dst -> {src...}
    indeg = {n: len(pres) for n, pres in adj.items()}
    out = []
    ready = sorted([n for n, d in indeg.items() if d == 0])
    # dst 依赖 src，所以先出 indeg==0（无前置）的
    while ready:
        n = ready.pop(0)
        out.append(n)
        for m, pres in adj.items():
            if n in pres:
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)
        ready.sort()
    leftovers = [n for n in sorted(adj) if n not in out]
    return out + leftovers


# ---------------- 状态：就绪度 ----------------

AVAILABLE, LOCKED, IN_PROGRESS, PASSED = "available", "locked", "in_progress", "passed"


def course_status(graph, mastery_state):
    """每门课的就绪状态。

    mastery_state 形如 {"lessons": {"py-agent-03": {"passed": true, ...}},
                        "atoms": {"py-agent-02:K1": {"passed": false, "review_queue": true}}}
    """
    state = mastery_state or {}
    lessons = state.get("lessons") or {}
    atoms = state.get("atoms") or {}
    passed_courses = {cid for cid, rec in lessons.items() if rec.get("passed")}

    # 按课程前缀给知识点建索引：只要有该课的知识点活动，就算"进行中"，
    # 不能只看 lessons 记录 —— 否则"练了但还没结算"的课会被误显示成未开始。
    by_course = {}
    for key, rec in atoms.items():
        cid = key.split(":", 1)[0]
        by_course.setdefault(cid, []).append((key, rec or {}))

    out = {}
    for node in course_nodes(graph):
        cid = node["id"]
        rec = lessons.get(cid)
        missing = [p for p in node["requires"] if p not in passed_courses]
        has_activity = (rec is not None) or bool(by_course.get(cid))
        if rec and rec.get("passed"):
            status = PASSED
        elif missing:
            status = LOCKED
        elif has_activity:
            status = IN_PROGRESS
        else:
            status = AVAILABLE
        pairs = by_course.get(cid, [])
        out[cid] = {
            "status": status,
            "missing_prerequisites": missing,
            "mastery": (rec or {}).get("mastery"),
            "reflow_points": sorted(k for k, r in pairs if r.get("review_queue")),
            "recheck_points": sorted(k for k, r in pairs if r.get("recheck_due")),
        }
    return out


def knowledge_status(graph, mastery_state, course_id=None):
    """每个知识点的状态：passed / weak（被打回待补）/ in_review / untouched / blocked。"""
    state = mastery_state or {}
    atoms = state.get("atoms") or {}
    out = {}
    for node in knowledge_nodes(graph, course_id):
        rec = atoms.get(node["id"])
        missing = [e["src"] for e in in_edges(graph, node["id"], E_REQUIRES)]
        missing = [m for m in missing if not (atoms.get(m) or {}).get("passed")]
        if rec and rec.get("passed"):
            status = PASSED
        elif rec and rec.get("review_queue"):
            status = "weak"
        elif missing:
            status = "blocked"
        elif rec:
            status = IN_PROGRESS
        else:
            status = "untouched"
        out[node["id"]] = {
            "status": status,
            "mastery": (rec or {}).get("mastery"),
            "blocked_by": missing,
            "level": node["level"],
            "title": node["title"],
        }
    return out


def unlock_path(graph, target_course):
    """某门课还差哪些课没通过（沿硬前置递归）。"""
    missing, seen = set(), set()

    def walk(cid):
        for e in in_edges(graph, cid, E_REQUIRES):
            src = e["src"]
            if src in seen:
                continue
            seen.add(src)
            missing.add(src)
            walk(src)

    walk(target_course)
    return sorted(missing)


def mastery_consistency(graph, mastery_state):
    """掌握度状态与图是否自相矛盾。

    会抓到这类问题：
      - 某课标记为"已通过"，但它声明的硬前置没通过（说明有人绕过了门禁）
      - 某知识点标记为"已通过"，但它的前置知识点没通过

    这一检查之所以必要：单课闭环（P0）是可以被单独调起来跑的，
    一旦绕过路线，状态就会与体系图对不上。**宁可报出来，也不要默默显示"已通过"。**

    例外：被 `cascade_recheck` 标记为 `recheck_due` 的节点不算矛盾——
    那是回炉的正常级联后果（用户确实通过过，只是地基松动了）。
    """
    issues = []
    state = mastery_state or {}
    atoms = state.get("atoms") or {}

    for cid, info in course_status(graph, state).items():
        if info["status"] == PASSED and info["missing_prerequisites"]:
            issues.append({"kind": "course_passed_without_prereqs",
                           "course": cid,
                           "missing": info["missing_prerequisites"]})

    for nid, rec in atoms.items():
        if not (rec or {}).get("passed") or (rec or {}).get("recheck_due"):
            continue
        node = graph["nodes"].get(nid)
        if not node or node["type"] != NODE_KNOWLEDGE:
            continue
        miss = [e["src"] for e in in_edges(graph, nid, E_REQUIRES)
                if not (atoms.get(e["src"]) or {}).get("passed")]
        if miss:
            issues.append({"kind": "knowledge_passed_without_prereqs",
                           "id": nid, "missing": miss})
    return issues


def cascade_recheck(graph, mastery_state, knocked_back_ids, reason="前置回炉"):
    """回炉的级联影响：把直接/间接依赖被打回知识点的【已通过】知识点标为待复查。

    为什么不是"连带打回"：用户确实通过过上层知识点，把它一并翻成未通过等于
    抹掉真实进度。但地基松动了是事实，所以要标出来让他复查。
    `mastery_consistency` 会因此不再把它们算成"绕过门禁"的矛盾。

    返回被标记的节点列表（含深度）。
    """
    atoms = (mastery_state or {}).setdefault("atoms", {})
    marked, seen = [], set()
    frontier = list(knocked_back_ids)

    for depth in range(1, 4):                     # 最多追 3 层，避免全图扩散
        nxt = []
        for src in frontier:
            for e in out_edges(graph, src, E_REQUIRES):
                dep = e["dst"]
                if dep in seen or dep in knocked_back_ids:
                    continue
                seen.add(dep)
                rec = atoms.get(dep)
                if rec and rec.get("passed"):
                    rec["recheck_due"] = True
                    rec["recheck_reason"] = f"{reason}：{src}"
                    rec["recheck_depth"] = depth
                    marked.append({"id": dep, "depth": depth, "via": src})
                nxt.append(dep)
        frontier = nxt
        if not frontier:
            break
    return marked
