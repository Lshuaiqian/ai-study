"""plan · 自省周报。

设计原则（系统设计 §10）：
  - 报告只**陈述事实**（做了什么、涨了多少、卡在哪），不替用户做价值判断
  - "课末复盘三问"由**用户自己作答**，报告只留空位提示 —— 一旦 AI 打分，就会变成应付
  - 建议部分必须**可执行**（给出下一步具体做什么），而不是"继续加油"
"""
from datetime import date, timedelta

from .review import due_reviews, parse_date, queue_summary, rework_items

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

REVIEW_QUESTIONS = [
    "这周我真正学会了什么？（用自己的话，不要抄笔记）",
    "我在哪里卡住了、最后是怎么出来的？",
    "新学的东西和我已经会的什么有关联？",
]


def _week_bounds(week_start=None):
    if week_start is None:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
    return week_start, week_start + timedelta(days=7)


def weekly_report(events, graph, mastery_state, week_start=None, today=None):
    """生成一周的自省报告（文本）。

    today 必须与 daily_view 用同一个值，否则"当前待复习"的数量会对不上
    （周报按系统日期算、视图按传入日期算，实测出现过 7 vs 9 的不一致）。
    """
    start, end = _week_bounds(week_start)
    week = [e for e in events if start.isoformat() <= (e.get("ts") or "") < end.isoformat()]

    submissions = [e for e in week if e.get("kind") == "submission"]
    passed = [e for e in week if e.get("kind") == "passed"]
    # note_review 有两个来源，parts 的形状不同，不能混在一起算"最弱维度"：
    # 体检给五维（structure/coverage/accuracy/linking/own_words），
    # 一键整理只给 coverage。按 source 分开。
    note_reviews = [e for e in week if e.get("kind") == "note_review"]
    tidies = [e for e in note_reviews if e.get("source") == "note-tidy"]
    checkups = [e for e in note_reviews if e.get("source") != "note-tidy"]
    interrogations = [e for e in week if e.get("kind") == "interrogation"]
    reflows = [e for e in week if e.get("kind") == "reflow"]
    rechecks = [e for e in week if e.get("kind") == "recheck"]
    reviews_done = [e for e in week if e.get("kind") == "review_done"]
    blocked = [e for e in week if e.get("kind") == "blocked_entry"]

    title_of = {nid: n["title"] for nid, n in graph["nodes"].items()}

    L = []
    L.append(f"📊 学习周报 · {start.isoformat()} ~ {(end - timedelta(days=1)).isoformat()}")
    L.append("=" * 62)

    # ---- 1 概览 ----
    L.append("\n【本周概览】")
    L.append(f"  提交次数      {len(submissions)}")
    L.append(f"  通过课程      {len(passed)} 门"
             + (f"：{'、'.join(title_of.get(e.get('course_id'), e.get('course_id')) for e in passed)}"
                if passed else ""))
    L.append(f"  笔记体检      {len(checkups)} 次")
    L.append(f"  一键整理      {len(tidies)} 次")
    L.append(f"  AI 质询      {len(interrogations)} 次")
    L.append(f"  复习完成      {len(reviews_done)} 个知识点")
    if blocked:
        L.append(f"  被门禁拦下    {len(blocked)} 次")

    # ---- 2 代码量（这是"足够的代码量训练"的客观依据）----
    L.append("\n【代码量】")
    if submissions:
        by_course = {}
        for e in submissions:
            by_course.setdefault(e.get("course_id"), []).append(e.get("lines") or 0)
        total = sum(sum(v) for v in by_course.values())
        L.append(f"  有效代码行合计 {total}")
        for cid, lines in sorted(by_course.items()):
            L.append(f"    {title_of.get(cid, cid)}：{sum(lines)} 行"
                     f"（{len(lines)} 次提交）")
    else:
        L.append("  （本周没有提交）")

    # ---- 3 掌握度 ----
    L.append("\n【掌握度变化】")
    if submissions:
        for cid in sorted({e.get("course_id") for e in submissions}):
            seq = [e for e in submissions if e.get("course_id") == cid]
            first, last = seq[0].get("mastery"), seq[-1].get("mastery")
            if isinstance(first, (int, float)) and isinstance(last, (int, float)):
                arrow = "↑" if last > first else ("↓" if last < first else "→")
                L.append(f"  {title_of.get(cid, cid)}：{first:.4f} {arrow} {last:.4f}")
    else:
        L.append("  （无数据）")

    # ---- 4 笔记质量 ----
    L.append("\n【笔记质量】")
    if checkups:
        scores = [e.get("note_score") or 0 for e in checkups]
        L.append(f"  体检平均 {sum(scores) / len(scores):.4f}｜最低 {min(scores):.4f}")
        worst = {}
        for e in checkups:
            for k, v in (e.get("parts") or {}).items():
                worst[k] = min(worst.get(k, 1.0), v or 0)
        if worst:
            weak = sorted(worst.items(), key=lambda kv: kv[1])[:2]
            L.append("  最弱维度：" + "、".join(f"{k}({v:.2f})" for k, v in weak))
    else:
        L.append("  （本周没有体检记录）")
    if tidies:
        ts = [e.get("note_score") or 0 for e in tidies]
        L.append(f"  整理后笔记维度 平均 {sum(ts) / len(ts):.4f}｜最新 {ts[-1]:.4f}")

    # ---- 4b AI 质询（一键整理的结论真正被消费的地方）----
    if interrogations:
        L.append("\n【AI 质询】")
        for e in interrogations[-3:]:
            cid = e.get("course_id")
            pct = e.get("percent")
            flag = "可跳过" if e.get("can_skip") else "未达标"
            L.append(f"  {title_of.get(cid, cid)}："
                     + (f"{pct:.0%}" if isinstance(pct, (int, float)) else "—")
                     + f"　{flag}")
        not_ready = [e for e in interrogations if not e.get("can_skip")]
        if not_ready and not passed:
            L.append(f"  本周有 {len(not_ready)} 课质询未过线——"
                     "补完缺口再进下一课，别跳")

    # ---- 5 薄弱点与回炉 ----
    L.append("\n【薄弱点与回炉】")
    if reflows:
        for e in reflows:
            L.append(f"  回炉 {e.get('atom')}：{e.get('before')} → {e.get('after')}")
    if rechecks:
        L.append(f"  级联待复查 {len(rechecks)} 个（地基被动摇，需重新确认）")
    if not reflows and not rechecks:
        L.append("  （本周无回炉）")
    q = due_reviews(graph, mastery_state, today)
    if q:
        L.append(f"  当前待复习 {len(q)} 个：")
        for cid, items in queue_summary(q).items():
            L.append(f"    {title_of.get(cid, cid)}："
                     + "、".join(f"{i['id'].split(':')[-1]}({'/'.join(i['reasons'])})"
                                for i in items))

    # ---- 6 复盘三问（留空给用户）----
    L.append("\n【课末复盘三问 —— 由你自己作答，AI 不打分】")
    for i, qn in enumerate(REVIEW_QUESTIONS, 1):
        L.append(f"  {i}. {qn}")
        L.append("     答：______________________________________")

    # ---- 7 下周建议（必须可执行）----
    L.append("\n【下周建议】")
    L += _suggestions(graph, mastery_state, q, rework_items(graph, mastery_state))

    return "\n".join(L)


