"""notedoctor · 笔记整理（达到「AI 整理稿」质量，并反馈给掌握度）。

质量标准的来源
    沿用 `E:\\Agents\\feishu-notes\\prompt_tidy.txt` 那套已经被验证过的写法：
      - **语义保真重写，不逐字保真**：把碎片、断句、错字还原为规范连贯的书面中文
      - **句式统一**：`**名词**：规范定义` —— 读起来像可以直接背的教材节选
      - **固定输出结构**：📖 本篇主题 → 🏷 体系化标题（≤14 字）→ 📌 本篇预告
        → `## 一、` / `### 1.` / `（1）` 统一层级 → 💡 小结与易错点
      - **保留全部原知识点**，允许等价改写与归位，但不合并吞掉
      - **不编造**：确实没有的留白或标 〔?〕；代码原样保留并标语言

与飞书版的区别
    飞书版是**通用整理**（面向任何笔记）。这里是**课程笔记整理**：
      - 领域上下文来自**知识体系**（本课的知识点 + 维度），不是写死的数据结构
      - 整理结果要**结构化反馈**（覆盖了哪些知识点 / 还缺什么 / 术语 / 待办），
        这样才能变成掌握度数据，而不是只让人读着舒服

写入语义（**不是覆写**）
    笔记分三区：脚手架区 / 你的笔记区 / AI 区 + 历史区。
    整理只替换 **AI 区**（幂等），你的正文一字不动，历史只追加，全量版本落盘可回滚。
"""
import json
import os
import re
from datetime import datetime

try:
    import io as _io
except ImportError:  # pragma: no cover
    _io = None

# ---------------------------------------------------------------- 分区标记

AI_START = "<!-- tidy:start"
AI_END = "<!-- tidy:end -->"
AI_HEADING = "## 🤖 AI 整理"
HISTORY_HEADING = "## 📚 整理历史"
USER_HEADING = "## ✍️ 我的笔记"
PLACEMENT_HEADING = "## ⚡ 你的起点"
REQ_HEADING = "## 📋 考核要求"

SOFT_HEADING = "## 🌐 软整理（仅排版，未改语义）"

# 质询区：与整理区并列、各自可替换，互不吞并
QUIZ_START = "<!-- quiz:start"
QUIZ_END = "<!-- quiz:end -->"
QUIZ_HEADING = "## 🧪 AI 质询"

# 脚手架残留：HTML 注释、以及脚手架里那句「（写完后运行：…）」提醒
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
SCAFFOLD_HINT_RE = re.compile(r"^[（(][^）)]*(?:运行|python\s+study)[^）)]*[）)]$")
SCAFFOLD_HEADING_RE = re.compile(r"^#{2,6}\s*\d+\s*[.、]")

# ---------------------------------------------------------------- 提示词

TIDY_SYSTEM = """你的任务：把学生的一份**课程笔记**整理成「教材级复习笔记」。

核心立场：**语义保真重写，不逐字保真**。把碎片、断句、口语、错字、残留符号，
依据课程领域知识还原为规范、连贯的书面中文。信息以「意思不丢、不新造概念」为准，
句式由你负责组织成流畅的学术表达。

【领域上下文（必须结合使用）】
本课知识点如下；判断归类、补全断词、纠正明显错误时一律以这套术语体系为准：
__KNOWLEDGE__
与常识冲突的归类直接纠正（无需加注）。**不得发明天花板之外的新概念**。

【质量标准（输出必须达到此风格）】
每个概念先给定义句，再做分类/要点；用词书面精炼，无口语、无 AI 腔、无「首先其次最后」式套话；
层次严密，结构如 `## 一、… / ### 1. … / （1）…`；同级用同级编号。
定义句统一为「**名词**：规范定义」这种"名词加粗 + 冒号 + 定义"的写法。
最终产物读起来应像可以直接背的教材节选。

【输出结构（固定）】
1. 首行：`# {原标题}`
2. 次行：`📖 本篇主题：` 一句话概括本篇讲了什么
3. 第三行必须是：`🏷 体系化标题：<学科>·<知识点>`
   - **≤14 字**（不含前缀），采用"学科·知识点"结构，便于归档检索
   - 示例：`网络爬虫·请求与解析`、`Python·类与魔术方法`
   - 禁止整句、禁止带标点、禁止把原标题原样抄来
4. `## 📌 本篇预告`：重点 3-6 条，关键词化
5. 正文按内容自然分节，核心概念用「**名词**：定义句」；需要对比处可用简表
6. 结尾 `## 💡 小结与易错点`：3-5 条

【课程对齐要求（比通用整理多这一步）】
- 整理后的正文要**按本课知识点组织**，让人一眼看出每个知识点在哪里讲到了
- 凡原笔记出现的概念/要点/例子/结论必须**全部出现**，不遗漏、不合并吞掉
- 原笔记**没提到的知识点不要硬补**：那是"还没学"，不是"整理该做的事"

【硬性红线】
1. **不编造**：只能写笔记里有的内容，或按术语常识可补全的定义句；
   确实缺失的留白或标 〔?〕，不许编。
2. **代码原样保留**并标注语言，不改逻辑。
3. 全程书面中文，零无用字符，不注水。
4. 只输出 Markdown 正文，不要任何解释性前后缀。

【学生笔记】
----------------------------------------
__NOTES__
----------------------------------------
直接输出整理结果。"""

