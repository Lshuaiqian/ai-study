"""library · 抽取流水线。

核心设计（对应可行性文档 §4.1 的 H1 假设）：
  **不信任模型给出的出处，而是程序化验证它。**

流程：
  1. 让模型从资料里抽候选原子，每条**必须附一句原文引文（quote）**
  2. `verify_candidates()` 用程序检查这句引文是否真的出现在资料里
     —— 找不到就直接拒收，不进原子库
  3. 通过验证的候选写成 `pending` 状态，等人工确认后才生效

这样"抽不出出处的不许入库"就不是一句口号：它是可以被确定性测试的。
LLM 调用与验证逻辑刻意拆开，验证部分是纯函数。
"""
import re

from .store import (SOURCE_KINDS, STATUS_PENDING, make_atom_id)

MIN_QUOTE_LEN = 8          # 太短的引文没有验证价值

EXTRACT_SYSTEM = (
    "你是知识库录入员。从给定资料里抽取**可被检验、可被复用**的最小知识单元。规则严格：\n"
    "1) 只抽资料里**真实写到**的内容，不要补充资料外的知识。\n"
    "2) 每条必须附 quote —— **资料中的原句**（照抄，不改写、不拼接）。"
    "如果找不到能支撑该结论的原句，就不要输出这一条。\n"
    "3) type 取值：concept（概念/原理）、api（接口/函数用法）、pitfall（易错点/坑）、"
    "example（示例）、exercise（练习）、formula（公式）。\n"
    "4) knowledge_id 从给定的【本课知识点】里选最贴近的一个；实在不属于任何一条就留空。\n"
    "\n【必须排除的内容】—— 这是本任务最容易犯的错：\n"
    "  ✗ 过程性叙述：\"我这次改了三处\"、\"跑到第 2 页共 20 条\"、\"耗时 3 秒\"、\"没触发限频\"\n"
    "  ✗ 只在本篇语境成立的事实：\"我复用了 NextLinkParser\"、\"我用了 books.toscrape.com\"\n"
    "  ✗ 正确但没有信息量的内容：整段抄写、过渡句、标题\n"
    "  判断标准只有一条：**换一个场景、换一份资料，这条结论还成立吗？**"
    "只有成立的才算知识。\n"
    "\n必须输出 JSON：\n"
    '{"atoms":[{"type":"concept","title":"短标题","statement":"这条知识本身，1-3 句",'
    '"why":"为什么重要/什么时候用","quote":"资料中的原句","knowledge_id":"K3 或 空"}]}'
)


def build_prompt(curriculum, material_text, source_ref):
    declares = curriculum.get("declares") or {}
    kp_lines = "\n".join(
        f"- {k['id']} {k['name']}" for k in declares.get("knowledge") or []) or "（未提供）"
    return (
        f"【本课】{curriculum.get('title', curriculum.get('course_id'))}\n"
        f"【本课知识点】\n{kp_lines}\n\n"
        f"【资料出处标记】{source_ref}\n\n"
        f"【资料正文】\n{material_text}\n\n"
        "请以 JSON 输出抽到的知识原子。"
    )


def _norm(text):
    """归一化以便比对：去掉所有空白与常见全角标点差异。"""
    return re.sub(r"\s+", "", (text or "")).strip()


def verify_candidates(candidates, material_text):
    """程序化验证引文是否真的在资料里。

    返回 (verified, rejected)；每条 rejected 带 reason。
    """
    haystack = _norm(material_text)
    verified, rejected = [], []
    for c in candidates:
        quote = (c.get("quote") or "").strip()
        if not (c.get("statement") or "").strip():
            rejected.append({**c, "reason": "缺少 statement"})
            continue
        if len(_norm(quote)) < MIN_QUOTE_LEN:
            rejected.append({**c, "reason": f"引文过短（<{MIN_QUOTE_LEN} 字），无法验证"})
            continue
        if _norm(quote) not in haystack:
            rejected.append({**c, "reason": "引文未在资料原文中找到（疑似编造出处）"})
            continue
        verified.append(c)
    return verified, rejected


# 权威级别：决定这条原子能不能用来"判定别人写错了"
#   authoritative —— 教材 / 官方文档 / 人工撰写的种子资料
#   derived       —— 从学生自己的笔记、代码、反思里抽出来的
# 从自己的笔记抽原子去纠正自己的笔记，是循环论证。所以 derived 原子
# 只允许用于"关联建议"，**不允许作为判错依据**。
AUTHORITY_BY_KIND = {
    "material": "authoritative",
    "web": "authoritative",
    "feishu": "authoritative",
    "note": "derived",
    "code": "derived",
}


def to_atoms(candidates, course_id, source_kind="material", source_ref="",
             lang="python", confidence=0.8):
    """把已验证的候选转成 pending 原子。"""
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"非法 source_kind: {source_kind}")
    authority = AUTHORITY_BY_KIND.get(source_kind, "derived")
    out = []
    for c in candidates:
        title = (c.get("title") or "").strip()
        quote = (c.get("quote") or "").strip()
        atom = {
            "atom_id": make_atom_id(course_id, title, quote),
            "type": c.get("type") or "concept",
            "title": title,
            "statement": (c.get("statement") or "").strip(),
            "why": (c.get("why") or "").strip(),
            "knowledge_id": c.get("knowledge_id") or "",
            "course": course_id,
            "lang": lang,
            "source": {"kind": source_kind, "ref": source_ref,
                       "quote": quote, "verified": True, "confidence": confidence,
                       "authority": authority},
            "prerequisites": c.get("prerequisites") or [],
            "related": c.get("related") or [],
            "contrast": c.get("contrast") or [],
            "mastery": 0.0,
            "status": STATUS_PENDING,
            "tags": c.get("tags") or [],
        }
        out.append(atom)
    return out


def dedupe(new_atoms, existing):
    """按 atom_id 去重：已存在的（不论状态）都不再重复写入。"""
    fresh = [a for a in new_atoms if a["atom_id"] not in existing]
    dup = [a for a in new_atoms if a["atom_id"] in existing]
    return fresh, dup


def extract_candidates(llm, curriculum, material_text, source_ref):
    """调用模型抽候选并做程序化验证。返回结果字典（不落盘）。"""
    prompt = build_prompt(curriculum, material_text, source_ref)
    data = llm.chat(EXTRACT_SYSTEM, prompt, json_mode=True, temperature=0.0)
    raw = data.get("atoms") or []
    verified, rejected = verify_candidates(raw, material_text)
    return {"raw_count": len(raw), "verified": verified, "rejected": rejected}