def _suggestions(graph, mastery_state, queue, rework):
    from graph.builder import course_status            # 延迟导入，避免循环依赖

    items = []
    if queue:
        by_course = queue_summary(queue)
        top = sorted(by_course.items(), key=lambda kv: -len(kv[1]))[:2]
        for cid, its in top:
            items.append(f"先清复习队列：{cid} 有 {len(its)} 个知识点待复习"
                         f"（{'、'.join(i['id'].split(':')[-1] for i in its)}），"
                         f"每个 5–10 分钟的小任务即可，不要重看资料")
    if rework:
        items.append("补练未过的知识点："
                     + "、".join(f"{i['id']}(mastery={i['mastery']})" for i in rework[:3]))
    st = course_status(graph, mastery_state)
    avail = [cid for cid, info in st.items() if info["status"] == "available"]
    if avail:
        titles = "、".join(graph["nodes"][c]["title"] for c in avail[:2])
        items.append(f"可以开新课：{titles}")
    if not items:
        items.append("当前没有待办 —— 要么继续深入当前课程，要么给自己放个假")
    return [f"  {i}) {text}" for i, text in enumerate(items, 1)]


def daily_view(graph, mastery_state, today=None):
    """今日视图：复习 / 补练 / 可开新课，三段。"""
    today = today or date.today()
    L = [f"📅 今日任务 · {today.isoformat()}（{WEEKDAYS[today.weekday()]}）",
         "=" * 62]

    q = due_reviews(graph, mastery_state, today)
    L.append(f"\n【复习 {len(q)}】" + ("（清空 ✅）" if not q else ""))
    for it in q:
        depth = f"  depth={it['recheck_depth']}" if it.get("recheck_depth") else ""
        L.append(f"  · {it['id']}  {it['title'][:30]}  "
                 f"[{'/'.join(it['reasons'])}]  stage={it['stage']}{depth}")

    rw = rework_items(graph, mastery_state)
    L.append(f"\n【补练 {len(rw)}】" + ("（无）" if not rw else ""))
    for it in rw:
        L.append(f"  · {it['id']}  {it['title'][:30]}  mastery={it['mastery']}")

    from graph.builder import course_status
    st = course_status(graph, mastery_state)
    avail = [cid for cid, info in st.items() if info["status"] == "available"]
    inprog = [cid for cid, info in st.items() if info["status"] == "in_progress"]
    L.append(f"\n【课程】进行中 {len(inprog)}｜可开始 {len(avail)}")
    for cid in inprog:
        L.append(f"  ▶️ {cid}  {graph['nodes'][cid]['title']}")
    for cid in avail:
        L.append(f"  🟡 {cid}  {graph['nodes'][cid]['title']}")

    return "\n".join(L)