# 结构化反馈：与整理分开调用。理由 —— JSON 模式会明显压低散文质量，
# 而这两件事的目标不同（一个是给人读的教材稿，一个是给程序吃的账）。
FEEDBACK_SYSTEM = (
    "你是一个课程笔记的审阅者。给定【本课知识点】与【学生笔记的整理稿】，"
    "判断每个知识点的覆盖情况，并抽出可复用的结构化信息。\n"
    "规则：\n"
    "1) 每个知识点给 status：covered（用自己的话讲清且正确）、"
    "partial（提到但不完整）、missing（没提）。\n"
    "2) glossary：抽出笔记里出现的术语，各给一句规范定义（依据术语常识补全，不编造）。\n"
    "3) todo：还没做或还没写的具体事项。\n"
    "4) errors：事实性错误，**必须带 reasoning 说明依据**；没依据的放 uncertain。\n"
    "必须输出 JSON：\n"
    '{"system_title":"学科·知识点（≤14字）","theme":"一句话主题",'
    '"preview":["重点1","重点2"],'
    '"coverage":[{"id":"K1","status":"covered|partial|missing","why":"一句话"}],'
    '"glossary":[{"term":"术语","def":"定义"}],'
    '"todo":["还没做的事"],'
    '"errors":[{"quote":"原句","reasoning":"依据"}],'
    '"uncertain":[{"quote":"原句","reason":"为什么存疑"}],'
    '"summary":"两三句总评"}'
)


def build_knowledge_context(curriculum):
    """把本课知识点拼成提示词里的领域上下文（含维度，帮模型归类）。"""
    lines = []
    for k in curriculum["declares"]["knowledge"]:
        dim = k.get("dimension_name") or k.get("dimension") or ""
        lvl = "必会" if k.get("level") == "must" else "了解"
        lines.append(f"- [{lvl}] {k['name']}" + (f"（{dim}）" if dim else ""))
    return "\n".join(lines) or "（本课未声明知识点）"


# ---------------------------------------------------------------- 分区

