#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""渲染知识点体系图（P0+ · 体系化视图）。

用法：
    E:\\Develop\\python\\python.exe study\\tools\\render_graph.py
    E:\\Develop\\python\\python.exe study\\tools\\render_graph.py --course py-agent-03 --soft
    E:\\Develop\\python\\python.exe study\\tools\\render_graph.py --out study\\state\\graph.md
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.store import read_json                                    # noqa: E402
from graph import (build, consistency_text, course_dag_mermaid,      # noqa: E402
                   course_status, issues_text, knowledge_mermaid,
                   knowledge_status, knowledge_text, load_curriculums,
                   load_route, mastery_consistency, route_text)
from graph.builder import topo_order_courses                          # noqa: E402


def main():
    argv = sys.argv[1:]
    course = "py-agent-03"
    if "--course" in argv:
        course = argv[argv.index("--course") + 1]
    include_soft = "--soft" in argv
    out_path = argv[argv.index("--out") + 1] if "--out" in argv else None

    route = load_route(os.path.join(BASE, "route.json"))
    curriculums = load_curriculums(os.path.join(BASE, "curriculum"))
    state = read_json(os.path.join(BASE, "state", "mastery.json"), default={})

    graph = build(route, curriculums)
    cst = course_status(graph, state)
    kst = knowledge_status(graph, state, course)

    blocks = []
    blocks.append("## 1. 图的完整性校验\n")
    blocks.append("```")
    blocks.append(issues_text(graph))
    blocks.append("```")
    blocks.append(f"\n节点：课程 {sum(1 for n in graph['nodes'].values() if n['type'] == 'course')} 个"
                  f" + 知识点 {sum(1 for n in graph['nodes'].values() if n['type'] == 'knowledge')} 个"
                  f"｜边 {len(graph['edges'])} 条")
    blocks.append(f"拓扑序：{' → '.join(topo_order_courses(graph))}")

    blocks.append("\n## 2. 路线状态\n")
    blocks.append("```")
    blocks.append(route_text(graph, cst))
    blocks.append("```")

    blocks.append("\n## 2b. 掌握度与图的自洽性\n")
    blocks.append("```")
    blocks.append(consistency_text(mastery_consistency(graph, state)))
    blocks.append("```")

    blocks.append(f"\n## 3. 知识点体系 · {course}\n")
    blocks.append("```")
    blocks.append(knowledge_text(graph, course, kst))
    blocks.append("```")

    blocks.append("\n## 4. 课程 DAG（Mermaid）\n")
    blocks.append("```mermaid")
    blocks.append(course_dag_mermaid(graph, cst))
    blocks.append("```")

    blocks.append(f"\n## 5. 知识点 DAG · {course}（Mermaid）\n")
    blocks.append("```mermaid")
    blocks.append(knowledge_mermaid(graph, course, kst, include_soft=include_soft))
    blocks.append("```")

    text = "\n".join(blocks)
    print(text)

    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("# 知识点体系图（自动生成）\n\n" + text + "\n")
        print(f"\n[已写入 {out_path}]")

    # 有问题时以非零退出，便于 CI / 手动检查
    fatal = [i for i in graph["issues"] if i["kind"] in
             ("cycle",) or i["kind"].startswith("unknown")]
    return 1 if fatal else 0


if __name__ == "__main__":
    sys.exit(main())
