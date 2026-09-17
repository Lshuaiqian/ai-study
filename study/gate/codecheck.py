"""gate · 代码实践维度的确定性检查。

定位：P0 阶段 code 维度先用【可复现的静态检查】给出，而不是靠 LLM 自由打分。
理由：门禁要让人服气，能确定性判定的部分就不要交给模型（与笔记覆盖维度同一原则）。
真正的逐行点评仍由 Tutor 角色（复用 python-tutor 协议）负责，其结果可覆盖本分数。
"""
import re

# task acceptance 条件的机器可判定形式
DEFAULT_CRITERIA = [
    {"id": "ua", "desc": "设置了 User-Agent",
     "any": [r"User-Agent", r"user_agent", r"headers\s*="]},
    {"id": "sleep", "desc": "有限速（sleep / 间隔）",
     "any": [r"time\.sleep", r"sleep\(", r"interval", r"delay"]},
    {"id": "retry", "desc": "有异常处理与重试",
     "any": [r"try\s*:", r"except", r"retry", r"max_retries"]},
    {"id": "save", "desc": "把结果保存为 json/csv",
     "any": [r"json\.dump", r"csv\.writer", r"csv\.DictWriter", r"to_json"]},
    {"id": "stats", "desc": "打印成功/失败统计",
     "any": [r"成功", r"失败", r"success", r"failed", r"stat", r"len\("]},
    {"id": "request", "desc": "真的发起了 HTTP 请求",
     "any": [r"requests\.get", r"requests\.post", r"urlopen", r"Session\("]},
]


def count_effective_lines(source):
    """有效代码行：非空、非纯注释。"""
    n = 0
    for line in (source or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        n += 1
    return n


def analyze(source, criteria=None, min_lines=None):
    """对练习代码做确定性检查。

    返回 {score, hits[], misses[], lines, details{}}；score = 命中条件数 / 条件总数。
    """
    criteria = criteria or DEFAULT_CRITERIA
    src = source or ""
    hits, misses = [], []
    for c in criteria:
        if any(re.search(p, src, re.IGNORECASE) for p in c["any"]):
            hits.append(c["desc"])
        else:
            misses.append(c["desc"])

    total = len(criteria) or 1
    score = round(len(hits) / total, 4)
    lines = count_effective_lines(src)

    return {
        "score": score,
        "hits": hits,
        "misses": misses,
        "lines": lines,
        "meets_min_lines": (min_lines is None or lines >= min_lines),
        "min_lines": min_lines,
    }


# ---------------- code 维度的合成 ----------------
# 设计公式（系统设计 §9.1）：code = 0.6 × 任务通过率 + 0.4 × 健壮性
#   任务通过率 = 机检条件命中率（确定性）
#   健壮性     = 由 Tutor 的 findings 严重度扣分得出
#
# ⚠️ 两条被实测逼出来的约束（首版公式在这里翻了车）：
#   1) style 不扣分：风格问题不是健壮性问题。首版按 0.05 扣，导致
#      "点评越认真→warning 越多→分数越低" 的逆向激励。
#   2) 扣分必须封顶：一个好导师本来就会给出很多条改进建议。
#      若线性累加，认真的点评会被当成"代码很差"。封顶 0.5，保证
#      code 维度的下限仍由机检通过率主导（0.6×通过率 ≥ 0）。
CRITERIA_WEIGHT = 0.6
QUALITY_WEIGHT = 0.4
SEVERITY_CODE_PENALTY = {"error": 0.30, "warn": 0.08, "style": 0.0, "praise": 0.0}
MAX_QUALITY_PENALTY = 0.5


def combine_code_dimension(criteria_ratio, counts=None):
    """把机检通过率与 Tutor 点评结论合成为 code 维度得分。

    counts 形如 {"error": 1, "warn": 2, "style": 1, "praise": 1}
    """
    counts = counts or {}
    raw = sum(SEVERITY_CODE_PENALTY.get(k, 0.0) * (counts.get(k) or 0)
              for k in SEVERITY_CODE_PENALTY)
    penalty = min(raw, MAX_QUALITY_PENALTY)
    quality = max(0.0, 1.0 - penalty)
    ratio = max(0.0, min(1.0, float(criteria_ratio or 0.0)))
    return {
        "score": round(CRITERIA_WEIGHT * ratio + QUALITY_WEIGHT * quality, 4),
        "criteria_ratio": ratio,
        "review_quality": round(quality, 4),
        "penalty": round(penalty, 4),
        "penalty_raw": round(raw, 4),
        "penalty_capped": raw > MAX_QUALITY_PENALTY,
    }