def split_zones(text):
    """把笔记切成 骨架 / 你的笔记 / AI 区 / 历史 四块。

    用户的正文与 AI 的产物必须能分开，否则"整理"迟早会吃掉人写的东西。

    坑：AI 区的起点必须算上它的小标题 `## 🤖 AI 整理`，不能只从 `<!-- tidy:start -->`
    开始算——否则第二次整理时，上一轮的标题会留在"用户区"，再生成一个新标题，
    AI 区就会一轮一轮地叠加（实测三轮后标题出现 3 次）。
    """
    ai_start = text.find(AI_START)
    ai_end = text.find(AI_END, ai_start) if ai_start >= 0 else -1
    has_ai = ai_start >= 0 and ai_end >= 0

    ai_head = text.find(AI_HEADING)
    if has_ai:
        region_start = ai_head if 0 <= ai_head <= ai_start else ai_start
    else:
        region_start = -1
    ai_region_end = ai_end + len(AI_END) if has_ai else -1

    # 质询区：与整理区**并列且各自独立**，这样「再整理一次」不会吃掉质询结论，
    # 「再质询一次」也不会吃掉整理稿。
    q_start = text.find(QUIZ_START)
    q_end = text.find(QUIZ_END, q_start) if q_start >= 0 else -1
    has_quiz = q_start >= 0 and q_end >= 0
    q_head = text.find(QUIZ_HEADING)
    if has_quiz:
        q_region_start = q_head if 0 <= q_head <= q_start else q_start
    else:
        q_region_start = -1
    q_region_end = q_end + len(QUIZ_END) if has_quiz else -1

    # 用户区的右边界 = 最早出现的那个 AI-ish 区起点
    bounds = [b for b in (region_start if has_ai else -1,
                          q_region_start if has_quiz else -1) if b >= 0]
    body_end = min(bounds) if bounds else len(text)

    user_idx = text.find(USER_HEADING)
    if user_idx >= 0 and user_idx < body_end:
        skeleton = text[:user_idx]
        user = text[user_idx:body_end]
        # 「我的笔记」与 AI 区之间那条 --- 是结构分隔线，不是用户写的内容。
        # 不算清楚它，每整理一次就会往用户区沉淀一条 ---（实测 2 次后 2 条）。
        user = re.sub(r"(?:\n[ \t]*-{3,}[ \t]*)+\s*$", "", user).strip("\n")
    else:
        skeleton, user = text[:body_end], ""

    ai_block = text[region_start:ai_region_end] if has_ai else ""
    quiz_block = text[q_region_start:q_region_end] if has_quiz else ""
    # 历史区 = 最后一个 AI-ish 区之后的所有内容
    tail_start = max([b for b in (ai_region_end, q_region_end) if b >= 0] or [len(text)])
    after = text[tail_start:] if tail_start < len(text) else ""
    # 与历史区之间那条 --- 同样是结构分隔线，不剥掉也会一轮一条地累加
    after = re.sub(r"^\s*(?:-{3,}[ \t]*\n+)+", "", after) if after else after
    return {"skeleton": skeleton.rstrip("\n"), "user": user.strip("\n"),
            "ai": ai_block, "quiz": quiz_block,
            "after": after.strip("\n"), "has_ai": has_ai, "has_quiz": has_quiz}


def extract_user_notes(text):
    """只取「我的笔记」区——整理应该只吃这一块，不该把考核要求当笔记整理。"""
    zones = split_zones(text)
    user = zones["user"]
    if user:
        return user[len(USER_HEADING):].strip("\n") if user.startswith(USER_HEADING) else user
    # 没有分区标记的老笔记：去掉考核要求之后再整理
    idx = text.find(REQ_HEADING)
    if idx >= 0:
        tail = text[idx:]
        nxt = tail.find("\n## ", 10)
        if nxt > 0:
            return tail[nxt:].strip("\n")
    return text.strip("\n")


# ---------------------------------------------------------------- 调用

def user_notes_clean(text):
    """送去整理的正文：去掉 HTML 注释，保留学习者自己的标题结构。"""
    return COMMENT_RE.sub("", extract_user_notes(text)).strip("\n")


def user_substance(text):
    """「我的笔记」里**真正由人写下**的部分（剥掉脚手架注释、提醒行、模板小标题）。

    脚手架模板本身就是 200 来字。直接按字数判断，会把"还没开始写"当成"有内容"，
    于是整理出一篇对模板的点评、质询出一堆对注释的提问。
    """
    keep = []
    for line in user_notes_clean(text).splitlines():
        s = line.strip()
        if not s or SCAFFOLD_HINT_RE.match(s) or SCAFFOLD_HEADING_RE.match(s):
            continue
        keep.append(s)
    return "\n".join(keep)


def tidy(llm, curriculum, note_text):
    """整理 + 结构化反馈。返回 {markdown, feedback, usage}。"""
    notes = user_notes_clean(note_text)
    if len(re.sub(r"\s+", "", user_substance(note_text))) < 5:
        raise ValueError("「我的笔记」还是空的或只有模板注释，没有可整理的内容")

    prompt = (TIDY_SYSTEM
              .replace("__KNOWLEDGE__", build_knowledge_context(curriculum))
              .replace("__NOTES__", notes))
    markdown = llm.chat(prompt, "请开始整理。", json_mode=False,
                        temperature=0.3).strip()

    kp_lines = "\n".join(
        f"- {k['id']} {k['name']}" for k in curriculum["declares"]["knowledge"])
    feedback = llm.chat(
        FEEDBACK_SYSTEM,
        f"【本课】{curriculum.get('title')}\n【本课知识点】\n{kp_lines}\n\n"
        f"【整理稿】\n{markdown}\n\n请以 JSON 输出。",
        json_mode=True, temperature=0.0)

    valid = {k["id"] for k in curriculum["declares"]["knowledge"]}
    if feedback.get("coverage"):
        feedback["coverage"] = [c for c in feedback["coverage"] if c.get("id") in valid]
    return {"markdown": markdown, "feedback": feedback, "notes_used": notes}


