"""notedoctor · 一键整理：AI 对笔记质询 + 查缺补漏 + 达成度百分比。

与 §8 的「笔记体检」的区别
    体检（doctor.py）回答"这条笔记写得对不对、全不全"。
    一键整理（本模块）回答的是**"这一课我到底学到位没有，能不能过"**：
      - 覆盖率：确定性关键词匹配（不交给模型）
      - 掌握判定：对每个知识点判 pass / partial / missing
      - 质询：针对薄弱与缺失**提问**，逼你自己补上，而不是直接给答案
      - 作业进度：从笔记里的 `- [ ]` 勾选状态统计
      - 达成度：加权成一个百分比，够线就提示"可以跳过进下一课"（由你决定）

设计原则
    - 覆盖率与作业进度**必须确定性**，模型只负责语义判断
    - 纠错必须带出处；无依据只能标"待确认"（沿用 D7）
    - 质询是「提问」不是「讲解」——除非你明确要答案
"""
import os
import re
from datetime import datetime

from gate.mastery import WEIGHTS  # noqa: F401  （保持与本项目其它模块一致的引用习惯）
from notedoctor.doctor import check_coverage
from notedoctor.tidier import (AI_HEADING, AI_START, HISTORY_HEADING,
                               QUIZ_HEADING, QUIZ_START)

# 「我的笔记」区的右边界：撞到任何一个都不能再往下取。
# 质询区也算：那是 AI 的提问清单，不是学生写的笔记。
AI_BOUNDARIES = (AI_HEADING, AI_START, QUIZ_HEADING, QUIZ_START, HISTORY_HEADING)

# 达成度权重：覆盖率与掌握判定各 0.4，作业进度 0.2
SCORE_WEIGHTS = {"coverage": 0.4, "mastery": 0.4, "tasks": 0.2}
DEFAULT_SKIP_THRESHOLD = 0.70

NOTES_HEADING = "✍️ 我的笔记"

VERDICT_SCORE = {"pass": 1.0, "partial": 0.5, "missing": 0.0}

INTERROGATE_SYSTEM = (
    "你是一个严格的课程验收官兼质询者。学生会给你他在某节课写的笔记。\n"
    "你的任务**不是讲解**，而是判断他是否真的学到位，并**提出追问**。\n"
    "规则：\n"
    "1) 对每个【本课知识点】给出 verdict：pass（用自己的话说清且正确）、"
    "partial（提到但不完整/偏浅）、missing（没提或说错）。\n"
    "2) 每个非 pass 的知识点，给 1 个**苏格拉底式追问**，逼他说出原理、"
    "边界条件或对比，**不要直接给答案**。\n"
    "3) 指出事实性错误时**必须引用资料依据**；若没有依据，只能放进 "
    "uncertain 而不是 errors。\n"
    "4) 检查他的作业记录是否覆盖了【作业清单】；没做的列进 todo。\n"
    "必须输出 JSON：\n"
    '{"verdicts":[{"id":"K1","verdict":"pass|partial|missing","why":"一句话"}],'
    '"questions":[{"for":"K1","question":"追问"}],'
    '"errors":[{"quote":"原句","reason":"说明","source_ref":"M3 或 空"}],'
    '"uncertain":[{"quote":"原句","reason":"为什么存疑"}],'
    '"todo":["还没做的作业或还没写的点"],'
    '"summary":"两三句话总评（先肯定，再指出最该补的）"}'
)


# ---------------------------------------------------------------- 拆解笔记

def split_note(text):
    """把课程笔记拆成 (考核要求部分, 我的笔记部分)。

    「我的笔记」必须**截到 AI 整理区之前**：整理稿是 AI 写的，
    把它当成学生自己的笔记去质询、去算覆盖率，等于 **AI 给自己打分**——
    整理一次覆盖率就冲到 100%，掌握度随之虚高。
    """
    idx = text.find(NOTES_HEADING)
    if idx < 0:
        return text, ""
    line_end = text.find("\n", idx)
    req_end = line_end + 1 if line_end > 0 else len(text)
    notes = text[req_end:]
    cut = len(notes)
    for marker in AI_BOUNDARIES:
        p = notes.find(marker)
        if p >= 0:
            cut = min(cut, p)
    # 与 AI 区之间那条结构分隔线也不算学生写的内容
    notes = re.sub(r"(?:\n[ \t]*-{3,}[ \t]*)+\s*$", "", notes[:cut])
    return text[:req_end], notes.strip("\n")


