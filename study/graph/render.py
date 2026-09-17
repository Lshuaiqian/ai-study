"""graph · 渲染：Mermaid 图与文本视图（不依赖任何图形库）。"""

from .builder import (AVAILABLE, E_APPLIES, E_CONTRAST, E_REQUIRES,
                      IN_PROGRESS, LOCKED, NODE_KNOWLEDGE, PASSED,
                      course_status, in_edges, knowledge_nodes, knowledge_status,
                      out_edges, topo_order_courses)

STATUS_ICON = {PASSED: "✅", AVAILABLE: "🟡", LOCKED: "🔒",
               IN_PROGRESS: "▶️", "weak": "⚠️", "blocked": "⛔",
               "untouched": "⚪", "in_review": "🔁"}

STATUS_LABEL = {PASSED: "已通过", AVAILABLE: "可开始", LOCKED: "未解锁",
                IN_PROGRESS: "进行中"}

SHORT = {
    "py-agent-01": "L1 语法+OOP",
    "py-agent-02": "L2 HTTP/JSON",
    "py-agent-03": "L3 爬虫",
    "py-agent-04": "L4 数据分析",
    "py-agent-05": "L5 可视化报告",
    "py-agent-06": "L6 项目整合",
    "py-agent-07": "L7 LLM API",
    "py-agent-08": "L8 Agent/FC",
    "py-agent-09": "L9 考核答辩",
}


def _mid(node_id):
    return "n_" + node_id.replace("-", "_").replace(":", "_")


def course_dag_mermaid(graph, status=None):
    """课程级 DAG（mermaid flowchart），按掌握状态着色。"""
    lines = ["flowchart LR"]
    for node in sorted(graph["nodes"].values(),
                       key=lambda n: n["id"] if n["type"] == "course" else ""):
        if node["type"] != "course":
            continue
        label = SHORT.get(node["id"], node["title"])
        lines.append(f'    {_mid(node["id"])}["{label}"]')
    for e in graph["edges"]:
        if e["type"] != E_REQUIRES:
            continue
        src_node = graph["nodes"].get(e["src"])
        dst_node = graph["nodes"].get(e["dst"])
        if src_node and dst_node and src_node["type"] == "course" and dst_node["type"] == "course":
            lines.append(f'    {_mid(e["src"])} --> {_mid(e["dst"])}')
    lines += [
        "    classDef passed fill:#d5f5e3,stroke:#27ae60,color:#145a32",
        "    classDef available fill:#fef9e7,stroke:#f1c40f,color:#7d6608",
        "    classDef locked fill:#f2f3f4,stroke:#bdc3c7,color:#7f8c8d",
        "    classDef in_progress fill:#eaf2fd,stroke:#2980b9,color:#1b4f72",
    ]
    if status:
        buckets = {}
        for cid, info in status.items():
            buckets.setdefault(info["status"], []).append(_mid(cid))
        for st, ids in buckets.items():
            lines.append(f'    class {",".join(sorted(ids))} {st}')
    return "\n".join(lines)


def knowledge_mermaid(graph, course_id, status=None, include_soft=False):
    """某门课的知识点 DAG，含指向其他课程的前置（虚线框表示外部节点）。"""
    lines = ["flowchart LR"]
    kn = knowledge_nodes(graph, course_id)
    local_ids = {n["id"] for n in kn}
    externals = {}

    for node in kn:
        label = f'{node["kp"]} {node["title"][:18]}'
        lines.append(f'    {_mid(node["id"])}["{label}"]')

    def edge(src, dst, arrow, label=""):
        lab = f"|{label}|" if label else ""
        lines.append(f'    {_mid(src)} {arrow}{lab} {_mid(dst)}')

    for node in kn:
        for e in in_edges(graph, node["id"], E_REQUIRES):
            src = e["src"]
            if src in local_ids:
                edge(src, node["id"], "-->")
            else:
                if src not in externals:
                    ext = graph["nodes"][src]
                    externals[src] = ext
                    lines.append(f'    {_mid(src)}[/"{SHORT.get(ext["course"], ext["course"])}'
                                 f' {ext["kp"]}"/]')
                edge(src, node["id"], "-.->", "前置")
        if include_soft:
            for e in out_edges(graph, node["id"], E_CONTRAST):
                edge(node["id"], e["dst"], "-.-", "对比")
            for e in out_edges(graph, node["id"], E_APPLIES):
                edge(node["id"], e["dst"], "==>", "会用到")

    lines += [
        "    classDef passed fill:#d5f5e3,stroke:#27ae60,color:#145a32",
        "    classDef weak fill:#fdecea,stroke:#c0392b,color:#78281f",
        "    classDef blocked fill:#f2f3f4,stroke:#bdc3c7,color:#7f8c8d",
        "    classDef untouched fill:#fbfcfc,stroke:#95a5a6,color:#5d6d7e",
        "    classDef in_progress fill:#eaf2fd,stroke:#2980b9,color:#1b4f72",
    ]
    if status:
        buckets = {}
        for nid, info in status.items():
            if nid in local_ids:
                buckets.setdefault(info["status"], []).append(_mid(nid))
        for st, ids in buckets.items():
            lines.append(f'    class {",".join(sorted(ids))} {st}')
    return "\n".join(lines)


