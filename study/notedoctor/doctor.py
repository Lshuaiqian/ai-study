"""notedoctor · 笔记医生（P0：覆盖 + 准确 两维）。

设计原则（D7 / D10）：
  - 【覆盖】维度用**程序判定**，不交给 LLM 自由心证——最容易被信任的部分必须是确定性的
  - 【准确】维度由 LLM 判定，但**必须引用 source_ref**；无依据只能标 uncertain
  - uncertain 不计入扣分，而是转成"请你自己核对"的问题（H3 实测该行为可稳定复现）
  - AI 只出建议 diff，不直接改笔记（D8）
  - 笔记门槛只卡「必会知识点覆盖 100% + 无事实错误」，不卡文采篇幅（D10）

H3 实测：precision 1.00 / 误报正确句 0 / 资料未覆盖时正确降级（见可行性深化文档 §4.3）
"""
from gate.mastery import note_score

REVIEW_SYSTEM = (
    "你是笔记审校员。对照【学习库资料】检查【学生笔记】。规则严格：\n"
    "1) 只有当笔记的说法与资料明确冲突时，才可判 verdict=\"error\"，"
    "且必须给出 source_ref（资料编号如 M3）。\n"
    "2) 若你怀疑有问题但资料里没有依据，一律判 verdict=\"uncertain\"，source_ref 留空。\n"
    "3) 保持正确的表述不要报。看不懂或只是简略的，不要报。\n"
    "4) error 需给出 severity：critical（概念搞反/张冠李戴）、major（明确说错）、minor（表述不严谨）。\n"
    "5) 另需评估：结构（有无小标题/例子/总结）、自己的话（是否整段照抄）、"
    "以及该补哪些相关知识链接。\n"
    "必须输出 JSON：\n"
    '{"issues":[{"quote":"笔记原句","verdict":"error|uncertain","severity":"critical|major|minor|",'
    '"reason":"说明","source_ref":"M3 或 空"}],'
    '"structure":{"has_headings":true,"has_example":true,"has_summary":false,"score":0.0},'
    '"own_words":{"score":0.0,"reason":""},'
    '"linking":{"suggestions":["[[HTTP 请求结构]]"],"score":0.0},'
    '"summary":"一句话总评"}\n'
    "issues 里只列你认为有问题的句子；没有就返回空数组。分数 score ∈ [0,1]。"
)

# 一个 error 对 accuracy 的扣分
SEVERITY_PENALTY = {"critical": 0.5, "major": 0.25, "minor": 0.1}


# ---------------- 覆盖：确定性判定 ----------------

def check_coverage(declares, note_text):
    """按知识点的 keywords 做确定性覆盖判定。

    规则：某知识点的每个 keyword 组内【任一词命中】即该组通过；
          所有组都通过，才算该知识点被覆盖。
    只统计 level == "must" 的知识点（门禁只卡必会，见 D10）。
    """
    text = note_text or ""
    covered, missing, detail = [], [], {}

    for kp in declares.get("knowledge", []):
        groups = kp.get("keywords") or []
        group_hits = []
        for g in groups:
            hit = next((w for w in g if w.lower() in text.lower()), None)
            group_hits.append(hit)
        ok = bool(groups) and all(group_hits)
        detail[kp["id"]] = {"name": kp["name"], "level": kp.get("level", "must"),
                            "hits": group_hits, "covered": ok}
        (covered if ok else missing).append(kp["id"])

    must = [kp for kp in declares.get("knowledge", []) if kp.get("level", "must") == "must"]
    must_ids = [kp["id"] for kp in must]
    must_covered = [i for i in must_ids if detail[i]["covered"]]
    ratio = round(len(must_covered) / len(must_ids), 4) if must_ids else 1.0

    return {
        "covered": covered,
        "missing": missing,
        "must_ids": must_ids,
        "must_covered": must_covered,
        "must_missing": [i for i in must_ids if i not in must_covered],
        "must_cover_ratio": ratio,
        "detail": detail,
    }


# ---------------- 准确 / 结构 / 自产 / 关联：LLM ----------------

def review_note(llm, materials, note_text, course_points=None):
    """LLM 审校。materials 为学习库原子列表（含 id / text）。"""
    mat_lines = "\n".join(f"[{m['id']}] {m['text']}" for m in materials)
    kp_lines = "\n".join(f"- {p}" for p in (course_points or [])) or "（未提供）"
    user = (
        f"【课程知识点】\n{kp_lines}\n\n"
        f"【学习库资料】\n{mat_lines}\n\n"
        f"【学生笔记】\n{note_text}\n\n"
        "请以 JSON 输出审校结果。"
    )
    return llm.chat(REVIEW_SYSTEM, user, json_mode=True, temperature=0.0)