def task_progress(requirements_text):
    """从「作业清单」里的 `- [ ]` / `- [x]` 统计进度。"""
    items = []
    in_tasks = False
    for line in (requirements_text or "").splitlines():
        if line.strip().startswith("### 作业清单"):
            in_tasks = True
            continue
        if in_tasks and line.strip().startswith("### "):
            break
        if not in_tasks:
            continue
        m = re.match(r"^\s*-\s*\[([ xX])\]\s*(.+?)\s*$", line)
        if m:
            items.append({"done": m.group(1).lower() == "x", "text": m.group(2).strip()})
    done = sum(1 for i in items if i["done"])
    return {"items": items, "done": done, "total": len(items),
            "ratio": round(done / len(items), 4) if items else 0.0}


def knowledge_points(curriculum):
    """本课知识点（含 keywords，供确定性覆盖度使用）。"""
    return curriculum["declares"]["knowledge"]


# ---------------------------------------------------------------- 上一轮整理的缺口

def prior_gaps(state_dir, course_id):
    """读取上一轮「一键整理」留下的缺口 —— 这就是整理结果**反馈给 AI** 的入口。

    没有它，整理出的缺口只活在终端输出里，滚动一下就没了；
    有了它，下一次质询会**优先追问**这些点，形成「整理 → 质询 → 掌握度」的闭环。

    返回 None 表示这节课还没整理过。
    """
    from core.store import read_json
    path = os.path.join(state_dir, "findings", f"{course_id}-tidy.json")
    data = read_json(path, default=None)
    if not data:
        return None
    gaps = [c for c in (data.get("coverage") or []) if c.get("status") != "covered"]
    return {
        "path": path,
        "tidied_at": data.get("tidied_at", ""),
        "coverage_ratio": data.get("coverage_ratio"),
        "gaps": [{"id": c.get("id"), "status": c.get("status"),
                  "why": c.get("why", "")} for c in gaps],
        "todo": data.get("todo") or [],
        "uncertain": data.get("uncertain") or [],
        "summary": data.get("summary", ""),
    }


def render_prior(prior):
    """把缺口块拼进质询提示词；没有历史就返回空串（保持原行为）。"""
    if not prior or not (prior["gaps"] or prior["todo"]):
        return ""
    lines = ["【上一轮一键整理的缺口 —— 请**优先**追问这些】"]
    for g in prior["gaps"]:
        lines.append(f"- {g['id']}（{g['status']}）：{g['why']}")
    if prior["todo"]:
        lines.append("【上一轮留下的待办】")
        lines += [f"- {t}" for t in prior["todo"]]
    if prior["uncertain"]:
        lines.append("【上一轮标为存疑的句子（请判断这次是否讲清了）】")
        lines += [f"- 「{(u.get('quote') or '')[:60]}」" for u in prior["uncertain"]]
    lines.append("注意：上一轮整理只是**参考**。这次仍按学生当前的笔记独立判断；"
                 "若他这次依然没讲清，照旧判 partial/missing，不要因为整理时提过就放行。")
    return "\n".join(lines) + "\n\n"


# ---------------------------------------------------------------- 达成度

def mastery_ratio(verdicts):
    if not verdicts:
        return 0.0
    total = sum(VERDICT_SCORE.get(v.get("verdict"), 0.0) for v in verdicts)
    return round(total / len(verdicts), 4)


def score(curriculum, notes_text, interrogation, progress):
    """加权达成度。返回 {percent, parts, level, can_skip, blockers}。"""
    cov = check_coverage(curriculum["declares"], notes_text)
    parts = {
        "coverage": cov["must_cover_ratio"],
        "mastery": mastery_ratio(interrogation.get("verdicts") or []),
        "tasks": progress["ratio"],
    }
    percent = round(sum(SCORE_WEIGHTS[k] * v for k, v in parts.items()), 4)

    errors = interrogation.get("errors") or []
    fatal = [e for e in errors if (e.get("source_ref") or "").strip()]
    blockers = []
    if cov["must_missing"]:
        blockers.append("必会知识点未覆盖：" + "、".join(cov["must_missing"]))
    if fatal:
        blockers.append(f"有依据明确的错误 {len(fatal)} 处")

    threshold = DEFAULT_SKIP_THRESHOLD
    lvl = ("已达标" if percent >= threshold and not blockers else
           "接近达标" if percent >= threshold - 0.15 else "差距较大")
    return {
        "percent": percent,
        "parts": parts,
        "coverage_detail": cov,
        "level": lvl,
        "threshold": threshold,
        "can_skip": percent >= threshold and not blockers,
        "blockers": blockers,
    }


