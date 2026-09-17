#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P0 单课掌握闭环 · 端到端运行器（真实闭环版）。

跑通 S4 全流程（docs/AI辅助学习-App-系统设计（融合版）.md §3）：
    声明知识点 → 布置任务 → 跑代码 → 代码点评改正 → 笔记加工与指错
    → 四维掌握度门禁 → 未过则 L1/L2/L3 或逃生阀 → 通过则下一课

用法：
    E:\\Develop\\python\\python.exe study\\p0_demo.py [--no-run]
"""
import io
import os
import sys
import tempfile
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import load_config                              # noqa: E402
from core.llm import LLM                                         # noqa: E402
from core.store import read_json, read_text, write_json          # noqa: E402
from gate import (carry_over, evaluate, next_action, reflow,     # noqa: E402
                  score_transfer)
from gate.codecheck import analyze, combine_code_dimension, count_effective_lines  # noqa: E402
from gate.rubric import judge_self_check                         # noqa: E402
from flow import entry_check                                     # noqa: E402
from graph import (build, cascade_recheck, kp_id, load_curriculums,  # noqa: E402
                   load_route)
from library import as_materials, load_atoms                      # noqa: E402
from notedoctor import diagnose, render_report                   # noqa: E402
from plan import append_event, start_review_clock                # noqa: E402
from tutor import (check_imports, check_syntax, record,          # noqa: E402
                   render_review, review_code, run_file)

BASE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(BASE, "demo")
# 这三个默认指向**沙箱**，由 main() 在运行时设定（见那里的说明）。
# 不要把它们写死成 BASE/state——演示会删 events.jsonl 并写合成结果。
STATE_DIR = os.path.join(BASE, "state")
RUN_DIR = STATE_DIR
FINDINGS_DIR = STATE_DIR
STATE = STATE_DIR
LIBRARY_PATH = os.path.join(BASE, "library", "atoms.jsonl")
ALLOWED = [DEMO, RUN_DIR]

NO_RUN = "--no-run" in sys.argv


def rule(ch="-", n=78):
    print(ch * n)


def task_of(curriculum, task_type, exclude=None):
    for t in curriculum["tasks"]:
        if t["type"] == task_type and t["task_id"] != exclude:
            return t
    return None


# ---------------- ① 声明知识点 ----------------

def render_declares(c):
    d = c["declares"]
    rule("=")
    print(f"📚 {c['title']}")
    print(f"🎯 {c['goal']}")
    rule()
    must = [k for k in d["knowledge"] if k["level"] == "must"]
    should = [k for k in d["knowledge"] if k["level"] != "must"]
    print(f"本课知识点（{len(must)} 个必会 / {len(should)} 个了解）")
    for k in must:
        print(f"   ├─ [必会] {k['id']} {k['name']}")
    for k in should:
        print(f"   └─ [了解] {k['id']} {k['name']}")
    print()
    for p in d["prerequisites"]:
        print(f"   ← 前置：{p['course_id']} {p['name']}")
    print(f"   🔗 体系位置：{d['system_position']}")
    for u in d["unlocks"]:
        print(f"   ⬇ 解锁：{u['course_id']} {u['name']}")
    print("\n任务：")
    for t in c["tasks"]:
        print(f"   [{t['type']:8s}] {t['task_id']}  {t['title']}  (~{t['est_minutes']}min)")
    rule("=")


# ---------------- 代码：环境 / 语法 / 运行 / 机检 / 点评 ----------------

def prepare_code(cfg, curriculum, main_file, cache=None):
    """对主练习文件做环境+语法检查，可选真实运行。返回 (env, syn, run_res, criteria)。"""
    path = os.path.join(DEMO, main_file)
    env = check_imports(path, ALLOWED)
    syn = check_syntax(path, ALLOWED)

    run_res = {"ran": False, "stdout": "", "stderr": "（未运行）", "exit_code": None,
               "timeout": False}
    if not NO_RUN and syn["ok"]:
        if cache is not None and "run" in cache:
            run_res = cache["run"]
            print(f"   运行（复用上次结果）：{run_res['stdout'].strip().splitlines()[-1:]}")
        else:
            os.makedirs(RUN_DIR, exist_ok=True)
            print("   正在真实运行练习代码 ...")
            t0 = time.time()
            run_res = run_file(path, ALLOWED, timeout=40, cwd=RUN_DIR)
            print(f"   ran={run_res['ran']} exit={run_res['exit_code']} "
                  f"耗时 {time.time()-t0:.1f}s")
            if cache is not None:
                cache["run"] = run_res

    print(f"   环境依赖：{'缺 ' + '、'.join(env['missing']) if env['missing'] else '齐全'}"
          f" | 语法：{'OK' if syn['ok'] else syn['error']}")
    return env, syn, run_res


def code_step(llm, curriculum, curriculum_task, source_files, env, run_res, cache=None):
    source = "\n\n# " + "-" * 60 + "\n".join(
        f"# ==== {f} ====\n" + read_text(os.path.join(DEMO, f)) for f in source_files)
    lines = count_effective_lines(source)
    criteria = analyze(source)
    criteria["lines"] = lines

    review = review_code(llm, curriculum, curriculum_task,
                         read_text(os.path.join(DEMO, source_files[0])),
                         run_result=run_res, criteria_result=criteria, env=env)
    rec = record(review, curriculum_task["task_id"], run_res, criteria)
    write_json(os.path.join(FINDINGS_DIR, f"{curriculum_task['task_id']}.json"), rec)
    dim = combine_code_dimension(criteria["score"], rec["counts"])
    return criteria, rec, dim, lines


# ---------------- 单轮评估 ----------------

def run_scenario(llm, curriculum, label, note_file, source_files, answers,
                 transfer=None, env=None, run_res=None, cache=None):
    print(f"\n{'#' * 78}\n# 场景：{label}\n{'#' * 78}")

    task_code = task_of(curriculum, "code")
    print(f"\n[代码] {task_code['task_id']} {task_code['title']}")
    criteria, rec, code_dim, lines = code_step(
        llm, curriculum, task_code, source_files, env, run_res, cache)
    print(f"   机检 {len(criteria['hits'])}/{len(criteria['hits'])+len(criteria['misses'])}"
          f" | 有效行 {lines} | findings {rec['counts']}")
    print()
    print(render_review(rec))

    print("\n[自检判分] ...")
    quiz_res = judge_self_check(llm, curriculum, answers)
    for qid, r in quiz_res["per_question"].items():
        print(f"   {qid}: {r['score']:.4f} {r.get('verdicts', '')}  {r.get('comment', '')}")

    print("\n[笔记体检] ...")
    # 只用【权威】原子作判错依据：从学生自己笔记抽出的 derived 原子
    # 不能反过来判定他的笔记有错（循环论证）。
    lib_atoms = as_materials(load_atoms(LIBRARY_PATH),
                             course_id=curriculum["course_id"],
                             authoritative_only=True)
    print(f"   证据来源：学习库 {len(lib_atoms)} 个权威已确认原子"
          f"（{os.path.relpath(LIBRARY_PATH, BASE)}）")
    note_res = diagnose(llm, curriculum, read_text(os.path.join(DEMO, note_file)),
                        atoms=lib_atoms)
    print(render_report(note_res, curriculum))

    # transfer
    transfer_res, transfer_score = None, 0.0
    if transfer:
        print("\n[迁移题评分] ...")
        task_tf = task_of(curriculum, "transfer")
        transfer_res = score_transfer(
            llm, task_tf, read_text(os.path.join(DEMO, transfer["artifact"])),
            read_text(os.path.join(DEMO, transfer["explanation"])))
        transfer_score = transfer_res["score"]
        print(f"   {transfer_res['verdicts']}  → {transfer_score:.4f}")
        print(f"   {transfer_res['comment']}")
    else:
        print("\n[迁移题] 未提交")

    dims = {"code": code_dim["score"], "quiz": quiz_res["score"],
            "note": note_res["note_score"], "transfer": transfer_score}
    fatal = bool(quiz_res["fatal"] or note_res["fatals"] or rec["fatal_misconception"])
    fatal_reasons = quiz_res["fatal_reasons"] + note_res["fatals"]
    if rec["fatal_misconception"]:
        fatal_reasons.append(f"代码点评: {rec['fatal_reason']}")

    result = evaluate(dims, curriculum["gate"], fatal=fatal,
                      must_cover_ratio=note_res["coverage"]["must_cover_ratio"],
                      practice_lines=lines)

    print()
    rule("=")
    print("【四维得分】")
    for k, v in dims.items():
        ok = "✅" if v >= curriculum["gate"]["min_each"] else f"❌ <{curriculum['gate']['min_each']}"
        print(f"   {k:9s} {v:.4f}   {ok}")
    print(f"   {'mastery':9s} {result['mastery']:.4f}   门槛 {curriculum['gate']['min_mastery']}")
    print(f"\n【门禁判定】{'✅ 通过' if result['passed'] else '❌ 未通过'}")
    for f in result["failures"]:
        print(f"   - {f}")
    for fr in fatal_reasons:
        print(f"   ⛔ {fr}")

    out = {"scenario": label, "dims": dims, "mastery": result["mastery"],
           "passed": result["passed"], "failures": result["failures"],
           "code_detail": code_dim, "knowledge_gaps": rec["knowledge_gaps"],
           "lines": lines, "note_parts": note_res["parts"],
           "note_score": note_res["note_score"]}

    if not result["passed"]:
        act = next_action(result, attempt=1)
        print(f"\n【下一步】{act['level']}：{act['detail']}")
        print(f"   可带疑点前进：{'是' if result['carry_allowed'] else '否（存在致命误解）'}")
        out["next_action"] = act
        out["carry_allowed"] = result["carry_allowed"]

    rule("=")
    return out, rec


def seed_prerequisites(state):
    """按用户真实进度补齐前置课程。

    依据：E:\\Agents\\python-tutor\\progress.json → current_lesson=3、lessons_done={1,2}。
    不补的话准入门禁会（正确地）拒绝开第 3 课——单课演示确实跳过了前置。
    """
    for cid, mast in (("py-agent-01", 0.91), ("py-agent-02", 0.89)):
        state.setdefault("lessons", {})[cid] = {
            "mastery": mast, "passed": True,
            "source": "E:\\Agents\\python-tutor\\progress.json"}
        for kp in ("K1", "K2", "K3", "K4", "K5"):
            state.setdefault("atoms", {})[f"{cid}:{kp}"] = {
                "mastery": 0.88, "passed": True}
    return state


def main():
    # 状态目录必须先定下来，再碰任何跟状态有关的路径。
    # global 要放在本函数**第一次读到** STATE_DIR 之前，否则 Python 直接语法错。
    global STATE_DIR, RUN_DIR, FINDINGS_DIR, STATE
    if "--keep-state" in sys.argv:
        print("[状态] ⚠️ --keep-state：本次演示会**写真实的 state/**，"
              "包括重置 mastery.json 与删除 events.jsonl")
    else:
        # 默认沙箱：真实 state/ 一个字节都不动。
        # 原行为是直接重置 mastery.json 并**删掉 events.jsonl** 再写演示结果——
        # events.jsonl 是自省与周报的数据底座，删它等于抹掉使用者的真实学习历史。
        sandbox = tempfile.mkdtemp(prefix="p0demo-state-")
        STATE_DIR = sandbox
        RUN_DIR = os.path.join(sandbox, "run")
        FINDINGS_DIR = os.path.join(sandbox, "findings")
        STATE = os.path.join(sandbox, "mastery.json")
        os.makedirs(RUN_DIR, exist_ok=True)
        os.makedirs(FINDINGS_DIR, exist_ok=True)
        print(f"[状态] 沙箱模式：状态写在 {sandbox}，真实 state/ 不受影响"
              f"（加 --keep-state 才会写真实状态）")

    cfg = load_config()
    curriculum = read_json(os.path.join(BASE, "curriculum", "py_agent_03.json"))
    llm = LLM(cfg)
    os.makedirs(FINDINGS_DIR, exist_ok=True)

    graph = build(load_route(os.path.join(BASE, "route.json")),
                  load_curriculums(os.path.join(BASE, "curriculum")))
    events_path = os.path.join(STATE_DIR, "events.jsonl")

    # 演示默认从干净状态开始（这是可重复的验证流程）。
    # 注意：不重置的话，第二次运行会被准入门禁正确拦下——
    # 因为 py-agent-03 已通过，而"已通过的课不允许直接重进"是刻意设计。
    if "--keep-state" in sys.argv:
        state = read_json(STATE, default={"atoms": {}, "lessons": {}})
    else:
        state = {"atoms": {}, "lessons": {}}
    state = seed_prerequisites(state)

    print(f"模型 {cfg['model']} | 思考 {'开' if cfg['thinking'] else '关'} | "
          f"temperature 0 | JSON Output | 真实运行={not NO_RUN}")
    render_declares(curriculum)

    # ---------------- 准入门禁（开课之前）----------------
    check = entry_check(graph, state, "py-agent-03")
    print(f"\n[准入门禁] {check['status']}｜{check['reason']}")
    if check["blocked_points"]:
        print(f"           被挡住的知识点：{check['blocked_points']}")
    if not check["allowed"]:
        append_event(events_path, "blocked_entry", course_id="py-agent-03",
                     missing=check["missing_prerequisites"])
        print("不予开课，已记录 blocked_entry 事件。")
        return 1
    append_event(events_path, "course_started", course_id="py-agent-03")

    answers = read_json(os.path.join(DEMO, "lesson3_answers.json"))
    cache = {}

    print("\n[准备] 主练习文件环境/语法/运行检查")
    env, syn, run_res = prepare_code(cfg, curriculum, "west2_spider.py", cache)

    a, rec_a = run_scenario(
        llm, curriculum, "A · 首次提交（预期未通过）",
        note_file="lesson3_note.md",
        source_files=["west2_spider.py"],
        answers=answers, transfer=None, env=env, run_res=run_res, cache=cache)
    for sc in (a,):
        append_event(events_path, "submission", course_id="py-agent-03",
                     mastery=sc["mastery"], passed=sc["passed"], lines=sc["lines"],
                     dims=sc["dims"])
        append_event(events_path, "note_review", course_id="py-agent-03",
                     note_score=sc["note_score"], parts=sc["note_parts"])

    b, rec_b = run_scenario(
        llm, curriculum, "B · L1 补练后重新提交（预期通过）",
        note_file="lesson3_note_fixed.md",
        source_files=["west2_spider.py", "t_py03_3_spider.py"],
        answers=answers,
        transfer={"artifact": "t_py03_3_spider.py",
                  "explanation": "lesson3_transfer_note.md"},
        env=env, run_res=run_res, cache=cache)
    for sc in (b,):
        append_event(events_path, "submission", course_id="py-agent-03",
                     mastery=sc["mastery"], passed=sc["passed"], lines=sc["lines"],
                     dims=sc["dims"])
        append_event(events_path, "note_review", course_id="py-agent-03",
                     note_score=sc["note_score"], parts=sc["note_parts"])
    if b["passed"]:
        append_event(events_path, "passed", course_id="py-agent-03",
                     mastery=b["mastery"], attempts=2)

    # ---------------- 状态持久化 + 回炉 ----------------
    state["lessons"]["py-agent-03"] = {
        "mastery": b["mastery"], "passed": b["passed"], "dims": b["dims"],
        "attempts": 2, "practice_lines": b["lines"],
        "first_submit": {"mastery": a["mastery"], "failures": a["failures"]},
    }
    # 通过后把本课必会知识点落进掌握度并启动复习时钟（Planner 的数据来源）
    if b["passed"]:
        for kp in curriculum["declares"]["knowledge"]:
            if kp["level"] != "must":
                continue
            rec_kp = state["atoms"].setdefault(kp_id("py-agent-03", kp["id"]), {})
            rec_kp.update({"mastery": b["mastery"], "passed": True,
                           "course": "py-agent-03", "source": "course_pass"})
            start_review_clock(rec_kp)
    gaps = sorted(set(b["knowledge_gaps"]))

    # 回炉演示：第 3 课的点评命中了 429 分支处理不当（见 findings 第 78 行那条 warn），
    # 判定为第 2 课的「HTTP 状态码语义」没吃透 → 打折已通过的前置知识点并重回复习队列。
    # 注意 reflow 只对【已通过】的原子生效，所以本课尚未通过的 K3 不受影响。
    reflow_targets = ["py-agent-02:K1"]
    changes = reflow(state, reflow_targets)
    # 回炉的级联影响：K2/K4 依赖 K1，它们不该被连带打回（用户确实通过过），
    # 但要标成"待复查"——否则状态与体系图会自相矛盾。
    rechecked = cascade_recheck(graph, state, reflow_targets)
    for ch in changes:
        append_event(events_path, "reflow", atom=ch["atom_id"],
                     before=ch["before"], after=ch["after"])
    for rc in rechecked:
        append_event(events_path, "recheck", atom=rc["id"],
                     depth=rc["depth"], via=rc["via"])
    write_json(STATE, state)

    print(f"\n{'#' * 78}\n# 状态 · 薄弱点 · 回炉\n{'#' * 78}")
    print(f"已写入 {STATE}")
    print(f"课程 py-agent-03：mastery {b['mastery']:.4f} passed={b['passed']}"
          f"（首次提交 {a['mastery']:.4f}）")
    print(f"代码点评暴露的薄弱点：{gaps or '（无）'}")
    for ch in changes:
        print(f"回炉：{ch['atom_id']} 掌握度 {ch['before']} → {ch['after']}，已挂复习队列")
    for rc in rechecked:
        print(f"   ↳ 级联待复查（depth {rc['depth']}）：{rc['id']}"
              f"（因 {rc['via']} 被回炉）—— 不翻转已通过状态")

    print()
    rule("=")
    print(llm.report())
    rule("=")
    ok = (not a["passed"]) and b["passed"]
    print(f"演示结论：A {'通过' if a['passed'] else '未通过'} → "
          f"B {'通过' if b['passed'] else '未通过'}　（预期：A 未通过、B 通过）")
    print(f"最终判定：{'PASS' if ok else 'CHECK'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