# ---------------------------------------------------------------- 组装（三区写入）

def strip_preamble(markdown):
    """整理稿的前几行是 📖 / 🏷，属于"给人看的头"，放进 AI 区即可，不特殊处理。"""
    return markdown.strip()


def _assemble(head, ai_block, quiz_block, history):
    """按「骨架+用户 → 整理区 → 质询区 → 历史」拼装，分隔线只在存在处出现。"""
    parts = [head.rstrip("\n")]
    if ai_block:
        parts.append(ai_block.strip("\n"))
    if quiz_block:
        parts.append(quiz_block.strip("\n"))
    if history:
        parts.append(history.strip("\n"))
    return "\n\n---\n\n".join(p for p in parts if p) + "\n"


def _history_with(history, entry, key):
    if not history:
        return f"{HISTORY_HEADING}\n\n{entry}"
    if key not in history:
        return history.rstrip("\n") + "\n" + entry
    return history


def _head_of(zones):
    head = zones["skeleton"]
    if zones["user"]:
        head = head + "\n\n" + zones["user"]
    return head


def compose(note_text, tidied_markdown, feedback, ts=None, version_ref=""):
    """把整理结果写回笔记：**只替换 AI 整理区**，用户正文、质询区、历史一字不动。"""
    ts = ts or datetime.now().strftime("%Y-%m-%d %H:%M")
    zones = split_zones(note_text)

    head = _head_of(zones)

    ai_block = "\n".join([
        AI_HEADING,
        "",
        f"<!-- tidy:start ts={ts} version={version_ref} -->",
        f"> 本次整理于 {ts}｜覆盖 {coverage_ratio(feedback):.0%}"
        f"（这个区块每次整理会被**整块替换**；你的「✍️ 我的笔记」AI 永不改动）",
        "",
        strip_preamble(tidied_markdown),
        AI_END,
    ])

    entry = (f"- `{ts}`　整理　覆盖 {coverage_ratio(feedback):.0%}"
             f"　{feedback.get('system_title', '')}"
             + (f"　`{version_ref}`" if version_ref else ""))
    history = _history_with(zones.get("after") or "", entry, f"`{ts}`　整理")
    return _assemble(head, ai_block, zones.get("quiz") or "", history)


def compose_quiz(note_text, quiz_markdown, ts=None, percent=None):
    """把质询结论写进**独立的质询区**（整块替换）。

    以前是往文件末尾无脑 append：每质询一次就多一块，且会掉进「整理历史」区里
    越堆越长。现在质询区与整理区并列，各自替换、互不吞并。
    """
    ts = ts or datetime.now().strftime("%Y-%m-%d %H:%M")
    zones = split_zones(note_text)
    head = _head_of(zones)

    pct = f"｜达成度 {percent:.0%}" if percent is not None else ""
    quiz_block = "\n".join([
        QUIZ_HEADING,
        "",
        f"<!-- quiz:start ts={ts} -->",
        f"> 本次质询于 {ts}{pct}（这个区块每次质询会被**整块替换**）",
        "",
        quiz_markdown.strip(),
        QUIZ_END,
    ])
    entry = f"- `{ts}`　质询{pct}"
    history = _history_with(zones.get("after") or "", entry, f"`{ts}`　质询")
    return _assemble(head, zones.get("ai") or "", quiz_block, history)


def compose_rollback(note_text, markdown, ts):
    """把整理区回滚到某个快照：用户区、质询区、历史都不动。"""
    zones = split_zones(note_text)
    head = _head_of(zones)
    ai_block = "\n".join([
        AI_HEADING, "",
        f"<!-- tidy:start ts={ts} version=rollback -->",
        f"> 已回滚到 {ts} 的快照",
        "", markdown.strip(), AI_END,
    ])
    history = zones.get("after") or ""
    key = f"回滚到 {ts}"
    if key not in history:
        entry = f"- `{ts}`　回滚"
        history = history.rstrip("\n") + "\n" + entry if history else \
            f"{HISTORY_HEADING}\n\n{entry}"
    return _assemble(head, ai_block, zones.get("quiz") or "", history)


