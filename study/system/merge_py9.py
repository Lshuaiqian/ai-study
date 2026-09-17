#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
"""把老 9 课（py-agent-01..09）按西二考核内容补齐。

为什么要有这个脚本，而不是手改 9 个 JSON：
  1. **只追加不改号**是硬约束（mastery.json 的 `py-agent-0X:K*` 原子全指着老 id），
     手改很容易不小心重排或改号，脚本可以逐条对比强制它。
  2. **每个西二知识点必须有归宿**（mapped 或 excluded，二选一）。手写没人查，
     于是「一门课的内容悄悄没人管」这种事发生过——6 门空壳课就是这么来的。
  3. name / keywords / level 一律从西二索引**原样取**，不自撰，避免 keywords 写坏
     导致覆盖率恒 0 或恒 1（keywords 是确定性覆盖判定的唯一依据）。

用法：
    python study\\system\\merge_py9.py              # 预览（不写盘）
    python study\\system\\merge_py9.py --write      # 写 study/curriculum/*.json（先备份）
    python study\\system\\merge_py9.py --check      # 只做校验，不产出
"""
import json
import os
import shutil
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BASE = os.path.dirname(os.path.abspath(__file__))          # study/system
STUDY = os.path.dirname(BASE)                              # study
BRIDGE_DIR = os.path.join(BASE, "bridge")
SYSTEM_PATH = os.path.join(BASE, "west2-ai-2026.json")
ROUTE_PATH = os.path.join(STUDY, "route.json")
CURRICULUM_DIR = os.path.join(STUDY, "curriculum")
ARCHIVE_DIR = os.path.join(STUDY, "archive")

NEW_COURSES = ["py-agent-04", "py-agent-05", "py-agent-06",
               "py-agent-07", "py-agent-08", "py-agent-09"]
APPEND_COURSES = ["py-agent-01", "py-agent-03"]


# ---------------------------------------------------------------- 载入

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_bridges():
    """读 bridge/*.json（跳过 `_` 开头的台账文件）。"""
    out = {}
    for name in sorted(os.listdir(BRIDGE_DIR)):
        if not name.endswith(".json") or name.startswith("_"):
            continue
        data = load_json(os.path.join(BRIDGE_DIR, name))
        cid = data.get("course_id")
        if not cid:
            raise SystemExit(f"❌ {name} 没有 course_id")
        if cid in out:
            raise SystemExit(f"❌ {cid} 有两份 bridge：{name}")
        out[cid] = data
    return out


def knowledge_index(system):
    return {k["id"]: k for k in system["knowledge"]}


# ---------------------------------------------------------------- 知识点条目

def kp_from_source(kp_index, src_id, local, bridge_kp):
    """从西二索引取 name/keywords/level，绝不自撰（自撰只允许 from=null）。"""
    if src_id not in kp_index:
        raise SystemExit(f"❌ 西二索引里没有知识点 {src_id}（{local} 引用它）")
    src = kp_index[src_id]
    groups = [list(g) for g in (src.get("keywords") or [])]
    kp = {
        "id": local,
        "name": src["name"],
        "level": src.get("level", "must"),
        "keywords": groups,
        "requires": bridge_kp.get("requires") or [],
        "contrast": bridge_kp.get("contrast") or [],
        "applies_to": bridge_kp.get("applies_to") or [],
    }
    # 出处留痕：以后想知道这个知识点从哪来，不用去翻 bridge
    kp["source_knowledge"] = src_id
    return kp


def kp_self_authored(local, bridge_kp):
    """无外部来源的知识点：必须自带 name/level/keywords。"""
    for field in ("name", "level", "keywords"):
        if not bridge_kp.get(field):
            raise SystemExit(f"❌ 自撰知识点 {local} 缺 {field}")
    groups = [list(g) for g in bridge_kp["keywords"]]
    return {
        "id": local,
        "name": bridge_kp["name"],
        "level": bridge_kp["level"],
        "keywords": groups,
        "requires": bridge_kp.get("requires") or [],
        "contrast": bridge_kp.get("contrast") or [],
        "applies_to": bridge_kp.get("applies_to") or [],
        "self_authored": True,
    }


