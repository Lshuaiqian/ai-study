"""library · 课程视图：原子 ↔ 知识点的映射与覆盖度。

对应系统设计 §4 的第三层：**课程视图只引用 atom_id，不复制内容**。
本模块回答一个很实际的问题：
    "这门课的每个必会知识点，我在学习库里到底有没有可引用的资料？"
覆盖度低的知识点，就是学习库最该补的地方。
"""
from .store import STATUS_CONFIRMED, stats


def course_view(curriculum, atoms, include_pending=False):
    course_id = curriculum.get("course_id")
    pool = []
    for a in atoms.values():
        if a.get("course") != course_id:
            continue
        if not include_pending and a.get("status") != STATUS_CONFIRMED:
            continue
        pool.append(a)

    by_kp, unmapped = {}, []
    for a in sorted(pool, key=lambda x: x["atom_id"]):
        kid = a.get("knowledge_id")
        if kid:
            by_kp.setdefault(kid, []).append(a["atom_id"])
        else:
            unmapped.append(a["atom_id"])

    knowledge = (curriculum.get("declares") or {}).get("knowledge") or []
    coverage = {}
    for kp in knowledge:
        ids = by_kp.get(kp["id"], [])
        coverage[kp["id"]] = {
            "name": kp["name"],
            "level": kp.get("level", "must"),
            "atoms": ids,
            "count": len(ids),
            "covered": bool(ids),
        }

    must = [k["id"] for k in knowledge if k.get("level", "must") == "must"]
    covered_must = [k for k in must if coverage[k]["covered"]]
    return {
        "course_id": course_id,
        "total_atoms": len(pool),
        "by_knowledge": by_kp,
        "unmapped": unmapped,
        "coverage": coverage,
        "must_total": len(must),
        "must_covered": len(covered_must),
        "must_ratio": round(len(covered_must) / len(must), 4) if must else 1.0,
        "missing_must": [k for k in must if not coverage[k]["covered"]],
    }


def as_materials(atoms, course_id=None, include_pending=False,
                 authoritative_only=False):
    """把原子转成笔记医生需要的 [{id, text}] 形式。

    authoritative_only=True 时只保留权威原子（教材/文档/人工种子）。
    笔记医生的"准确"维度必须用这个模式：拿学生自己笔记抽出的原子
    去判定他的笔记有错，是循环论证。
    """
    out = []
    for a in sorted(atoms.values(), key=lambda x: x["atom_id"]):
        if course_id and a.get("course") != course_id:
            continue
        if not include_pending and a.get("status") != STATUS_CONFIRMED:
            continue
        if authoritative_only and (a.get("source") or {}).get("authority") != "authoritative":
            continue
        text = a.get("statement") or ""
        if a.get("why"):
            text += f"（{a['why']}）"
        out.append({"id": a["atom_id"], "text": text})
    return out


def render_view(curriculum, atoms, include_pending=False):
    v = course_view(curriculum, atoms, include_pending)
    L = [f"📚 学习库覆盖 · {curriculum.get('title', v['course_id'])}",
         f"   已确认原子 {v['total_atoms']} 个｜必会知识点覆盖 "
         f"{v['must_covered']}/{v['must_total']}（{v['must_ratio']:.0%}）", ""]
    for kid, info in sorted(v["coverage"].items()):
        mark = "✅" if info["covered"] else ("⚠️" if info["level"] == "must" else "·")
        lvl = "必会" if info["level"] == "must" else "了解"
        L.append(f"  {mark} [{lvl}] {kid} {info['name'][:34]}  "
                 f"{info['count']} 个原子")
        for aid in info["atoms"][:3]:
            L.append(f"        - {aid} {atoms[aid]['title'][:38]}")
    if v["unmapped"]:
        L.append(f"\n  未挂到任何知识点的原子 {len(v['unmapped'])} 个："
                 + "、".join(v["unmapped"][:6]))
    if v["missing_must"]:
        L.append(f"\n  ⚠️ 必会知识点还没有资料支撑：{'、'.join(v['missing_must'])}")
        L.append("     → 这就是学习库最该补的地方（笔记医生的『准确』维度会因此只能输出待确认）")
    return "\n".join(L)


def global_stats(atoms):
    s = stats(atoms)
    return (f"知识库总计 {s['total']} 个原子\n"
            f"  状态：{s['by_status']}\n"
            f"  类型：{s['by_type']}\n"
            f"  课程：{s['by_course']}\n"
            f"  来源：{s['by_source_kind']}")
