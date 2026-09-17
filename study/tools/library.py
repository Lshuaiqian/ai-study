#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""学习库（知识原子）CLI。

用法：
    :: 把课程 JSON 里人工写的种子原子导入知识库（human-authored，直接 confirmed）
    E:\\Develop\\python\\python.exe study\\tools\\library.py import-seed

    :: 从一个真实文件抽取候选（会调用模型；引文由程序验证，未通过的进 rejects）
    E:\\Develop\\python\\python.exe study\\tools\\library.py extract --course py-agent-03 ^
        --file study\\demo\\lesson3_transfer_note.md --kind note

    :: 查看 / 确认 / 拒绝
    E:\\Develop\\python\\python.exe study\\tools\\library.py list --status pending
    E:\\Develop\\python\\python.exe study\\tools\\library.py confirm a_xxxx a_yyyy
    E:\\Develop\\python\\python.exe study\\tools\\library.py reject a_zzzz --reason "不是知识点"

    :: 覆盖度（必会知识点有没有资料支撑）
    E:\\Develop\\python\\python.exe study\\tools\\library.py cover --course py-agent-03
"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.config import load_config                                # noqa: E402
from core.llm import LLM                                           # noqa: E402
from core.store import read_text                                   # noqa: E402
from library import (append_atoms, dedupe, extract_candidates,     # noqa: E402
                     find_near_duplicates, global_stats, load_atoms,
                     render_duplicates, render_view, set_status, to_atoms)
from library.store import STATUS_CONFIRMED, STATUS_PENDING         # noqa: E402
from library.view import course_view                               # noqa: E402

ATOMS_PATH = os.path.join(BASE, "library", "atoms.jsonl")
REJECTS_PATH = os.path.join(BASE, "library", "rejects.jsonl")
CURRICULUM_DIR = os.path.join(BASE, "curriculum")