def coverage_ratio(feedback):
    cov = feedback.get("coverage") or []
    if not cov:
        return 0.0
    score = {"covered": 1.0, "partial": 0.5, "missing": 0.0}
    return sum(score.get(c.get("status"), 0.0) for c in cov) / len(cov)


def note_dimension(feedback):
    """把整理结果折算成 note 维度（五维体检加权，与 doctor.py 一致）。

    没有任何覆盖信息时返回 0，而不是"没有错误所以准确率满分"——
    **不知道就是不知道，不该给分。**
    """
    from gate.mastery import note_score
    cov = feedback.get("coverage") or []
    if not cov:
        return 0.0
    coverage = coverage_ratio(feedback)
    n_err = len(feedback.get("errors") or [])
    accuracy = max(0.0, 1.0 - 0.35 * n_err)
    glossary = feedback.get("glossary") or []
    return note_score({
        "structure": 0.9 if feedback.get("preview") else 0.6,
        "coverage": coverage,
        "accuracy": accuracy,
        "linking": 0.7 if len(glossary) >= 3 else 0.4,
        "own_words": 0.8,
    })


# ---------------------------------------------------------------- 版本落盘

def save_version(state_dir, note_id, markdown, keep=30):
    """把本次的整理稿落盘：AI 区每一版都留底，可回滚到任一版。

    存的是**整理稿**（AI 区的内容），不是整篇笔记——用户的「✍️ 我的笔记」
    本来就不会被改动，不需要靠快照保命。
    """
    d = os.path.join(state_dir, "note_versions", note_id or "unknown")
    os.makedirs(d, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(d, f"{ts}.md")
    # 同一秒里连点两次「一键整理」不该把上一份覆盖掉
    n = 2
    while os.path.exists(path):
        path = os.path.join(d, f"{ts}-{n}.md")
        n += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown if markdown.endswith("\n") else markdown + "\n")
    # 只保留最近 keep 份，避免无限膨胀（删的是旧快照，不是历史记录行）
    snaps = sorted(f for f in os.listdir(d) if f.endswith(".md"))
    for old in snaps[:-keep]:
        try:
            os.remove(os.path.join(d, old))
        except OSError:
            pass
    return path


def gap_items(course_id, feedback):
    """本课未覆盖/部分覆盖的知识点 → [(key, why)]（纯函数，不碰状态）。"""
    out = []
    for c in feedback.get("coverage") or []:
        if c.get("status") == "covered":
            continue
        out.append((f"{course_id}:{c.get('id')}", c.get("why", "")))
    return out


def queued_gaps(course_id, feedback):
    """会被送进补练/回炉队列的知识点键（纯函数，供预览显示用）。"""
    return [k for k, _ in gap_items(course_id, feedback)]


def build_payload(course_id, note_id, feedback, version_path=""):
    """整理结论 → 掌握度可读的载荷。

    **纯函数：预览与写入共用。** 预览也必须能显示 note 维度，
    但不能因此落盘——见 write_state 的说明。
    """
    return {
        "source": "note-tidy",
        "course_id": course_id,
        "note_id": note_id,
        "tidied_at": datetime.now().isoformat(timespec="seconds"),
        "coverage": feedback.get("coverage") or [],
        "coverage_ratio": round(coverage_ratio(feedback), 4),
        "glossary_count": len(feedback.get("glossary") or []),
        "system_title": feedback.get("system_title", ""),
        "theme": feedback.get("theme", ""),
        "todo": feedback.get("todo") or [],
        "errors": feedback.get("errors") or [],
        "uncertain": feedback.get("uncertain") or [],
        "summary": feedback.get("summary", ""),
        "note_dimension": note_dimension(feedback),
        "version": version_path,
    }


def _kind_map(protected):
    """保护集可以是 {id: kind} 或 {id, ...}；统一成前者。"""
    if not protected:
        return {}
    if isinstance(protected, dict):
        return dict(protected)
    return {k: "met" for k in protected}


