#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""花笺课程脚手架：把知识体系落成花笺里的「课程主文件夹 + 子笔记页」。

产物（在花笺的 notesDir 下）
    <主文件夹>/                     ← category，默认「西二AI-2026」
       00-学习路线.md               ← 主要学习路线（拓扑序 + 前置/解锁 + 进度）
       01-知识体系.md               ← 7 维度 × 知识点 × 归属课程
       F0-环境搭建.md               ← 每课一个子笔记页
       F1-语法基础与面向对象.md
       ...

每课子笔记的结构
    **考核要求写最上面**（学习目的 / 学习内容 / 学习要求 / 作业清单 / 知识点），
    下面是「我的笔记」空段。这样一键整理（interrogate.py）能直接拿上半部分查缺补漏。

用法
    python study\\tools\\scaffold.py plan                        # 只打印将要建什么
    python study\\tools\\scaffold.py apply --yes                 # 单层分类（当前花笺即可用）
    python study\\tools\\scaffold.py apply --multilevel --yes     # 多层分类（需花笺打过多层补丁）
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from notes import (discover, make_entry, read_note, scan,         # noqa: E402
                   upsert_metadata, write_note)
from system import (CODE_LABEL, STAGE_LABEL, course_index,          # noqa: E402
                    load_placement, load_system, placement_report,
                    to_curriculum, topo_courses)

SYSTEM_PATH = None      # 运行时由 active_paths 决定（见 system/active.py）
PLACEMENT_PATH = None      # 运行时由 active_paths 决定
DEFAULT_FOLDER = "西二AI-2026"
NOTES_HEADING = "## ✍️ 我的笔记"


def short_title(system, course):
    """给笔记起一个能排序、能看懂的短标题：`F2-网络爬虫与数据分析`。"""
    code = CODE_LABEL.get(course["course_id"], course["course_id"])
    # 从完整标题里去掉「Foundation Task 2 · 」这类前缀
    t = course["title"]
    for sep in ("·", "·"):
        if sep in t:
            t = t.split(sep, 1)[1].strip()
            break
    t = t.replace("/", "-").replace("\\", "-").replace("：", "-").strip()
    return f"{code}-{t}"


# ---------------------------------------------------------------- 笔记正文