def build_knowledge(kp_index, bridge, offset=0):
    """offset：新建课为 0；追加模式传已有最大编号，新知识点从 offset+1 接着排。"""
    out = []
    for i, bk in enumerate(bridge["knowledge"], start=1):
        local = bk.get("local")
        want = f"K{offset + i}"
        if local != want:
            raise SystemExit(f"❌ {bridge['course_id']} 的 local 编号不连续："
                             f"第 {i} 条是 {local!r}，应为 {want}")
        src = bk.get("from")
        out.append(kp_self_authored(local, bk) if not src
                   else kp_from_source(kp_index, src, local, bk))
    if not out:
        raise SystemExit(f"❌ {bridge['course_id']} 没有任何知识点")
    bad = [k["id"] for k in out if not k["keywords"]]
    if bad:
        raise SystemExit(f"❌ {bridge['course_id']} 这些知识点没有 keywords，"
                         f"永远不会被判定为覆盖：{bad}")
    return out


# ---------------------------------------------------------------- 课程组装

def unlocks_of(route, cid):
    out = []
    titles = {c["course_id"]: c.get("title", c["course_id"])
              for c in route["courses"]}
    for c in route["courses"]:
        if cid in (c.get("requires") or []):
            out.append({"course_id": c["course_id"], "name": titles[c["course_id"]]})
    return out


def prerequisites_of(route, cid):
    titles = {c["course_id"]: c.get("title", c["course_id"])
              for c in route["courses"]}
    for c in route["courses"]:
        if c["course_id"] == cid:
            return [{"course_id": r, "name": titles.get(r, r),
                     "status_hint": "由图反推的课程级硬前置"}
                    for r in (c.get("requires") or [])]
    raise SystemExit(f"❌ route 里没有 {cid}")


def route_title(route, cid):
    for c in route["courses"]:
        if c["course_id"] == cid:
            return c.get("title", cid)
    raise SystemExit(f"❌ route 里没有 {cid}")


def build_new(route, kp_index, bridge):
    cid = bridge["course_id"]
    return {
        "course_id": cid,
        "route": route.get("title", ""),
        "title": route_title(route, cid),
        "goal": bridge.get("goal", ""),
        "declares": {
            "system_position": bridge.get("system_position", ""),
            "prerequisites": prerequisites_of(route, cid),
            "unlocks": unlocks_of(route, cid),
            "knowledge": build_knowledge(kp_index, bridge),
        },
        "theory": bridge.get("theory") or [],
        "self_check": bridge.get("self_check") or [],
        "tasks": bridge.get("tasks") or [],
        "materials": bridge.get("materials") or {"note": "", "atoms": []},
        "gate": bridge.get("gate") or {"min_mastery": 0.85, "min_each": 0.6,
                                       "require_transfer": True,
                                       "min_practice_lines": 100},
    }


