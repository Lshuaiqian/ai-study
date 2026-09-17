"""gate · 掌握度模型与门禁判定（纯逻辑，无网络依赖，可单元测试）。

对应 S4 定案（docs/AI辅助学习-App-可行性深化（S4定案版）.md §2）：
  D1 四维加权：mastery = 0.35·code + 0.25·quiz + 0.20·note + 0.20·transfer
  D2 门禁：mastery ≥ 0.85 且 min(四维) ≥ 0.6 且 无 fatal 且 必会知识点覆盖 100%
  D3 逃生阀：未通过时可"带疑点前进"，但【存在致命误解时不允许】
  D4 未过三级处理：L1 补练 → L2 降粒度 → L3 换表征
  D5 回炉：后续暴露前置漏洞 → 该原子 mastery ×0.7 并重回复习队列
"""

DIMENSIONS = ("code", "quiz", "note", "transfer")

WEIGHTS = {
    "code": 0.35,
    "quiz": 0.25,
    "note": 0.20,
    "transfer": 0.20,
}

DEFAULT_GATE = {
    "min_mastery": 0.85,
    "min_each": 0.60,
    "require_transfer": True,
    "min_practice_lines": 0,
}

DIM_LABEL = {
    "code": "代码实践",
    "quiz": "知识点自检",
    "note": "笔记质量",
    "transfer": "迁移应用",
}


def compute_mastery(dims):
    """四维加权总分。缺失维度按 0 计，并在 clamp 到 [0,1]。"""
    total = 0.0
    for name, w in WEIGHTS.items():
        v = dims.get(name, 0.0)
        v = 0.0 if v is None else max(0.0, min(1.0, float(v)))
        total += w * v
    return round(total, 4)


def evaluate(dims, gate=None, *, fatal=False, must_cover_ratio=1.0,
             practice_lines=None):
    """门禁判定。

    参数
      dims             四维得分 {code, quiz, note, transfer} ∈ [0,1]
      gate             门槛配置，缺省 DEFAULT_GATE
      fatal            是否存在"致命误解"（如概念性错误理解）
      must_cover_ratio 本课【必会】知识点的笔记覆盖率 ∈ [0,1]
      practice_lines   本课累计有效练习代码行数

    返回
      {mastery, passed, failures[], weak_dims[], carry_allowed, next_action_hint}
    """
    g = dict(DEFAULT_GATE)
    g.update(gate or {})

    failures = []
    weak = []

    mastery = compute_mastery(dims)

    if mastery < g["min_mastery"]:
        failures.append(f"总分 {mastery:.4f} < 门槛 {g['min_mastery']}")

    for name in DIMENSIONS:
        v = dims.get(name, 0.0) or 0.0
        if v < g["min_each"]:
            weak.append(name)
            failures.append(f"{DIM_LABEL[name]}({name}) {v:.2f} < {g['min_each']}")

    if g.get("require_transfer") and not dims.get("transfer"):
        if "transfer" not in weak:
            weak.append("transfer")
        failures.append("本课要求完成迁移题，但尚未提交")

    if fatal:
        failures.append("存在致命误解（概念性错误），不允许带疑点前进")

    if must_cover_ratio < 1.0:
        failures.append(f"必会知识点覆盖率 {must_cover_ratio:.0%} < 100%")

    if practice_lines is not None and g.get("min_practice_lines"):
        if practice_lines < g["min_practice_lines"]:
            failures.append(
                f"练习代码量 {practice_lines} 行 < 要求 {g['min_practice_lines']} 行")

    passed = not failures

    return {
        "mastery": mastery,
        "passed": passed,
        "failures": failures,
        "weak_dims": weak,
        "carry_allowed": (not fatal) and (not passed),
        "gate": g,
    }


# ---------------- D4：未通过的三级处理 ----------------

L1, L2, L3 = "L1_补练", "L2_降粒度", "L3_换表征"

