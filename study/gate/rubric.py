"""gate · 自检问答判分器（quiz 维度）。

方案由 S-H2 Spike 实测确定（极差 0.0，分类 5/5）：
  - deepseek-flash + thinking=disabled + temperature=0 + JSON Output
  - 【结构化判定点】逐点判定 pass/partial/fail，分数取判定点均值
  - 绝不让模型自由打分（那是不可复现的）
另新增 fatal_misconception 通道：概念性错误理解会阻断"带疑点前进"逃生阀（D3）。
"""
from core.llm import LLMError  # noqa: F401  （调用方可能捕获）

VERDICT_SCORE = {"pass": 1.0, "partial": 0.5, "fail": 0.0}

JUDGE_SYSTEM = (
    "你是一个严格的技术判分器。只依据给定的判定点逐项判定，不看文采、不看篇幅、"
    "不因为答案长就给分。\n"
    "对每个判定点输出 verdict：\"pass\"（明确且正确地说到了）、"
    "\"partial\"（沾边但不完整或有轻微偏差）、\"fail\"（没说、说错或概念混淆）。\n"
    "另外判断是否存在**致命误解**：即概念性错误理解（不是遗漏，而是把概念搞反、"
    "张冠李戴、把 A 当成 B）。有就置 fatal_misconception=true 并说明；"
    "只是没提到、说得简略，一律不算致命。\n"
    "必须输出 JSON：\n"
    '{"points":[{"id":"P1","verdict":"pass|partial|fail","evidence":"引用原句或写 无"}],'
    '"fatal_misconception":false,"fatal_reason":"","comment":"一句话总评"}\n'
    "points 必须与给定判定点数量、顺序一致。"
)


def judge_answer(llm, question, points, answer, system=None):
    """判定单个自检问题的回答。points 为判定点字符串列表。

    system 可覆盖默认判分提示词，供 transfer 等场景复用同一套判定点机制。
    """
    point_lines = "\n".join(f"{i+1}. {p}" for i, p in enumerate(points))
    user = (
        f"【题目】{question}\n\n"
        f"【判定点】\n{point_lines}\n\n"
        f"【学生的回答】\n{answer or '（未作答）'}\n\n"
        "请按判定点逐项判定，以 JSON 输出。"
    )
    data = llm.chat(system or JUDGE_SYSTEM, user, json_mode=True, temperature=0.0)
    pts = data.get("points") or []
    if len(pts) != len(points):
        raise ValueError(f"判定点数量不符：期望 {len(points)}，得到 {len(pts)}")
    scores = [VERDICT_SCORE.get(p.get("verdict"), 0.0) for p in pts]
    return {
        "score": round(sum(scores) / len(scores), 4),
        "verdicts": [p.get("verdict") for p in pts],
        "evidence": [p.get("evidence", "") for p in pts],
        "fatal_misconception": bool(data.get("fatal_misconception")),
        "fatal_reason": data.get("fatal_reason", ""),
        "comment": data.get("comment", ""),
    }


def judge_self_check(llm, curriculum, answers):
    """判定整课的 self_check。

    answers: {question_id: answer_text}
    返回 {score, per_question{}, fatal, fatal_reasons[]}
    """
    per_question = {}
    fatal_reasons = []
    scores = []

    for q in curriculum["self_check"]:
        qid = q["id"]
        if qid not in answers:
            per_question[qid] = {"score": 0.0, "skipped": True,
                                 "comment": "未作答，按 0 计"}
            scores.append(0.0)
            continue
        res = judge_answer(llm, q["question"], q["points"], answers[qid])
        res["skipped"] = False
        per_question[qid] = res
        scores.append(res["score"])
        if res["fatal_misconception"]:
            fatal_reasons.append(f"{qid}: {res['fatal_reason']}")

    return {
        "score": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "per_question": per_question,
        "fatal": bool(fatal_reasons),
        "fatal_reasons": fatal_reasons,
    }