# ---------------------------------------------------------------- AI 质询

def interrogate(llm, curriculum, notes_text, progress, prior=None):
    """一次结构化质询调用。失败时返回空结构（不阻塞覆盖率与百分比）。

    prior 是上一轮一键整理的缺口（见 prior_gaps）——**这一步就是"反馈给 AI"**。
    """
    kp = knowledge_points(curriculum)
    kp_lines = "\n".join(f"- {k['id']} [{k['level']}] {k['name']}" for k in kp)
    task_lines = "\n".join(
        f"- [{'x' if i['done'] else ' '}] {i['text']}" for i in progress["items"]) or "（无）"
    user = (
        f"【本课】{curriculum.get('title')}\n"
        f"【本课知识点】\n{kp_lines}\n\n"
        + render_prior(prior)
        + f"【作业清单与勾选状态】\n{task_lines}\n\n"
        f"【学生的笔记正文】\n{notes_text or '（还没写）'}\n\n"
        "请以 JSON 输出质询结果。"
    )
    data = llm.chat(INTERROGATE_SYSTEM, user, json_mode=True, temperature=0.0)
    valid = {k["id"] for k in kp}
    verdicts = [v for v in (data.get("verdicts") or []) if v.get("id") in valid]
    return {
        "verdicts": verdicts,
        "questions": data.get("questions") or [],
        "errors": data.get("errors") or [],
        "uncertain": data.get("uncertain") or [],
        "todo": data.get("todo") or [],
        "summary": data.get("summary", ""),
    }


def empty_interrogation():
    return {"verdicts": [], "questions": [], "errors": [], "uncertain": [],
            "todo": [], "summary": "（离线模式：未做语义质询）"}


# ---------------------------------------------------------------- 反馈进掌握度

def verdict_gaps(course_id, interrogation):
    """非 pass 的判定 → [(atom_key, why)]（纯函数）。"""
    out = []
    for v in interrogation.get("verdicts") or []:
        if v.get("verdict") == "pass":
            continue
        out.append((f"{course_id}:{v.get('id')}", v.get("why", "")))
    return out


def build_payload(course_id, note_id, result, interrogation):
    """质询结论 → 掌握度可读的载荷（纯函数）。"""
    return {
        "source": "note-interrogate",
        "course_id": course_id,
        "note_id": note_id,
        "interrogated_at": datetime.now().isoformat(timespec="seconds"),
        "percent": result["percent"],
        "level": result["level"],
        "can_skip": result["can_skip"],
        "threshold": result["threshold"],
        "parts": result["parts"],
        "coverage_detail": result["coverage_detail"],
        "blockers": result["blockers"],
        "verdicts": interrogation.get("verdicts") or [],
        "questions": interrogation.get("questions") or [],
        "errors": interrogation.get("errors") or [],
        "uncertain": interrogation.get("uncertain") or [],
        "todo": interrogation.get("todo") or [],
        "summary": interrogation.get("summary", ""),
    }


