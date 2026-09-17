"""tutor · 代码导师：逐行点评并产出结构化 findings.json。

继承 python-tutor 的四段式教学协议（阶段 A 布置作业 / B 验收与知识修正 / C 通过验收），
但把输出**结构化为 JSON**，使点评结果能直接喂给掌握度模型——这是三个现有 Agent 都缺的一环。

四段式（渲染给用户看）：
  【🧪 作业检查】【📚 知识修正】【🔗 知识定位】【❓ 自检追问】

红线：引导而不代写。除非用户明确要答案，只给提示（fix_hint），不给完整实现。
"""
from gate.codecheck import DEFAULT_CRITERIA  # noqa: F401

REVIEW_SYSTEM = (
    "你是一位任务驱动式编程导师，学生有扎实的 C/C++ 基础（指针、STL、RAII、多线程都懂），"
    "所以**不要科普入门概念**，优先做语言对照（list≈vector、dict≈map、with≈RAII、"
    "GIL vs 真并行）。\n"
    "你的任务是审阅学生的练习代码。规则：\n"
    "1) 只根据给出的代码与运行结果说话，不要臆测未出现的代码。\n"
    "2) 每条 finding 必须**锚定具体行号**并引用该行原文。\n"
    "3) severity 取值：error（会出错或概念用错）、warn（能跑但有隐患/不 Pythonic）、"
    "style（风格）、praise（做得好的点，至少 1 条）。\n"
    "4) 【引导而不代写】fix_hint 只给方向与提示，**不要给完整实现**。\n"
    "5) knowledge_gaps 只填下面【本课知识点】里确实没掌握的知识点 id。\n"
    "6) 只有出现概念性错误理解（把概念搞反/张冠李戴）才置 fatal_misconception=true。\n"
    "必须输出 JSON：\n"
    '{"check":{"runs":true,"summary":"整体一句话评价，先肯定做得好的点"},'
    '"findings":[{"severity":"error|warn|style|praise","line":3,"code":"该行原文",'
    '"issue":"问题说明","atom_id":"K3 或 空","fix_hint":"引导性提示，不给完整答案"}],'
    '"knowledge_gaps":["K3"],'
    '"knowledge_position":{"atom_id":"K3","system_position":"该知识点在体系中的位置",'
    '"affects":["后续受影响的课程或知识点"]},'
    '"self_check_questions":["1-2 个引导性问题，让学生自己发现问题"],'
    '"fatal_misconception":false,"fatal_reason":""}'
)


def review_code(llm, curriculum, task, source, run_result=None,
                criteria_result=None, env=None):
    """审阅练习代码，返回结构化 findings。

    env：{ok, missing[], error} —— 由 runner.check_imports 提供。
    用于区分「环境缺依赖」与「学生写错了」：前者不得算作学生的错误。
    """
    knowledge = curriculum["declares"]["knowledge"]
    kp_lines = "\n".join(f"- {k['id']} [{k['level']}] {k['name']}" for k in knowledge)

    run_txt = "（未运行）"
    if run_result:
        run_txt = (f"ran={run_result.get('ran')} exit={run_result.get('exit_code')} "
                   f"timeout={run_result.get('timeout')}\n"
                   f"stdout:\n{run_result.get('stdout') or '（空）'}\n"
                   f"stderr:\n{run_result.get('stderr') or '（空）'}")

    env_txt = "（未检测）"
    if env:
        if env.get("missing"):
            env_txt = (f"⚠️ 当前环境缺少这些依赖：{'、'.join(env['missing'])}。"
                       "如果代码因此跑不通，**不要算作学生的错误**，只需提示他安装或改用标准库。")
        else:
            env_txt = "所有 import 在本环境均可解析。"

    crit_txt = "（无）"
    if criteria_result:
        crit_txt = ("已通过：" + "、".join(criteria_result.get("hits") or []) + "\n"
                    "未通过：" + ("、".join(criteria_result.get("misses") or []) or "（无）"))

    user = (
        f"【本课】{curriculum['title']}\n"
        f"【本课知识点】\n{kp_lines}\n\n"
        f"【任务】{task['title']}\n{task['brief']}\n"
        f"验收标准：{'；'.join(task.get('acceptance') or []) or '（见任务描述）'}\n\n"
        f"【依赖环境检查】\n{env_txt}\n\n"
        f"【机器检查结果】\n{crit_txt}\n\n"
        f"【运行结果】\n{run_txt}\n\n"
        f"【学生代码】\n```python\n{source}\n```\n\n"
        "请以 JSON 输出点评结果。"
    )
    return llm.chat(REVIEW_SYSTEM, user, json_mode=True, temperature=0.0)


def summarize_findings(findings):
    """统计各类 finding 数量与是否致命。"""
    items = findings.get("findings") or []
    by = {"error": [], "warn": [], "style": [], "praise": []}
    for f in items:
        by.setdefault(f.get("severity") or "warn", []).append(f)
    return {
        "counts": {k: len(v) for k, v in by.items()},
        "errors": by["error"],
        "warns": by["warn"],
        "styles": by["style"],
        "praises": by["praise"],
        "fatal": bool(findings.get("fatal_misconception")),
        "fatal_reason": findings.get("fatal_reason", ""),
        "knowledge_gaps": findings.get("knowledge_gaps") or [],
        "atom_ids": sorted({f.get("atom_id") for f in items if f.get("atom_id")}),
    }