def append_course(route, kp_index, bridge, existing):
    """给已有课程追加知识点/自检题/种子资料：**老条目逐字不动，新条目顺号接在后面。**

    只加知识点是不够的：新知识点若没有种子资料，学习库与笔记体检对它们是空的；
    没有自检题，门禁就没有东西可问。所以三样一起接。

    **必须幂等**：改完 bridge 再跑一次要能同步，而不是报「编号不连续」或者又追加一遍。
    做法是——bridge 的 local 若已存在于课程里，就走「就地更新」而不是追加；
    bridge 带来的自检题与资料一律打 `source: bridge` 标记，重跑时先摘掉旧的再加新的。
    """
    cid = bridge["course_id"]
    old_kps = list(existing["declares"]["knowledge"])
    old_ids = [k["id"] for k in old_kps]
    want = [k["local"] for k in bridge["knowledge"]]
    already = all(w in old_ids for w in want)
    add = build_knowledge(kp_index, bridge, offset=bridge_offset(cid, bridge))

    merged = json.loads(json.dumps(existing))          # 深拷贝，不动入参
    fresh = {k["id"]: k for k in add}
    if already:
        merged["declares"]["knowledge"] = [fresh.get(k["id"], k) for k in old_kps]
    else:
        merged["declares"]["knowledge"] = old_kps + add

    # 自检题：先摘掉上一轮从 bridge 带来的，再按 bridge 重新接
    sc = [q for q in (merged.get("self_check") or [])
          if q.get("source") != "bridge"]
    n = len(sc)
    for i, q in enumerate(bridge.get("self_check") or [], start=1):
        item = dict(q)
        item["id"] = f"Q{n + i}"
        item["source"] = "bridge"
        sc.append(item)
    merged["self_check"] = sc

    mats = dict(merged.get("materials") or {"note": "", "atoms": []})
    atoms = [a for a in (mats.get("atoms") or [])
             if a.get("source") != "bridge"]
    n = len(atoms)
    for i, a in enumerate((bridge.get("materials") or {}).get("atoms") or [],
                          start=1):
        item = dict(a)
        item["id"] = f"M{n + i}"
        item["source"] = "bridge"
        atoms.append(item)
    mats["atoms"] = atoms
    merged["materials"] = mats
    return merged, old_ids, add


# ---------------------------------------------------------------- 校验

def check_ledger(kp_index, bridges, problems):
    """每个西二知识点必须恰好出现在 existing / planned / excluded 三者之一。"""
    ledger = load_json(os.path.join(BRIDGE_DIR, "_index.json"))
    existing = {k: v for k, v in (ledger.get("existing") or {}).items()
                if k != "comment"}
    planned = {k: v for k, v in (ledger.get("planned") or {}).items()
               if k != "comment"}
    excluded = {k: v for k, v in (ledger.get("excluded") or {}).items()
                if k != "comment"}

    buckets = {"existing": set(existing), "planned": set(planned),
               "excluded": set(excluded)}
    for a in buckets:
        for b in buckets:
            if a < b:
                dup = sorted(buckets[a] & buckets[b])
                if dup:
                    problems.append(f"台账里 {a} 与 {b} 重复登记：{dup}")

    all_kp = set(kp_index)
    covered = set().union(*buckets.values())
    if all_kp - covered:
        problems.append(f"这些西二知识点没有归宿：{sorted(all_kp - covered)}")
    if covered - all_kp:
        problems.append(f"台账引用了不存在的西二知识点：{sorted(covered - all_kp)}")

    # existing 的目标必须真的存在于当前 curriculum 里——防止台账是编的
    live = {}
    for name in os.listdir(CURRICULUM_DIR):
        if not name.endswith(".json"):
            continue
        cur = load_json(os.path.join(CURRICULUM_DIR, name))
        cid = cur.get("course_id")
        for k in (cur.get("declares") or {}).get("knowledge") or []:
            live[f"{cid}:{k['id']}"] = k.get("name", "")
    for src, target in existing.items():
        targets = target if isinstance(target, list) else [target]
        for t in targets:
            if t not in live:
                problems.append(f"台账 existing 说 {src} → {t}，但当前课程里没有 {t}")

    # planned 必须与 bridge 实际产出一致
    in_bridges = _mapped_in_bridges(bridges)
    if in_bridges != set(planned):
        problems.append(
            f"台账 planned 与 bridge 实际来源不一致："
            f"台账多={sorted(set(planned) - in_bridges)}｜"
            f"bridge 多={sorted(in_bridges - set(planned))}")
    clash = sorted(set(excluded) & in_bridges)
    if clash:
        problems.append(f"这些知识点标了 excluded，却被 bridge 接走了：{clash}")

    planned_actual = _planned_targets(bridges)
    for src, target in planned.items():
        if target not in planned_actual.get(src, []):
            problems.append(f"台账说 {src} → {target}，但 bridge 里实际落在 "
                            f"{planned_actual.get(src) or '（没有）'}")
    return ledger, len(existing), len(planned), len(excluded)


