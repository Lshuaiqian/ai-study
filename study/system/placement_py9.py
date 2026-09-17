# -*- coding: utf-8 -*-
"""把西二的「学习位置」桥接到老 9 课的 K id 上。

为什么必须有这一步：placement-west2.json 是按**西二知识点**（`env.ide` / `net.http`）
记的，而活跃骨架是老课的**本地 K id**（`py-agent-02:K1`）。不做转换，
学习者已经具备的点在活跃体系里会显示成 `unknown`——等于让他从头学一遍，
而且「挂账」也会静默消失（这正是之前修过的 id 空间不一致那类 bug）。

映射从哪来：`bridge/_index.json` 的 `existing` 与 `planned` 两张表就是为这件事记的。
不要在这里另写一份映射——两份映射一定会漂移。

用法：
    python study\\system\\placement_py9.py            # 预览
    python study\\system\\placement_py9.py --write    # 写 study/system/placement-py9.json
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BASE = os.path.dirname(os.path.abspath(__file__))       # study/system
STUDY = os.path.dirname(BASE)
WEST2_PLACEMENT = os.path.join(BASE, "placement-west2.json")
LEDGER = os.path.join(BASE, "bridge", "_index.json")
OUT = os.path.join(BASE, "placement-py9.json")


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def invert_ledger(ledger):
    """西二知识点 → 老课 K id 列表（existing 与 planned 合起来）。"""
    mapping = {}
    for section in ("existing", "planned"):
        for src, target in (ledger.get(section) or {}).items():
            if src == "comment":
                continue
            mapping.setdefault(src, [])
            mapping[src].extend(target if isinstance(target, list) else [target])
    return mapping


def main():
    argv = sys.argv[1:]
    west2 = load(WEST2_PLACEMENT)
    ledger = load(LEDGER)
    mapping = invert_ledger(ledger)

    status_in = west2.get("knowledge_status") or {}
    status_out, unmapped_status, dropped = {}, [], []
    for src, rec in status_in.items():
        targets = mapping.get(src)
        if not targets:
            # F0 那 9 个点被显式排除：它们的判定确实没有归宿，记下来而不是假装没有
            dropped.append(src)
            continue
        for local in targets:
            status_out[local] = {
                "status": rec.get("status", "unknown"),
                "evidence": rec.get("evidence", ""),
                "from": src,
            }
    # 反向：老课里没有西二来源的知识点 → 明确记成 unknown（不是 met）
    all_local = set()
    for targets in mapping.values():
        all_local.update(targets)
    for src in mapping:
        if src not in status_in:
            unmapped_status.append(src)

    # 课程级决策：只有「本地全部知识点都有西二判定」时才可能整门迁移。
    # 老 1 有 K2/K4 这类西二没有对应的点，所以它的 fast_pass 不会自动变成
    # 「老 1 已通过」——那会把没证据的知识点一起放行。挂账则按点迁移。
    decisions = []
    for dec in west2.get("decisions") or []:
        carried_local = []
        for g in (dec.get("carried_over") or []):
            carried_local.extend(mapping.get(g) or [])
        carried_local = sorted(set(carried_local))
        # course_id 必须换成**老课** id：apply_placement 是按活跃课程的 id 查决策的，
        # 留着 west2-f1 的话这条挂账永远不会被读到（静默失效）。
        targets = {t.split(":")[0] for t in carried_local}
        if len(targets) != 1:
            continue        # 挂账跨课或无处安放（F0）→ 不作为整门课的决策迁移
        decisions.append({
            "course_id": targets.pop(),
            "decision": dec.get("decision"),
            "reason": (dec.get("reason") or "") +
                      "（原决策针对西二课表；迁移到老课后只按知识点生效，不整门放行——"
                      "老课含有西二没有对应的知识点，那些点没有证据）",
            "carried_over": carried_local,
            "recheck_at": dec.get("recheck_at", ""),
            "from_course": dec.get("course_id"),
        })

    out = {
        "note": "由 placement_py9.py 从 placement-west2.json + bridge/_index.json 派生，请勿手改。"
                "老课的知识点若在西二那里有对应点，就继承它的判定；没有对应点的记为 unknown——"
                "不知道就是不知道，不能当成已具备。",
        "source": "placement-west2.json",
        "knowledge_status": dict(sorted(status_out.items())),
        "weak_points": _weak_points(west2, mapping),
        "decisions": decisions,
        "dropped": {
            "knowledge": sorted(dropped),
            "why": "这些西二知识点按用户决定不并入老 9 课（见 bridge/_index.json 的 excluded），"
                   "它们的判定在老体系里没有归宿。",
        },
        "stats": {
            "west2_status": len(status_in),
            "migrated": len(status_out),
            "dropped": len(dropped),
        },
    }

    print(f"西二判定 {len(status_in)} 条 → 迁移 {len(status_out)} 条"
          f"｜无处安放（F0 排除）{len(dropped)} 条")
    met = sum(1 for v in status_out.values() if v["status"] == "met")
    print(f"其中 met {met} 条｜weak_points {len(out['weak_points'])} 个")
    for d in out["decisions"]:
        print(f"  决策 {d['course_id']}: {d['decision']}"
              f"｜挂账迁移 {len(d['carried_over'])} 个"
              f"（{d['carried_over']}）")

    if "--write" not in argv:
        print("\n（预览，未写盘。加 --write 落盘）")
        return 0
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n✅ 已写入 {OUT}")
    return 0


def _weak_points(west2, mapping):
    out = []
    for w in west2.get("weak_points") or []:
        for local in mapping.get(w.get("knowledge"), []):
            item = dict(w)
            item["knowledge"] = local
            item["from"] = w.get("knowledge")
            out.append(item)
    return out


if __name__ == "__main__":
    sys.exit(main())