L3_METHODS = [
    "讲原理（从机制出发解释，而不是给结论）",
    "给类比（用 C/C++ 对照，如 with≈RAII、list≈vector）",
    "给可视化（画数据流 / 状态图）",
    "读真实源码（拿你自己的项目代码当教材）",
]


def next_action(result, attempt):
    """根据失败次数与薄弱维度，给出下一步处理方式。

    attempt = 本课累计失败次数（第一次失败传 1）
    """
    if result.get("passed"):
        return {"level": None, "detail": "已通过，解锁下一课"}

    weak = result.get("weak_dims") or []
    worst = None
    if weak:
        worst = min(weak, key=lambda d: (result.get("dims", {}) or {}).get(d, 0.0))

    if attempt <= 1:
        target = worst or "transfer"
        return {
            "level": L1,
            "detail": f"只补短板：针对【{DIM_LABEL.get(target, target)}】追加 1 个针对性任务，其余不重做",
            "target_dim": target,
        }

    if attempt == 2:
        return {
            "level": L2,
            "detail": "把本课拆成 2–3 个更小单元，知识点不变，逐个通过后合并结算",
            "target_dim": worst,
        }

    method = L3_METHODS[(attempt - 3) % len(L3_METHODS)]
    return {
        "level": L3,
        "detail": f"换教学表征：{method}",
        "target_dim": worst,
    }


# ---------------- D3：逃生阀 ----------------

def carry_over(lesson_id, result, point_ids, reason="user_chose"):
    """生成"带疑点前进"记录。仅在 result['carry_allowed'] 为真时可用。"""
    if not result.get("carry_allowed"):
        raise ValueError("当前不满足带疑点前进的条件（存在致命误解或已通过）")
    return {
        "lesson_id": lesson_id,
        "carried_over": True,
        "mastery_at_carry": result["mastery"],
        "points": list(point_ids),
        "reason": reason,
        "must_recheck_at": "next_lesson_start",
        "review_queue": True,
    }


# ---------------- D5：回炉 ----------------

REFLOW_FACTOR = 0.7


def reflow(mastery_state, gap_atom_ids, factor=REFLOW_FACTOR):
    """后续课程暴露前置漏洞 → 打折已通过原子的掌握度并重回复习队列。

    语义：只对【当前已通过】的原子打折。一个原子被打回、尚未补练通过之前，
    再次暴露不会重复打折（避免重复惩罚）；补练重新通过后再次暴露才会再打折。
    通过 reflow_count 可看出该知识点反复了多次。

    mastery_state 形如：
      {"atoms": {"a_py_0011": {"mastery": 0.9, "passed": True, "review_queue": False}, ...}}

    返回变更列表（便于展示"已安排 N 个回炉任务"）。
    """
    changes = []
    atoms = mastery_state.setdefault("atoms", {})
    for aid in gap_atom_ids:
        rec = atoms.get(aid)
        if not rec or not rec.get("passed"):
            continue
        # mastery 可能是 None（有证据但没量化，例如 placement 判定"已具备"）。
        # 用 `or 0.0` 而不是 get 默认值——key 存在且为 None 时 get 会返回 None，
        # 下一步乘法就炸了。
        before = rec.get("mastery") or 0.0
        after = round(before * factor, 4)
        rec["mastery"] = after
        rec["passed"] = False
        rec["review_queue"] = True
        rec["reflow_count"] = rec.get("reflow_count", 0) + 1
        changes.append({"atom_id": aid, "before": before, "after": after})
    return changes


# ---------------- note 维度：五维体检加权（D10） ----------------

NOTE_WEIGHTS = {
    "structure": 0.2,
    "coverage": 0.3,
    "accuracy": 0.3,
    "linking": 0.1,
    "own_words": 0.1,
}


def note_score(parts):
    """把笔记体检的分项折算成 note 维度得分（∈[0,1]）。"""
    total = 0.0
    for k, w in NOTE_WEIGHTS.items():
        v = parts.get(k, 0.0) or 0.0
        total += w * max(0.0, min(1.0, float(v)))
    return round(total, 4)