def route_text(graph, status=None, mastery_state=None):
    """路线文本视图：按拓扑顺序列出课程、状态、前置缺口。"""
    status = status if status is not None else course_status(graph, mastery_state or {})
    out = [f"路线：{graph['route'].get('title')}",
           f"入口：{graph['route'].get('entry', {}).get('name')}"
           f"（{graph['route'].get('entry', {}).get('note', '')}）", ""]
    for i, cid in enumerate(topo_order_courses(graph), 1):
        node = graph["nodes"][cid]
        info = status.get(cid, {})
        icon = STATUS_ICON.get(info.get("status"), "?")
        label = STATUS_LABEL.get(info.get("status"), info.get("status", ""))
        m = info.get("mastery")
        mtxt = f" mastery={m:.4f}" if isinstance(m, (int, float)) else ""
        out.append(f"  {icon} {i:>2}. {node['title']}  [{label}]{mtxt}")
        if info.get("missing_prerequisites"):
            names = [SHORT.get(p, p) for p in info["missing_prerequisites"]]
            tag = "⚠️ 前置未通过" if info.get("status") == PASSED else "缺前置"
            out.append(f"        {tag}：{'、'.join(names)}")
        if info.get("reflow_points"):
            out.append(f"        回炉中：{'、'.join(info['reflow_points'])}")
        if info.get("recheck_points"):
            out.append(f"        待复查：{'、'.join(info['recheck_points'])}"
                       f"（地基被回炉，需重新确认）")
    return "\n".join(out)


def knowledge_text(graph, course_id, status=None, mastery_state=None):
    """单课知识点视图：每个点的状态、掌握度、被什么挡住、以及跨课前置。"""
    status = status if status is not None else knowledge_status(
        graph, mastery_state or {}, course_id)
    out = [f"知识点体系 · {course_id}", ""]
    for node in knowledge_nodes(graph, course_id):
        info = status.get(node["id"], {})
        icon = STATUS_ICON.get(info.get("status"), "?")
        lvl = "必会" if node["level"] == "must" else "了解"
        m = info.get("mastery")
        mtxt = f"  mastery={m:.2f}" if isinstance(m, (int, float)) else ""
        out.append(f"  {icon} [{lvl}] {node['kp']} {node['title']}{mtxt}")
        for e in in_edges(graph, node["id"], E_REQUIRES):
            src = graph["nodes"][e["src"]]
            where = "本课" if src.get("course") == course_id else SHORT.get(src.get("course"), "")
            out.append(f"         ← 前置：{where} {src.get('kp', src['id'])} "
                       f"{src['title'][:26]}｜{e['why']}")
        if node.get("contrast_external"):
            out.append(f"         ⇄ 对照：{'、'.join(node['contrast_external'])}")
        if info.get("blocked_by"):
            out.append(f"         ⛔ 被挡住：{'、'.join(info['blocked_by'])}")
    return "\n".join(out)


def issues_text(graph):
    """一致性问题的可读输出。"""
    issues = graph.get("issues") or []
    if not issues:
        return "校验：✅ 无问题（无环、无未知引用、人写的 declares 与 route 一致）"
    out = [f"校验：⚠️ {len(issues)} 个问题"]
    for it in issues:
        kind = it.get("kind")
        if kind == "cycle":
            out.append(f"  ❌ 存在环：{it['cycles']}")
        elif kind == "prereq_mismatch":
            out.append(f"  ⚠️ [{it['course']}] 前置不一致：route={it['route']} "
                       f"declares={it['declares']}")
        elif kind == "unlocks_mismatch":
            out.append(f"  ⚠️ [{it['course']}] unlocks 不一致：由图反推={it['derived']} "
                       f"declares={it['declares']}")
        elif kind.startswith("unknown"):
            out.append(f"  ❌ 未知引用（{kind}）：{ {k: v for k, v in it.items() if k != 'kind'} }")
        elif kind == "missing_curriculum":
            out.append(f"  ⬜ [{it['course']}] 空壳课程——route 声明了它，"
                       f"但没有任何知识点：{it.get('title', '')}")
        else:
            out.append(f"  ⚠️ {kind}: { {k: v for k, v in it.items() if k != 'kind'} }")
    return "\n".join(out)


def consistency_text(issues):
    """掌握度状态与图的自洽性检查结果。"""
    if not issues:
        return "自洽性：✅ 掌握度状态与体系图一致（没有绕过前置通过的课/知识点）"
    out = [f"自洽性：⚠️ {len(issues)} 个矛盾"]
    for it in issues:
        if it["kind"] == "course_passed_without_prereqs":
            miss = "、".join(SHORT.get(p, p) for p in it["missing"])
            out.append(f"  ❌ [{it['course']}] 标记为已通过，但硬前置未通过：{miss}"
                       f"  ← 有人绕过了门禁")
        elif it["kind"] == "knowledge_passed_without_prereqs":
            out.append(f"  ❌ [{it['id']}] 知识点标记为已通过，但前置未通过："
                       f"{'、'.join(it['missing'])}")
    return "\n".join(out)