def course_note(system, course, placement=None):
    cur = to_curriculum(system, course, placement)
    d = cur["declares"]
    code = CODE_LABEL.get(course["course_id"], course["course_id"])
    # 课程身份标记：花笺里改标题（= 改文件名）后，「一键整理」仍能认出这是哪门课。
    # 用 HTML 注释而不是 YAML frontmatter —— 花笺的 markdown 渲染对注释透明，
    # YAML 会被当正文渲染出一条分隔线。update 模式会幂等刷新这一行。
    # stage 为空时不写（九课体系的 course.stage 就是空串，写了会留下难看的 `stage=`）。
    _stage = str(course.get("stage") or "").strip()
    _marker = f"<!-- study: course={course['course_id']}" + (
        f" stage={_stage} -->" if _stage else " -->")
    L = [_marker, f"# {code} · {course['title']}", ""]
    L.append("> 本页由 `study/tools/scaffold.py` 从知识体系生成。")
    L.append("> **上面这段「考核要求」不要删** —— 一键整理要用它来查缺补漏。")
    L.append(f"> 课程 id：`{course['course_id']}`｜阶段：{STAGE_LABEL.get(course['stage'], course['stage'])}")
    L.append("")

    # ---- 你的起点（依据实际产物判定，不是自评）----
    pl = cur.get("placement")
    if pl:
        L.append("## ⚡ 你的起点")
        L.append("")
        L.append(f"依据实际产物判定：**已具备 {pl['met_count']}/{pl['total']} 个知识点**。")
        name_of = {k["source_knowledge"]: k["name"] for k in d["knowledge"]}

        if pl.get("fast_pass"):
            L.append("")
            L.append("⏩ **你已决定快速过本课**（带疑点前进）")
            if pl.get("decision_reason"):
                L.append("")
                L.append(f"> {pl['decision_reason']}")
            if pl.get("carried_over"):
                L.append("")
                L.append(f"**挂账 {len(pl['carried_over'])} 个知识点** —— 不是忘了，是记账了：")
                L.append("")
                for gid in pl["carried_over"]:
                    L.append(f"- `{gid}` {name_of.get(gid, '')}")
                L.append("")
                if pl.get("recheck_at"):
                    L.append(f"复查时机：{pl['recheck_at']}")
            if pl.get("decision_warning"):
                L.append("")
                L.append(f"> ⚠️ {pl['decision_warning']}")
        elif pl["likely_fast_pass"]:
            L.append("")
            L.append("✅ 本课知识点你已全部具备 —— **可以快速过或直接跳过**，"
                     "但建议先跑一次一键整理确认。")
        elif pl["focus"]:
            L.append("")
            L.append(f"**只需补这 {len(pl['focus'])} 项**（其余按已具备处理）：")
            L.append("")
            for f in pl["focus"]:
                mark = {"not_started": "⬜ 未开始", "unknown": "❓ 无证据",
                        "partial": "🟡 部分具备"}.get(f["status"], f["status"])
                weak = "　⚠️ **反复错过的点**" if f.get("weak") else ""
                L.append(f"- {mark} `{f['id']}` {f['name']}{weak}")
                if f.get("evidence"):
                    L.append(f"  - 判断依据：{f['evidence']}")
        L.append("")
        L.append("> 判断依据全部来自已有产物（进度文件、练习代码、对话历史），"
                 "没有证据的一律标「无证据」而不是假装会。")
        L.append("")

    L.append("## 📋 考核要求")
    L.append("")
    for key in ("学习目的", "学习内容", "学习要求"):
        if course.get(key):
            L.append(f"### {key}")
            L.append("")
            L.append(course[key])
            L.append("")

    L.append("### 作业清单")
    L.append("")
    for t in cur["tasks"]:
        L.append(f"- [ ] `{t['task_id']}` **{t['title']}** — {t['brief']}")
    L.append("")

    L.append("### 本课知识点（一键整理按这个算覆盖率）")
    L.append("")
    dims = {}
    for k in d["knowledge"]:
        dims.setdefault(k["dimension_name"] or k["dimension"], []).append(k)
    for dim, ks in dims.items():
        L.append(f"**{dim}**")
        L.append("")
        for k in ks:
            lvl = "必会" if k["level"] == "must" else "了解"
            L.append(f"- [{lvl}] `{k['source_knowledge']}` {k['name']}")
        L.append("")

    L.append("### 前置 / 解锁")
    L.append("")
    L.append("- 前置：" + ("、".join(p["name"] for p in d["prerequisites"]) or "（本课是路线起点）"))
    L.append("- 解锁：" + ("、".join(u["name"] for u in d["unlocks"]) or "（路线终点）"))
    L.append("")

    L.append("---")
    L.append("")
    L.append("## ✍️ 我的笔记")
    L.append("")
    L.append(f"（写完后运行：`python study\\tools\\interrogate.py --course {course['course_id']}`）")
    L.append("")
    for sec, hint in (
        ("1. 我学到的（用自己的话）", "不要抄资料；写你真正理解了什么"),
        ("2. 作业记录", "每道作业：做了什么、结果如何、卡在哪"),
        ("3. 踩到的坑", "报错原文 + 怎么定位 + 最后怎么解决的"),
        ("4. 还没搞懂的", "列出来，一键整理会针对这些提问"),
    ):
        L.append(f"### {sec}")
        L.append("")
        L.append(f"<!-- {hint} -->")
        L.append("")
    return "\n".join(L)