def live_ids(cid):
    """当前课程已有的知识点 id（文件不存在时返回空）。"""
    path = os.path.join(CURRICULUM_DIR, _file_of(cid))
    if not os.path.isfile(path):
        return []
    return [k["id"] for k in load_json(path)["declares"]["knowledge"]]


def bridge_offset(cid, bridge):
    """bridge 的 local 编号基准：新建课为 0；追加课要么接在已有之后，要么已合并过。

    **生成与校验必须共用这一个函数。** 第一版两边各算一套（`append_course` 用
    「已合并就就地更新」，`_planned_targets` 用「总是接在已有之后」），
    于是第二次运行时报出「台账说 K6，实际落在 K11」这种假错误——同一件事
    算两遍，迟早会漂移。
    """
    if bridge.get("mode") != "append":
        return 0
    live = live_ids(cid)
    want = [k["local"] for k in bridge["knowledge"]]
    if want and all(w in live for w in want):
        return int(want[0][1:]) - 1          # 已合并过：就地更新，位置不变
    return max((int(i[1:]) for i in live), default=0)


def _planned_targets(bridges):
    """bridge 生成后，每个西二来源会落到哪些 py-agent:K。"""
    out = {}
    for cid, b in bridges.items():
        offset = bridge_offset(cid, b)
        for i, k in enumerate(b["knowledge"], start=1):
            if k.get("from"):
                out.setdefault(k["from"], []).append(f"{cid}:K{offset + i}")
    return out


def _mapped_in_bridges(bridges):
    return {k.get("from") for b in bridges.values() for k in b["knowledge"]
            if k.get("from")}


def _existing_max(cid):
    """追加模式首次合并时的编号基准（= 已有最大编号）。"""
    ids = live_ids(cid)
    if not ids:
        raise SystemExit(f"❌ {cid} 标了 append，但 {_file_of(cid)} 不存在或没有知识点")
    return max(int(i[1:]) for i in ids)


def _file_of(cid):
    return cid.replace("-", "_") + ".json"


def check_no_renumbering(cid, old_ids, new_kps, problems):
    """老知识点的 id 必须逐个原样保留——改号会让 mastery 原子集体失配。"""
    new_ids = [k["id"] for k in new_kps]
    if new_ids[:len(old_ids)] != old_ids:
        problems.append(f"{cid} 老知识点的 id 被改动了：{old_ids} → {new_ids}")


# ---------------------------------------------------------------- 主流程