def summarize_review(review):
    """把 LLM 审校结果折算成可计算的量。"""
    issues = review.get("issues") or []
    errors = [i for i in issues if i.get("verdict") == "error"]
    uncertain = [i for i in issues if i.get("verdict") == "uncertain"]

    penalty = 0.0
    for e in errors:
        penalty += SEVERITY_PENALTY.get(e.get("severity") or "major", 0.25)
    accuracy = round(max(0.0, 1.0 - penalty), 4)

    return {
        "errors": errors,
        "uncertain": uncertain,
        "accuracy": accuracy,
        "fatal": any((e.get("severity") == "critical") for e in errors),
        "fatal_reasons": [f"笔记致命错误: {e.get('quote', '')[:40]} → {e.get('reason', '')}"
                          for e in errors if e.get("severity") == "critical"],
    }


# ---------------- 组合：一次体检 ----------------

def diagnose(llm, curriculum, note_text, atoms=None):
    """完整笔记体检（P0 两维 + 三个轻量维）。

    atoms：学习库提供的证据（形如 [{"id":..., "text":...}]）。
           为 None 时回退到课程 JSON 里人工写的种子原子——这样即使学习库还没建，
           体检也能跑，只是证据更薄。
    """
    declares = curriculum["declares"]
    if atoms is None:
        atoms = [{"id": m["id"], "text": m["text"]}
                 for m in (curriculum.get("materials") or {}).get("atoms") or []]
    course_points = [k["name"] for k in declares["knowledge"]]

    cov = check_coverage(declares, note_text)
    review = review_note(llm, atoms, note_text, course_points)
    acc = summarize_review(review)

    parts = {
        "structure": (review.get("structure") or {}).get("score", 0.0),
        "coverage": cov["must_cover_ratio"],
        "accuracy": acc["accuracy"],
        "linking": (review.get("linking") or {}).get("score", 0.0),
        "own_words": (review.get("own_words") or {}).get("score", 0.0),
    }

    return {
        "coverage": cov,
        "accuracy": acc,
        "review": review,
        "parts": parts,
        "note_score": note_score(parts),
        "fatals": acc["fatal_reasons"],
        "evidence_count": len(atoms),
    }


# ---------------- 报告渲染 ----------------

def render_report(result, curriculum):
    cov, acc, parts = result["coverage"], result["accuracy"], result["parts"]
    kp = curriculum["declares"]["knowledge"]
    name_of = {k["id"]: k["name"] for k in kp}

    lines = [f"📋 笔记体检 · {curriculum['title']}", ""]
    lines.append(f"① 结构   {parts['structure']:.2f}   "
                 f"{'缺总结小节' if not (result['review'].get('structure') or {}).get('has_summary') else 'OK'}")
    lines.append(f"② 覆盖   {parts['coverage']:.2f}   必会 {len(cov['must_covered'])}/{len(cov['must_ids'])}"
                 + (f"  ⚠️ 未提及：{'、'.join(name_of[i] for i in cov['must_missing'])}"
                    if cov["must_missing"] else "  ✅ 必会全覆盖"))
    lines.append(f"③ 准确   {parts['accuracy']:.2f}   "
                 f"error {len(acc['errors'])} / 待确认 {len(acc['uncertain'])}")
    for e in acc["errors"]:
        lines.append(f"        ❌ [{e.get('severity')}] {str(e.get('quote'))[:46]}")
        lines.append(f"           依据 {e.get('source_ref') or '（无）'}：{e.get('reason')}")
    for u in acc["uncertain"]:
        lines.append(f"        ❓ 待你核对：{str(u.get('quote'))[:46]} —— {u.get('reason')}")
    lines.append(f"④ 关联   {parts['linking']:.2f}   "
                 f"建议补链：{'、'.join((result['review'].get('linking') or {}).get('suggestions') or []) or '（无）'}")
    lines.append(f"⑤ 自产   {parts['own_words']:.2f}   "
                 f"{(result['review'].get('own_words') or {}).get('reason', '')}")
    lines.append("")
    lines.append(f"→ 笔记得分 {result['note_score']:.4f}（权重 结构0.2/覆盖0.3/准确0.3/关联0.1/自产0.1）")
    return "\n".join(lines)