def apply_gaps(atoms, course_id, gaps, source, protected=None, today=None):
    """把一批缺口写进 `atoms` —— **整理与质询共用这一条规矩**。

    规矩：**笔记/回答里没说到 ≠ 没掌握。**
      - 有证据的知识点（已 `passed`，或 placement 判定 `met`/`carried_over`）
        → **不摘牌**，只标 `note_gap` / `recheck_due` + 排队复核
        （与 cascade 前置回炉同一条规矩：只标待复查，不翻 passed）
      - 从没有过任何证据的 → `passed=False`，进补练队列（stage 0）

    `protected` 是 {本地 K-id: "met"|"carried_over"}（见 `system.protection_map`）。
    没有它，挂账会被整理一次就误判成「未通过」——实测 F0 的 9 个知识点曾被
    整片写成 `passed=false`，而 placement 明明判了 5 已具备 + 4 挂账。

    返回被写到的键列表。
    """
    today = today or datetime.now().date().isoformat()
    kinds = _kind_map(protected)
    touched = []
    for key, why in gaps:
        local = key.split(":", 1)[1] if ":" in key else key
        rec = atoms.get(key) or {}
        kind = kinds.get(local)
        has_evidence = bool(rec.get("passed")) or kind is not None
        rec["source"] = source
        rec["note_gap"] = True
        rec["note_gap_reason"] = why
        if has_evidence:
            if not rec.get("passed"):
                # placement 的证据把它提为"已具备"——这也要**修正**此前整理写下的
                # passed=False（笔记里没写到 ≠ 没掌握）。只判"键不存在"是不够的：
                # 整理先跑、质询后跑时，键已经存在且为 False。
                rec["passed"] = True
                rec["mastery_source"] = f"placement-{kind}" if kind else "passed"
            if kind == "carried_over":
                # 挂账：带疑点前进，下一课开头必须复查
                rec["carried_over"] = True
            rec["review_queue"] = True
            rec["next_review"] = today
            rec["recheck_due"] = True
            rec["recheck_reason"] = f"笔记未覆盖：{course_id}"
        else:
            rec["passed"] = False
            rec.pop("review_queue", None)
            rec.setdefault("stage", 0)
        # mastery=null 是"没测量"的坏表示（旧版本写的）：删掉键，别留一个空值
        if rec.get("mastery") is None:
            rec.pop("mastery", None)
        atoms[key] = rec
        touched.append(key)
    return touched


def write_state(state_dir, course_id, note_id, feedback, version_path,
                protected=None):
    """把整理结论反馈进掌握度数据——这是"反馈给 AI"的落点。

    下一次一键整理 / 门禁 / Planner 都能读到它。

    **只在 --apply 时调用。** 预览若也走这里，会把已通过的知识点降级成待补、
    往回炉队列里塞缺口——"看一眼笔记就改掌握度"是不可接受的副作用。
    """
    from core.store import read_json, write_json
    from plan.events import append_event

    payload = build_payload(course_id, note_id, feedback, version_path)
    findings_dir = os.path.join(state_dir, "findings")
    os.makedirs(findings_dir, exist_ok=True)
    write_json(os.path.join(findings_dir, f"{course_id}-tidy.json"), payload)

    # 缺口 → 补练/回炉队列
    state_path = os.path.join(state_dir, "mastery.json")
    state = read_json(state_path, default={"atoms": {}, "lessons": {}})
    atoms = state.setdefault("atoms", {})
    queued = apply_gaps(atoms, course_id, gap_items(course_id, feedback),
                        source="note-tidy", protected=protected)

    entry = state.setdefault("lessons", {}).get(course_id) or {}
    dims = dict(entry.get("dims") or {})
    dims["note"] = payload["note_dimension"]
    missing = [d for d in ("quiz", "transfer") if d not in dims]
    dims["note_gaps"] = len(queued)
    # 只记录证据，**不在这里重算 passed**——判定是 gate 的事，
    # 整理一次笔记就把已通过的课摘牌，属于越权。
    entry.update({"dims": dims, "needs": missing,
                  "last_note_tidy": payload["tidied_at"], "source": "note-tidy"})
    state["lessons"][course_id] = entry
    write_json(state_path, state)

    append_event(os.path.join(state_dir, "events.jsonl"), "note_review",
                 course_id=course_id, note_score=payload["note_dimension"],
                 source="note-tidy", parts={"coverage": payload["coverage_ratio"]})
    return payload, queued


# ---------------------------------------------------------------- 软整理（确定性）