GAP_SYSTEM = (
    "你是一个知识点掌握度判定器。给定【本课知识点】与【导师对学生作业的点评】，"
    "判断哪些知识点**尚未掌握**。判定从严：只有点评明确肯定、或能从学生代码里看出来的，"
    "才算掌握；点评没提到的一律算未掌握。\n"
    "必须输出 JSON：\n"
    '{"gaps":[{"id":"K3","reason":"一句话"}],"solid":["K1","K2"],"summary":"一句话"}'
)


def extract_knowledge_gaps(llm, curriculum, review_text, criteria_result=None):
    """从导师的**自由文本点评**里抽出结构化薄弱点。

    为什么要这一步：python-tutor 的验收结论是一段人读的散文（三段式），
    没有结构化字段。而掌握度模型与复习队列需要 `knowledge_gaps`。
    这里用一次结构化调用把它转出来——这是把"点评"变成"自省数据"的关键一环。
    """
    knowledge = curriculum["declares"]["knowledge"]
    kp_lines = "\n".join(
        f"- {k['id']} [{k.get('level', 'must')}] {k['name']}" for k in knowledge)
    crit = ""
    if criteria_result:
        crit = ("\n【机器检查通过的条件】" + "、".join(criteria_result.get("hits") or [])
                + "\n【未通过的条件】" + ("、".join(criteria_result.get("misses") or []) or "（无）"))
    user = (
        f"【本课】{curriculum.get('title', curriculum.get('course_id'))}\n"
        f"【本课知识点】\n{kp_lines}\n{crit}\n\n"
        f"【导师点评原文】\n{review_text}\n\n"
        "请以 JSON 输出判定结果。"
    )
    data = llm.chat(GAP_SYSTEM, user, json_mode=True, temperature=0.0)
    valid = {k["id"] for k in knowledge}
    gaps = [g for g in (data.get("gaps") or []) if g.get("id") in valid]
    solid = [s for s in (data.get("solid") or []) if s in valid]
    return {"gaps": gaps, "solid": solid, "summary": data.get("summary", "")}


def record(findings, task_id, run_result=None, criteria_result=None):
    """组装可落盘的 findings.json。"""
    s = summarize_findings(findings)
    return {
        "task_id": task_id,
        "ran": bool((run_result or {}).get("ran")),
        "run_result": run_result or {},
        "criteria": {
            "score": (criteria_result or {}).get("score"),
            "hits": (criteria_result or {}).get("hits") or [],
            "misses": (criteria_result or {}).get("misses") or [],
            "lines": (criteria_result or {}).get("lines"),
        },
        "check": findings.get("check") or {},
        "findings": findings.get("findings") or [],
        "counts": s["counts"],
        "knowledge_gaps": s["knowledge_gaps"],
        "atom_ids": s["atom_ids"],
        "knowledge_position": findings.get("knowledge_position") or {},
        "self_check_questions": findings.get("self_check_questions") or [],
        "fatal_misconception": s["fatal"],
        "fatal_reason": s["fatal_reason"],
    }


def render_review(rec):
    """把 findings.json 渲染成用户看的四段式文本。"""
    out = []
    chk = rec.get("check") or {}
    out.append(f"【🧪 作业检查】跑通={rec['ran']}  " + (chk.get("summary") or ""))
    if rec.get("run_result", {}).get("stderr"):
        err = rec["run_result"]["stderr"].strip().splitlines()
        if err:
            out.append(f"    运行输出：{err[-1][:100]}")

    out.append("【📚 知识修正】")
    for f in rec.get("findings") or []:
        sev = f.get("severity")
        mark = {"error": "❌", "warn": "⚠️", "style": "🎨", "praise": "✅"}.get(sev, "•")
        loc = f"第 {f.get('line')} 行" if f.get("line") else "整体"
        out.append(f"    {mark} [{loc}] {str(f.get('code'))[:44]}")
        out.append(f"       {f.get('issue')}")
        if f.get("fix_hint"):
            out.append(f"       → 提示：{f['fix_hint']}")
    if not rec.get("findings"):
        out.append("    （无）")

    pos = rec.get("knowledge_position") or {}
    if pos:
        out.append(f"【🔗 知识定位】{pos.get('atom_id') or ''} "
                   f"{pos.get('system_position') or ''}")
        if pos.get("affects"):
            out.append(f"    影响：{'、'.join(pos['affects'])}")

    if rec.get("self_check_questions"):
        out.append("【❓ 自检追问】")
        for q in rec["self_check_questions"]:
            out.append(f"    - {q}")

    if rec.get("knowledge_gaps"):
        out.append(f"【📉 薄弱点】{'、'.join(rec['knowledge_gaps'])} —— 已挂复习队列")
    if rec.get("fatal_misconception"):
        out.append(f"【⛔ 致命误解】{rec.get('fatal_reason')}（不允许带疑点前进）")
    return "\n".join(out)