def _arg(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def load_curriculum(course_id):
    for name in sorted(os.listdir(CURRICULUM_DIR)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(CURRICULUM_DIR, name), encoding="utf-8") as f:
            data = json.load(f)
        if data.get("course_id") == course_id:
            return data
    raise SystemExit(f"找不到课程 {course_id}")


# ---------------- 子命令 ----------------

def cmd_import_seed():
    """把课程 JSON 里人工撰写的 materials.atoms 导入知识库（直接 confirmed）。"""
    all_new = []
    for name in sorted(os.listdir(CURRICULUM_DIR)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(CURRICULUM_DIR, name)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        cid = data.get("course_id")
        mats = (data.get("materials") or {}).get("atoms") or []
        for m in mats:
            text = m.get("text") or ""
            all_new.append({
                "atom_id": f"a_seed_{cid.replace('-', '_')}_{m['id']}",
                "type": m.get("type") or "concept",
                "title": (m.get("title") or text[:24]).strip(),
                "statement": text.strip(),
                "why": "",
                "knowledge_id": m.get("knowledge_id") or "",
                "course": cid,
                "lang": "python",
                "source": {"kind": "material",
                           "ref": f"curriculum/{name}#{m['id']}",
                           "quote": "", "verified": True, "confidence": 1.0,
                           "authority": "authoritative",
                           "human_authored": True},
                "prerequisites": [], "related": [], "contrast": [],
                "mastery": 0.0, "status": STATUS_CONFIRMED, "tags": ["seed"],
            })
    existing = load_atoms(ATOMS_PATH)
    fresh, dup = dedupe(all_new, existing)
    append_atoms(ATOMS_PATH, fresh)
    print(f"导入种子原子：新增 {len(fresh)}，已存在跳过 {len(dup)}")
    for a in fresh:
        print(f"  + {a['atom_id']}  [{a['course']}] {a['title'][:40]}")
    return 0


def cmd_extract(argv):
    course_id = _arg(argv, "--course")
    file_path = _arg(argv, "--file")
    kind = _arg(argv, "--kind", "note")
    if not (course_id and file_path):
        print("用法：extract --course <id> --file <path> [--kind material|note|web|code]")
        return 2

    curriculum = load_curriculum(course_id)
    text = read_text(file_path)
    if not text.strip():
        print(f"文件为空或不可读：{file_path}")
        return 2
    ref = os.path.relpath(os.path.abspath(file_path), BASE).replace("\\", "/")

    llm = LLM(load_config())
    print(f"抽取：{course_id} ← {ref}（{len(text)} 字符，kind={kind}）")
    res = extract_candidates(llm, curriculum, text, ref)
    print(f"模型给出 {res['raw_count']} 条候选｜引文验证通过 {len(res['verified'])}"
          f"｜被拒 {len(res['rejected'])}")

    atoms = to_atoms(res["verified"], course_id, source_kind=kind, source_ref=ref)
    existing = load_atoms(ATOMS_PATH)
    fresh, dup = dedupe(atoms, existing)
    append_atoms(ATOMS_PATH, fresh)
    if res["rejected"]:
        append_atoms(REJECTS_PATH, res["rejected"])

    print(f"\n新增 pending 原子 {len(fresh)}（重复跳过 {len(dup)}）：")
    for a in fresh:
        print(f"  + {a['atom_id']} [{a['type']}] {a['title'][:44]}")
        print(f"      {a['statement'][:70]}")
        print(f"      出处：{a['source']['quote'][:50]}")
    if res["rejected"]:
        print(f"\n被拒候选 {len(res['rejected'])} 条（引文未在原文找到 / 引文过短）：")
        for r in res["rejected"][:8]:
            print(f"  - {str(r.get('title'))[:30]}｜{r.get('reason')}")

    if fresh:
        pairs = find_near_duplicates(load_atoms(ATOMS_PATH), course_id=course_id)
        if pairs:
            print()
            print(render_duplicates(pairs))
    print()
    print(llm.report())
    print("\n下一步：library.py confirm <id...> 才会真正生效")
    return 0


def cmd_dupes(argv):
    course_id = _arg(argv, "--course", "py-agent-03")
    atoms = load_atoms(ATOMS_PATH)
    threshold = float(_arg(argv, "--threshold", 0.55))
    pairs = find_near_duplicates(atoms, threshold=threshold, course_id=course_id)
    print(render_duplicates(pairs))
    return 0


def cmd_list(argv):
    status = _arg(argv, "--status", STATUS_PENDING)
    atoms = load_atoms(ATOMS_PATH)
    items = [a for a in atoms.values() if a.get("status") == status]
    print(f"{status} 原子 {len(items)} 个")
    for a in sorted(items, key=lambda x: x["atom_id"]):
        print(f"  {a['atom_id']}  [{a['course']}] [{a['type']}] {a['title'][:40]}")
        if a.get("source", {}).get("quote"):
            print(f"      出处引文：{a['source']['quote'][:60]}")
    return 0


def cmd_set_status(argv, status):
    ids = [x for x in argv if x.startswith("a_")]
    if not ids:
        print("需要提供至少一个 atom_id")
        return 2
    reason = _arg(argv, "--reason", "")
    changed = set_status(ATOMS_PATH, ids, status, reason)
    print(f"已把 {len(changed)} 个原子标记为 {status}")
    for c in changed:
        print(f"  {c['atom_id']}  {c['title'][:40]}")
    return 0


def cmd_map(argv):
    """把原子人工挂到某个知识点上（unmapped 队列的收口动作）。"""
    ids = [x for x in argv if x.startswith("a_")]
    kid = _arg(argv, "--knowledge", "")
    if not (ids and kid):
        print("用法：map <atom_id...> --knowledge K4")
        return 2
    from library import update_atom
    n = 0
    for aid in ids:
        rec = update_atom(ATOMS_PATH, aid, knowledge_id=kid)
        if rec:
            n += 1
            print(f"  {aid} → {kid}  {rec['title'][:40]}")
    print(f"已挂载 {n} 个原子到 {kid}")
    return 0


def cmd_cover(argv):
    course_id = _arg(argv, "--course", "py-agent-03")
    atoms = load_atoms(ATOMS_PATH)
    print(render_view(load_curriculum(course_id), atoms))
    print()
    print(global_stats(atoms))
    return 0


def cmd_stats():
    print(global_stats(load_atoms(ATOMS_PATH)))
    v = course_view(load_curriculum("py-agent-03"), load_atoms(ATOMS_PATH))
    print(f"\npy-agent-03 必会覆盖 {v['must_covered']}/{v['must_total']}"
          f"（{v['must_ratio']:.0%}）")
    return 0


def show_help():
    print(__doc__)


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        show_help()
        return 0
    cmd = argv[0]
    if cmd == "import-seed":
        return cmd_import_seed()
    if cmd == "extract":
        return cmd_extract(argv)
    if cmd == "list":
        return cmd_list(argv)
    if cmd == "confirm":
        return cmd_set_status(argv, STATUS_CONFIRMED)
    if cmd == "reject":
        return cmd_set_status(argv, "rejected")
    if cmd == "map":
        return cmd_map(argv)
    if cmd == "dupes":
        return cmd_dupes(argv)
    if cmd == "cover":
        return cmd_cover(argv)
    if cmd == "stats":
        return cmd_stats()
    print(f"未知子命令：{cmd}\n")
    show_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