def soft_tidy(text):
    """只做排版规整，**不改动任何语义**——不调用模型。

    什么时候用它：你不想让 AI 改写文字，只想把粘贴进来的东西弄干净。
    做的事：统一标题层级写法、压缩连续空行、去行尾空白、保证标题/代码块周围有空行。
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out, in_fence = [], False
    for raw in lines:
        # 代码块内**什么都不动**——连行尾空白也不动，否则会改掉别人贴的代码
        if in_fence:
            out.append(raw)
            if raw.strip().startswith("```"):
                in_fence = False
            continue
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = True
            out.append(line)
            continue
        # 全角井号 / 缺空格的标题 → 规范成 "# 标题"
        m = re.match(r"^(\s*)(#{1,6})\s*(.+?)\s*#*\s*$", line)
        if m:
            line = f"{m.group(2)} {m.group(3)}"
        out.append(line)

    # 压缩连续空行（同样跳过代码块内部——那里的空行是代码的一部分）
    compact = []
    blank = 0
    in_fence = False
    for line in out:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            compact.append(line)
            blank = 0
            continue
        if in_fence:
            compact.append(line)
            continue
        if not line.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        compact.append(line)

    # 标题与代码围栏前后各留一个空行
    spaced = []
    in_fence = False
    for line in compact:
        is_heading = bool(re.match(r"^#{1,6} ", line)) and not in_fence
        if line.strip().startswith("```"):
            in_fence = not in_fence
            if spaced and spaced[-1].strip():
                spaced.append("")
            spaced.append(line)
            continue
        if is_heading and spaced and spaced[-1].strip():
            spaced.append("")
        spaced.append(line)

    while spaced and not spaced[0].strip():
        spaced.pop(0)
    while spaced and not spaced[-1].strip():
        spaced.pop()
    return "\n".join(spaced) + "\n"


# ---------------------------------------------------------------- 报告

def render_report(feedback, payload=None, queued=None, version_path=""):
    L = ["📝 一键整理报告", "=" * 62, ""]
    if feedback.get("system_title"):
        L.append(f"🏷 体系化标题：{feedback['system_title']}")
    if feedback.get("theme"):
        L.append(f"📖 本篇主题：{feedback['theme']}")
    L.append("")
    cov = feedback.get("coverage") or []
    if cov:
        L.append(f"## 知识点覆盖 {coverage_ratio(feedback):.0%}")
        L.append("")
        for c in cov:
            mark = {"covered": "✅", "partial": "🟡", "missing": "⚪"}.get(c.get("status"), "•")
            L.append(f"- {mark} `{c.get('id')}`　{c.get('why', '')}")
        L.append("")
    if feedback.get("preview"):
        L.append("## 📌 本篇预告")
        L.append("")
        for p in feedback["preview"]:
            L.append(f"- {p}")
        L.append("")
    if feedback.get("glossary"):
        L.append(f"## 📚 术语表（{len(feedback['glossary'])} 条）")
        L.append("")
        for g in feedback["glossary"]:
            L.append(f"- **{g.get('term')}**：{g.get('def')}")
        L.append("")
    if feedback.get("errors"):
        L.append("## ❌ 错误（带依据）")
        L.append("")
        for e in feedback["errors"]:
            L.append(f"- 「{e.get('quote', '')[:44]}」　依据：{e.get('reasoning', '')}")
        L.append("")
    if feedback.get("uncertain"):
        L.append("## ❓ 待你核对（无依据不硬判）")
        L.append("")
        for u in feedback["uncertain"]:
            L.append(f"- 「{u.get('quote', '')[:44]}」　{u.get('reason', '')}")
        L.append("")
    todo = list(feedback.get("todo") or [])
    if queued:
        todo += [f"知识点未覆盖：{k}" for k in queued]
    if todo:
        L.append("## 🔧 查缺补漏")
        L.append("")
        for t in dict.fromkeys(todo):
            L.append(f"- [ ] {t}")
        L.append("")
    if feedback.get("summary"):
        L.append("## 总评")
        L.append("")
        L.append(feedback["summary"])
        L.append("")
    if payload:
        L.append("---")
        L.append(f"note 维度 {payload['note_dimension']:.4f}"
                 f"｜覆盖 {payload['coverage_ratio']:.0%}"
                 f"｜术语 {payload['glossary_count']} 条")
    if version_path:
        L.append(f"版本快照：{version_path}")
    return "\n".join(L)
