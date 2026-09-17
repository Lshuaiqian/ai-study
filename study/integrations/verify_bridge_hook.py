#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""端到端验证 study 桥接的**钩子**在真实交互循环里会不会触发。

为什么需要这个脚本
    之前只验证了 `study_bridge.py` 的 CLI（直接调 record_submission），
    但**没验证 tutor.py 的 main() 循环里那段钩子**。钩子不触发的话，
    用户正常学习时什么都不会被记录 —— 这是整个小型可测版的关键环节。

做法
    - 打桩 `agent_run`：不发网络请求，返回一段假的导师点评
    - 打桩 `check_api_key` / history 读写：不碰真实状态
    - 把 config 的 bridge.structured_gaps 置为 False：离线
    - 用 StringIO 喂 `/done` → `/study` → `/exit`，驱动真正的 main()
    - 断言：桥接输出出现、state 文件被写入、/study 能渲染今日视图

注意：会写入真实的 study/state，脚本自身负责备份与恢复。
"""
import io
import json
import os
import shutil
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

AGENT_DIR = r"E:\Agents\python-tutor"
STUDY_DIR = r"E:\Docs\Code\Java\book\study"
STATE = os.path.join(STUDY_DIR, "state")
MASTERY = os.path.join(STATE, "mastery.json")
EVENTS = os.path.join(STATE, "events.jsonl")
BACKUP = os.path.join(STATE, "_preverify")

sys.path.insert(0, AGENT_DIR)
import tutor  # noqa: E402


def snapshot():
    return {p: (os.path.getmtime(p), os.path.getsize(p))
            for p in (MASTERY, EVENTS) if os.path.exists(p)}


def restore():
    for name in ("mastery.json", "events.jsonl"):
        src = os.path.join(BACKUP, name)
        dst = os.path.join(STATE, name)
        if os.path.exists(src):
            shutil.copy2(src, dst)
    shutil.rmtree(BACKUP, ignore_errors=True)


def main():
    print("=" * 66)
    print("[准备] 备份 study/state")
    if os.path.isdir(BACKUP):
        shutil.rmtree(BACKUP)
    os.makedirs(BACKUP, exist_ok=True)
    for name in ("mastery.json", "events.jsonl"):
        src = os.path.join(STATE, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(BACKUP, name))
    before = snapshot()

    # ---------------- 打桩 ----------------
    seen_prompts = []

    def fake_agent_run(cfg, lessons, progress, user_text, history=None):
        seen_prompts.append(user_text)
        return ("【🧪 作业检查】打桩：能跑通\n"
                "【📚 知识修正】打桩：第 10 行缺 User-Agent\n"
                "【❓ 自检追问】打桩问题\n"), []

    real_load_config = tutor.load_config

    def patched_load_config():
        cfg = real_load_config()
        cfg.setdefault("bridge", {})
        cfg["bridge"]["enabled"] = True
        cfg["bridge"]["structured_gaps"] = False      # 离线：不调用模型
        return cfg

    tutor.agent_run = fake_agent_run
    tutor.check_api_key = lambda cfg: True
    tutor.save_history = lambda h: None
    tutor.load_history = lambda: []
    tutor.load_config = patched_load_config

    # ---------------- 驱动真正的 main() ----------------
    print("[执行] 用 /done → /study → /exit 驱动 tutor.main()")
    sys.stdin = io.StringIO("/done\n/study\n/exit\n")
    buf = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = buf
    try:
        tutor.main()
    except SystemExit:
        pass
    except Exception as e:  # noqa: BLE001
        sys.stdout = real_stdout
        print(f"❌ main() 抛异常：{type(e).__name__}: {e}")
        restore()
        return 1
    finally:
        sys.stdout = real_stdout
    out = buf.getvalue()

    # ---------------- 断言 ----------------
    print("\n[检查]")
    checks = []

    checks.append(("钩子把 /done 改写成验收提示词",
                   any("验收我当前课" in p for p in seen_prompts)))

    checks.append(("桥接摘要出现在输出里",
                   "study桥接" in out or "课程 py-agent-03" in out))

    checks.append(("桥接报告了 code 维度",
                   "code 维度" in out))

    checks.append(("bridge.enabled/structured_gaps 配置生效（离线未产生薄弱点）",
                   "薄弱点 （无）" in out))

    after = snapshot()
    checks.append(("mastery.json 被写入（mtime/大小变化）",
                   MASTERY in after and after.get(MASTERY) != before.get(MASTERY)))
    checks.append(("events.jsonl 被写入",
                   EVENTS in after and after.get(EVENTS) != before.get(EVENTS)))

    # 结构断言：比字符串匹配更能说明问题
    try:
        with open(MASTERY, "r", encoding="utf-8") as f:
            state = json.load(f)
        entry = (state.get("lessons") or {}).get("py-agent-03") or {}
        checks.append(("掌握度写入 code 维",
                       "code" in (entry.get("dims") or {})))
        checks.append(("显式标记 code_only（不假装四维齐全、门禁不会误判）",
                       entry.get("code_only") is True))
        checks.append(("来源标记为 python-tutor",
                       entry.get("source") == "python-tutor"))
        events = [json.loads(l) for l in
                  open(EVENTS, encoding="utf-8").read().splitlines() if l.strip()]
        checks.append(("submission 事件带 source=python-tutor",
                       any(e.get("kind") == "submission"
                           and e.get("source") == "python-tutor" for e in events)))
    except Exception as e:  # noqa: BLE001
        checks.append((f"读取 state 做结构断言（失败：{type(e).__name__}）", False))

    checks.append(("/study 渲染出今日视图",
                   "今日任务" in out and "复习" in out))

    for name, ok in checks:
        print(f"  {'✅' if ok else '❌'} {name}")

    # 展示关键片段
    print("\n[输出片段：桥接与 /study]")
    for line in out.splitlines():
        if any(k in line for k in ("study桥接", "课程 py-agent", "code 维度",
                                   "薄弱点", "机检通过率", "今日任务", "【复习",
                                   "【补练", "【课程】", "桥接事件", "还缺维度")):
            print("  " + line)

    print("\n[清理] 恢复 study/state")
    restore()
    restored = snapshot()
    ok_restore = restored == before
    print(f"  {'✅' if ok_restore else '❌'} 状态已恢复到运行前")

    passed = all(ok for _, ok in checks) and ok_restore
    print("\n" + "=" * 66)
    print(f"结论：{'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
