"""plan · 复习队列与间隔重复（确定性，无网络依赖）。

这不是 FSRS，也不假装是。P0/P1 阶段只需要一个**能跑、可解释、可测**的阶梯：
  通过 → stage+1，下次复习 = 今天 + INTERVALS[stage]
  没通过 → stage 归零，明天再来

三种进入复习队列的途径：
  - review_queue   回炉：后续课程暴露前置漏洞，被打回
  - recheck_due    待复查：地基被回炉，需重新确认（不翻转 passed）
  - next_review    到期：正常间隔重复到期
"""
from datetime import date, datetime, timedelta

INTERVALS = [1, 3, 7, 16, 35]          # 天；stage 递增

PRIORITY = {"回炉未清": 0, "待复查": 1, "到期复习": 2}


def parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def due_reviews(graph, mastery_state, today=None):
    """今天该复习的知识点，按优先级排序。"""
    today = today or date.today()
    atoms = (mastery_state or {}).get("atoms") or {}
    out = []

    for nid, rec in atoms.items():
        node = graph["nodes"].get(nid)
        if not node or node["type"] != "knowledge":
            continue
        rec = rec or {}
        reasons = []
        if rec.get("review_queue"):
            reasons.append("回炉未清")
        if rec.get("recheck_due"):
            reasons.append("待复查")
        due = parse_date(rec.get("next_review"))
        if due and due <= today:
            reasons.append("到期复习")
        if not reasons:
            continue
        out.append({
            "id": nid,
            "course": node["course"],
            "title": node["title"],
            "level": node["level"],
            "mastery": rec.get("mastery"),
            "stage": rec.get("stage", 0),
            "reasons": reasons,
            "overdue_days": max(0, (today - due).days) if due else 0,
            "recheck_depth": rec.get("recheck_depth") or 0,
            "priority": min(PRIORITY[r] for r in reasons),
        })

    # 排序：先按原因优先级，再按级联深度（浅层更该先看），再按逾期天数。
    # 一次回炉可能级联出很多待复查项（实测一次 6 个），按深度排序能让
    # 用户先处理"直接受影响"的，而不是被一堆两层外的点淹没。
    return sorted(out, key=lambda x: (x["priority"], x["recheck_depth"],
                                      -x["overdue_days"], x["id"]))


def rework_items(graph, mastery_state):
    """学过但没通过的知识点 —— 这些是"补练"任务，不是复习。"""
    atoms = (mastery_state or {}).get("atoms") or {}
    out = []
    for nid, rec in atoms.items():
        rec = rec or {}
        node = graph["nodes"].get(nid)
        if not node or node["type"] != "knowledge":
            continue
        if rec.get("passed") or rec.get("review_queue"):
            continue                      # 已通过的不算；回炉的走复习队列
        out.append({"id": nid, "course": node["course"], "title": node["title"],
                    "mastery": rec.get("mastery"), "attempts": rec.get("attempts", 0)})
    return sorted(out, key=lambda x: x["id"])


def promote_review(rec, success, today=None):
    """复习结束后推进（或回退）间隔阶梯。就地修改 rec 并返回它。"""
    today = today or date.today()
    if success:
        stage = min((rec.get("stage") or 0) + 1, len(INTERVALS) - 1)
        rec["stage"] = stage
        rec["next_review"] = (today + timedelta(days=INTERVALS[stage])).isoformat()
        rec["review_queue"] = False
        rec.pop("recheck_due", None)
        rec.pop("recheck_reason", None)
        rec.pop("recheck_depth", None)
    else:
        rec["stage"] = 0
        rec["next_review"] = (today + timedelta(days=INTERVALS[0])).isoformat()
        rec["review_queue"] = True
    rec["last_review"] = today.isoformat()
    rec["review_count"] = (rec.get("review_count") or 0) + 1
    return rec


def start_review_clock(rec, today=None, days=None):
    """知识点首次通过时启动复习时钟。"""
    today = today or date.today()
    stage = rec.get("stage") or 0
    rec["stage"] = stage
    rec["next_review"] = (today + timedelta(days=days or INTERVALS[stage])).isoformat()
    return rec


def queue_summary(items):
    """把队列按课程汇总，便于展示。"""
    agg = {}
    for it in items:
        agg.setdefault(it["course"], []).append(it)
    return agg