def write_state(state_dir, course_id, note_id, result, interrogation,
                protected=None):
    """把质询结论反馈进掌握度——与整理共用「没说到 ≠ 没掌握」这一条规矩。

    写三样：findings（给下一次整理/质询看）、atoms（缺口进补练与复习队列）、
    events（时间线）。**不在 lessons 上重算 passed**：判定是 gate 的事。
    """
    from core.store import read_json, write_json
    from notedoctor.tidier import apply_gaps
    from plan.events import append_event

    payload = build_payload(course_id, note_id, result, interrogation)
    findings_dir = os.path.join(state_dir, "findings")
    os.makedirs(findings_dir, exist_ok=True)
    write_json(os.path.join(findings_dir, f"{course_id}-interrogate.json"), payload)

    state_path = os.path.join(state_dir, "mastery.json")
    state = read_json(state_path, default={"atoms": {}, "lessons": {}})
    atoms = state.setdefault("atoms", {})
    queued = apply_gaps(atoms, course_id, verdict_gaps(course_id, interrogation),
                        source="note-interrogate", protected=protected)

    entry = state.setdefault("lessons", {}).get(course_id) or {}
    entry.update({
        "last_interrogation": payload["interrogated_at"],
        "interrogation_percent": payload["percent"],
        "interrogation_level": payload["level"],
        "can_skip": payload["can_skip"],
        "blockers": payload["blockers"],
    })
    state["lessons"][course_id] = entry
    write_json(state_path, state)

    append_event(os.path.join(state_dir, "events.jsonl"), "interrogation",
                 course_id=course_id, percent=payload["percent"],
                 can_skip=payload["can_skip"],
                 parts=payload["parts"])
    return payload, queued


# ---------------------------------------------------------------- 报告

def render_report(curriculum, result, interrogation, progress):
    cov = result["coverage_detail"]
    p = result["parts"]
    kp_name = {k["id"]: k["name"] for k in knowledge_points(curriculum)}

    L = [f"📝 一键整理 · {curriculum['title']}", "=" * 62, ""]
    L.append(f"## 达成度 {result['percent']:.0%}　（{result['level']}｜"
             f"跳过线 {result['threshold']:.0%}）")
    L.append("")
    L.append(f"- 知识点覆盖（确定性） {p['coverage']:.0%}"
             f"　必会 {len(cov['must_covered'])}/{len(cov['must_ids'])}")
    L.append(f"- 掌握判定（AI 逐点）   {p['mastery']:.0%}")
    L.append(f"- 作业进度（勾选）       {p['tasks']:.0%}"
             f"　{progress['done']}/{progress['total']}")
    L.append("")

    if result["can_skip"]:
        L.append(f"✅ **已达标，可以选择跳过直接进下一课**（由你决定）。")
    else:
        L.append("⛔ **暂不建议跳过**：")
        for b in result["blockers"]:
            L.append(f"   - {b}")
    L.append("")

    if cov["must_missing"]:
        L.append("## 必会知识点还没覆盖")
        L.append("")
        for kid in cov["must_missing"]:
            L.append(f"- `{kid}` {kp_name.get(kid, '')}")
        L.append("")

    verdicts = interrogation.get("verdicts") or []
    if verdicts:
        L.append("## 逐点掌握判定")
        L.append("")
        for v in verdicts:
            mark = {"pass": "✅", "partial": "🟡", "missing": "⚪"}.get(v.get("verdict"), "•")
            L.append(f"- {mark} `{v.get('id')}` {kp_name.get(v.get('id'), '')}"
                     f"　{v.get('why', '')}")
        L.append("")

    if interrogation.get("questions"):
        L.append("## ❓ 质询（请先自己回答，再回来看）")
        L.append("")
        for q in interrogation["questions"]:
            target = kp_name.get(q.get("for"), q.get("for", ""))
            L.append(f"- **[{target}]** {q.get('question')}")
        L.append("")

    if interrogation.get("errors"):
        L.append("## ❌ 错误（带依据）")
        L.append("")
        for e in interrogation["errors"]:
            ref = e.get("source_ref") or "（无依据）"
            L.append(f"- 「{e.get('quote', '')[:50]}」　依据 {ref}：{e.get('reason', '')}")
        L.append("")

    if interrogation.get("uncertain"):
        L.append("## ❓ 待你核对（模型没找到依据，不硬判）")
        L.append("")
        for u in interrogation["uncertain"]:
            L.append(f"- 「{u.get('quote', '')[:50]}」　{u.get('reason', '')}")
        L.append("")

    todo = list(interrogation.get("todo") or [])
    todo += [f"作业未勾选：{i['text']}" for i in progress["items"] if not i["done"]]
    if todo:
        L.append("## 🔧 查缺补漏清单")
        L.append("")
        for t in dict.fromkeys(todo):
            L.append(f"- [ ] {t}")
        L.append("")

    if interrogation.get("summary"):
        L.append("## 总评")
        L.append("")
        L.append(interrogation["summary"])
        L.append("")

    L.append("---")
    L.append(f"（本次结果可回填到笔记末尾；下次整理会重新计算）")
    return "\n".join(L)
