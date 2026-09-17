#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Planner 视图：今日任务 + 自省周报。

用法：
    E:\\Develop\\python\\python.exe study\\tools\\plan.py
    E:\\Develop\\python\\python.exe study\\tools\\plan.py --today 2026-09-20
    E:\\Develop\\python\\python.exe study\\tools\\plan.py --week-start 2026-09-14
"""
import io
import os
import sys
from datetime import date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.store import read_json                                      # noqa: E402
from graph import build, load_curriculums, load_route                 # noqa: E402
from plan import daily_view, read_events, weekly_report               # noqa: E402


def _date_arg(argv, name):
    if name in argv:
        try:
            return date.fromisoformat(argv[argv.index(name) + 1])
        except (ValueError, IndexError):
            print(f"[警告] {name} 参数无法解析，已忽略")
    return None


def main():
    argv = sys.argv[1:]
    today = _date_arg(argv, "--today")
    week_start = _date_arg(argv, "--week-start")

    graph = build(load_route(os.path.join(BASE, "route.json")),
                  load_curriculums(os.path.join(BASE, "curriculum")))
    state = read_json(os.path.join(BASE, "state", "mastery.json"), default={})
    events = read_events(os.path.join(BASE, "state", "events.jsonl"))

    print(daily_view(graph, state, today=today))
    print()
    print(weekly_report(events, graph, state, week_start=week_start, today=today))
    print()
    print(f"[事件日志 {len(events)} 条] {os.path.join('state', 'events.jsonl')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