def check_graph(results, problems):
    """把**新结果**写进临时目录建一次图，检查环、空壳课与未知引用。

    只校验「字段齐不齐」是不够的：实测出现过 py-agent-09:K4 与 K5 互相 requires，
    字段全齐、台账全对，但图里有环——门禁会死锁，两门课一个都开不了。

    必须在临时目录里用**待写入的结果**建图，不能读 study/curriculum：
    读磁盘等于校验上一轮的状态。第一版就是这么错的——它把「已修好的环」和
    「本轮才新增的跨课依赖」都报成了错误（前者是残留，后者尚未落盘）。
    """
    import tempfile
    sys.path.insert(0, STUDY)
    from graph.builder import build, load_route, load_curriculums

    tmp = tempfile.mkdtemp(prefix="mergepy9-")
    try:
        for name in os.listdir(CURRICULUM_DIR):
            if name.endswith(".json"):
                shutil.copy2(os.path.join(CURRICULUM_DIR, name),
                             os.path.join(tmp, name))
        for cid, cur in results.items():
            with open(os.path.join(tmp, _file_of(cid)), "w",
                      encoding="utf-8", newline="\n") as f:
                json.dump(cur, f, ensure_ascii=False, indent=2)
        graph = build(load_route(ROUTE_PATH), load_curriculums(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    bad = [i for i in graph["issues"]
           if i["kind"] in ("cycle", "missing_curriculum")
           or str(i["kind"]).startswith("unknown")]
    for i in bad:
        problems.append(f"体系图问题：{i}")
    return bad


def main():
    argv = sys.argv[1:]
    route = load_json(ROUTE_PATH)
    system = load_json(SYSTEM_PATH)
    kp_index = knowledge_index(system)
    bridges = load_bridges()
    problems = []

    # 1. bridge 覆盖了哪些课
    want = set(NEW_COURSES) | set(APPEND_COURSES)
    have = set(bridges)
    if want - have:
        problems.append(f"这些课还没有 bridge：{sorted(want - have)}")
    if have - want:
        problems.append(f"多了不该有的 bridge：{sorted(have - want)}")

    # 2. 台账完整性
    ledger, n_existing, n_planned, n_excluded = check_ledger(kp_index, bridges, problems)

    # 3. 组装
    results, keeps = {}, {}
    for cid in NEW_COURSES:
        if cid in bridges:
            results[cid] = build_new(route, kp_index, bridges[cid])
    for cid in APPEND_COURSES:
        if cid in bridges:
            path = os.path.join(CURRICULUM_DIR, _file_of(cid))
            existing = load_json(path)
            merged, old_ids, add = append_course(
                route, kp_index, bridges[cid], existing)
            for k in existing["declares"]["knowledge"]:
                keeps[k["id"]] = k
            check_no_renumbering(cid, old_ids, merged["declares"]["knowledge"],
                                 problems)
            results[cid] = merged

    # 4. 生成后的自检
    for cid, cur in results.items():
        kps = cur["declares"]["knowledge"]
        must = [k for k in kps if k.get("level") == "must"]
        if not must:
            problems.append(f"{cid} 一个必会知识点都没有——门禁会永远放行")
        for k in kps:
            if not k.get("keywords"):
                problems.append(f"{cid}:{k['id']} 没有 keywords")
        if not cur.get("self_check"):
            problems.append(f"{cid} 没有自检题")
        if not cur.get("tasks"):
            problems.append(f"{cid} 没有任务")
        n3 = [q.get("id") for q in cur["self_check"] if len(q.get("points") or []) != 3]
        if n3:
            problems.append(f"{cid} 这些自检题不是 3 个采分点：{n3}")

    print(f"内容来源：西二 {len(kp_index)} 个知识点 → "
          f"老课已覆盖 {n_existing}｜新增 {n_planned}｜排除 {n_excluded}")
    print(f"bridge：{len(bridges)} 份（新建 {len(NEW_COURSES)}｜追加 {len(APPEND_COURSES)}）")
    for cid in sorted(results):
        kps = results[cid]["declares"]["knowledge"]
        mode = "追加" if cid in APPEND_COURSES else "新建"
        print(f"  {cid}  {mode}  知识点 {len(kps)}  "
              f"self_check {len(results[cid]['self_check'])}  "
              f"tasks {len(results[cid]['tasks'])}")

    if problems:
        print("\n❌ 校验未通过：")
        for p in problems:
            print("   · " + p)
        return 1

    # 5. 建图自检：不能有环、不能有空壳课、不能有未知引用
    #    只校验「字段齐不齐」是不够的——实测出现过 py-agent-09:K4 ↔ K5 互相 requires，
    #    字段全齐但图里有环，门禁会死锁（哪一门都开不了）。生成阶段就必须拦住。
    graph_problems = check_graph(results, problems)
    if graph_problems:
        print("\n❌ 建图校验未通过：")
        for p in problems:
            print("   · " + p)
        return 1

    print("\n✅ 校验通过：台账无漏项、老 id 未改号、keywords/自检/任务齐全、体系图无环")

    if "--check" in argv:
        return 0
    if "--write" not in argv:
        print("\n（预览模式，未写盘。加 --write 落盘，会先备份到 study/archive/）")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(ARCHIVE_DIR, f"curriculum-{stamp}")
    os.makedirs(backup, exist_ok=True)
    for cid in results:
        src = os.path.join(CURRICULUM_DIR, _file_of(cid))
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(backup, _file_of(cid)))
    for cid, cur in results.items():
        dst = os.path.join(CURRICULUM_DIR, _file_of(cid))
        with open(dst, "w", encoding="utf-8", newline="\n") as f:
            json.dump(cur, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"  写入 {dst}")
    print(f"\n✅ 已写盘。旧文件备份在 {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