def route_note(system, placement=None):
    courses = course_index(system)
    order = topo_courses(system)
    L = [f"# {system['title']} · 主要学习路线", ""]
    src = system.get("source") or {}
    L.append(f"> 来源：{src.get('repo')}（{src.get('license')}）｜抓取于 {src.get('fetched_at')}")
    L.append("> 本页由知识体系派生。**体系是唯一真源**，所有课程笔记都是它的切片。")
    L.append("")

    L.append("## 分流结构")
    L.append("")
    L.append("```")
    L.append("Foundation（共通，F0 → F4）")
    L.append("        │")
    L.append("        ├── Scientific Research  →  R1（保研/进实验室方向）")
    L.append("        └── Application          →  A0（门槛）→ A1（找工作方向）")
    L.append("")
    L.append("方向日常训练（可与上面并行）：BE 后端 / FE 前端 / ST 统计")
    L.append("```")
    L.append("")

    L.append("## 学习顺序（拓扑序）")
    L.append("")
    L.append("| # | 代号 | 课程 | 阶段 | 前置 |")
    L.append("| --- | --- | --- | --- | --- |")
    for i, cid in enumerate(order, 1):
        c = courses[cid]
        pre = "、".join(CODE_LABEL.get(p, p) for p in (c.get("requires") or [])) or "—"
        L.append(f"| {i} | {CODE_LABEL.get(cid, cid)} | {c['title']} | "
                 f"{STAGE_LABEL.get(c['stage'], c['stage'])} | {pre} |")
    L.append("")

    L.append("## 每课知识点数")
    L.append("")
    rep = placement_report(system, placement) if placement else None
    by_course = {r["course_id"]: r for r in (rep or {}).get("rows", [])}
    if rep:
        L.append("| 代号 | 必会 | 了解 | 作业数 | 已具备 | 状态 |")
        L.append("| --- | --- | --- | --- | --- | --- |")
    else:
        L.append("| 代号 | 必会 | 了解 | 作业数 |")
        L.append("| --- | --- | --- | --- |")
    for cid in order:
        c = courses[cid]
        cur = to_curriculum(system, c)
        ks = cur["declares"]["knowledge"]
        must = sum(1 for k in ks if k["level"] == "must")
        base = f"| {CODE_LABEL.get(cid, cid)} | {must} | {len(ks) - must} | {len(cur['tasks'])} |"
        if rep:
            r = by_course.get(cid, {"met": 0, "total": len(ks), "done": False})
            mark = "✅ 已具备" if r["done"] else ("🟡 部分" if r["met"] else "⬜ 未开始")
            base += f" {r['met']}/{r['total']} | {mark} |"
        L.append(base)
    L.append("")

    if rep and rep.get("next_course"):
        nxt = rep["next_course"]
        L.append("## 📍 我的位置")
        L.append("")
        L.append(f"▶️ **下一步：{CODE_LABEL.get(nxt['course_id'], nxt['course_id'])} · "
                 f"{nxt['title']}**（已具备 {nxt['met']}/{nxt['total']}）")
        L.append("")
        if rep.get("focus"):
            L.append("本课还需补：")
            L.append("")
            for f in rep["focus"]:
                mark = {"not_started": "⬜ 未开始", "unknown": "❓ 无证据",
                        "partial": "🟡 部分具备"}.get(f["status"], f["status"])
                L.append(f"- {mark} `{f['knowledge']}`")
            L.append("")
        if rep.get("weak_points"):
            L.append("⚠️ 反复错过的点（来自对话历史，不是自评）：")
            L.append("")
            for w in rep["weak_points"]:
                L.append(f"- `{w['knowledge']}`：{w['issue']}")
            L.append("")
        L.append(f"> 评估于 {rep['assessed_at']}｜依据："
                 f"{len(rep.get('evidence') or [])} 条实际产物证据")
        L.append("")

    L.append("## 进度")
    L.append("")
    L.append("<!-- 由 study 工具回填：python study\\tools\\plan.py -->")
    L.append("")
    for cid in order:
        r = by_course.get(cid)
        code = CODE_LABEL.get(cid, cid)
        box = "x" if (r and r["done"]) else " "
        suffix = f"　（已具备 {r['met']}/{r['total']}）" if r else ""
        L.append(f"- [{box}] {code} {courses[cid]['title']}{suffix}")
    return "\n".join(L)


def system_note(system):
    know = system["knowledge"]
    courses = system["courses"]
    owner = {}
    for c in courses:
        for kid in c["knowledge"]:
            owner.setdefault(kid, []).append(CODE_LABEL.get(c["course_id"], c["course_id"]))

    L = [f"# 知识体系 · {system['title']}", ""]
    L.append(f"> 维度 {len(system['dimensions'])}｜知识点 {len(know)}｜"
             f"课程 {len(courses)}｜拆分器 `study/system/split.py`")
    L.append("")

    L.append("## 维度总览")
    L.append("")
    L.append("| 维度 | 说明 | 知识点 |")
    L.append("| --- | --- | --- |")
    for d in system["dimensions"]:
        n = sum(1 for k in know if k.get("dim") == d["id"])
        L.append(f"| {d['id']} {d['name']} | {d.get('desc', '')} | {n} |")
    L.append("")

    L.append("## 知识点 × 归属课程")
    L.append("")
    for d in system["dimensions"]:
        ks = [k for k in know if k.get("dim") == d["id"]]
        if not ks:
            continue
        L.append(f"### {d['id']} {d['name']}")
        L.append("")
        for k in ks:
            lvl = "必会" if k.get("level") == "must" else "了解"
            who = "、".join(owner.get(k["id"], [])) or "**（无人讲！）**"
            L.append(f"- [{lvl}] `{k['id']}` {k['name']}　→ {who}")
        L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- 主流程

