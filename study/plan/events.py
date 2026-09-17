"""plan · 事件日志（自省机制的数据底座）。

为什么需要它：`mastery.json` 只存"当前状态"，答不了"这一周我干了什么、
掌握度涨了多少、卡在哪一步"。自省机制要的是一段时间序列，所以每次动作都记一条事件。

append-only JSONL，坏了也不影响主状态；可随时删除重建。
"""
import json
import os
from datetime import datetime

KINDS = {
    "course_started",   # {course_id}
    "submission",       # {course_id, mastery, passed, lines, dims}
    "passed",           # {course_id, mastery, attempts}
    "carried_over",     # {course_id, points[]}
    "reflow",           # {atom, before, after}
    "recheck",          # {atom, depth, via}
    "note_review",      # {course_id, note_score, parts{}, source} 笔记体检/一键整理
    "interrogation",    # {course_id, percent, can_skip, parts{}} AI 质询结论
    "review_done",      # {atom, success, stage}
    "blocked_entry",    # {course_id, missing[]}
}


def append_event(path, kind, **payload):
    if kind not in KINDS:
        raise ValueError(f"未定义的事件类型: {kind}")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "kind": kind}
    rec.update(payload)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def read_events(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue          # 坏行跳过，不让日志阻塞主流程
    return out


def filter_range(events, start, end):
    """按 ISO 时间串闭开区间过滤 —— 避免引入时区依赖，直接比较字符串前缀。"""
    s, e = start.isoformat(), end.isoformat()
    return [ev for ev in events if s <= (ev.get("ts") or "") < e]