def build_plan(system, folder, multilevel, placement=None):
    courses = course_index(system)
    plan = []

    def cat_for(cid=None):
        if not multilevel or cid is None:
            return folder
        return f"{folder}/{short_title(system, courses[cid])}"

    plan.append({"title": "00-学习路线", "category": cat_for(), "kind": "route",
                 "content": route_note(system, placement)})
    plan.append({"title": "01-知识体系", "category": cat_for(), "kind": "system",
                 "content": system_note(system)})
    for cid in topo_courses(system):
        plan.append({"title": short_title(system, courses[cid]),
                     "category": cat_for(cid), "course_id": cid, "kind": "course",
                     "content": course_note(system, courses[cid], placement)})
    return plan


def cmd_plan(system, argv):
    folder = _arg(argv, "--folder", DEFAULT_FOLDER)
    multilevel = "--multilevel" in argv
    d = discover(_arg(argv, "--data-dir"))
    plan = build_plan(system, folder, multilevel)

    print(f"花笺 notesDir：{d['notes_dir']}")
    print(f"主文件夹：{folder}（{'多层分类' if multilevel else '单层分类'}）")
    print(f"将创建 {len(plan)} 篇笔记：\n")
    for item in plan:
        cat = item["category"]
        print(f"  [{cat}] {item['title']}.md  ({len(item['content'])} 字)")
    if not multilevel:
        print("\n提示：单层分类下所有笔记都在同一文件夹里，靠标题前缀区分课程。")
        print("      花笺打了「多层分类」补丁后可用 --multilevel 得到真正的每课子文件夹。")
    return 0


def cmd_apply(system, argv):
    if "--yes" not in argv:
        print("这是写操作：会在花笺笔记目录里创建/更新课程笔记并同步 metadata.json。")
        print("先看 plan，确认后加 --yes 重跑。")
        print("已有笔记默认**跳过**；加 --update-placement 只更新「考核要求」部分，"
              "「✍️ 我的笔记」以下原样保留。")
        return 2
    folder = _arg(argv, "--folder", DEFAULT_FOLDER)
    multilevel = "--multilevel" in argv
    update = "--update-placement" in argv
    d = discover(_arg(argv, "--data-dir"))
    if not d["exists"]:
        print(f"❌ 花笺 notesDir 不存在：{d['notes_dir']}")
        return 1

    placement = _active_placement()
    if placement:
        rep = placement_report(system, placement)
        nxt = rep.get("next_course")
        if nxt:
            print(f"已应用学习位置：下一步 "
                  f"{CODE_LABEL.get(nxt['course_id'], nxt['course_id'])} · {nxt['title']}")
            print()

    plan = build_plan(system, folder, multilevel, placement)
    by_title = {n["title"]: n for n in scan(d["notes_dir"])}
    created = updated = skipped = 0

    for item in plan:
        note = by_title.get(item["title"])
        if note is None:
            note_id, path = write_note(d["notes_dir"], item["title"], item["content"],
                                       item["category"])
            upsert_metadata(d["data_dir"], make_entry(
                note_id, item["title"], os.path.basename(path),
                item["category"], item["content"]))
            print(f"  ✅ 新建 {item['category']} / {item['title']}.md")
            created += 1
            continue

        if not update:
            print(f"  ⏭  已存在，跳过：{item['title']}（用 --update-placement 更新要求部分）")
            skipped += 1
            continue

        old = read_note(note["path"])
        if item["kind"] in ("route", "system"):
            new_text = item["content"]                      # 纯生成物，整体重写
        else:
            # 课程笔记：只替换「## ✍️ 我的笔记」之前的部分，保住用户写的正文
            head, sep, tail = old.partition(NOTES_HEADING)
            if not sep:
                print(f"  ⚠️ {item['title']}：找不到「我的笔记」段落，为免覆盖已跳过")
                skipped += 1
                continue
            new_text = item["content"].split(NOTES_HEADING)[0] + NOTES_HEADING + tail

        if new_text == old:
            print(f"  ⏭  无变化：{item['title']}")
            skipped += 1
            continue
        with open(note["path"], "w", encoding="utf-8") as f:
            f.write(new_text)
        upsert_metadata(d["data_dir"], make_entry(
            note["id"] or "", item["title"], os.path.basename(note["path"]),
            note["category"], new_text))
        print(f"  🔄 更新要求部分：{item['title']}（你的笔记已保留）")
        updated += 1

    print(f"\n完成：新建 {created}，更新 {updated}，跳过 {skipped}")
    return 0


def _arg(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    system = _active_system()
    if argv[0] == "plan":
        return cmd_plan(system, argv)
    if argv[0] == "apply":
        return cmd_apply(system, argv)
    print(f"未知子命令：{argv[0]}\n")
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
