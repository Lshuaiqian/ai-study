"""library · 知识原子存储。

append-only JSONL：每次写入追加一条完整记录，读取时按 atom_id 折叠取最新。
好处：崩溃安全、可审计（能看到某个原子被改过几次）、可随时删除重建课程视图。

原子 id 用【内容哈希】：对同一份资料重复抽取不会产生重复原子。
"""
import hashlib
import json
import os
from datetime import datetime

STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED = "rejected"

ATOM_TYPES = {"concept", "example", "exercise", "pitfall", "api", "formula"}
SOURCE_KINDS = {"material", "web", "code", "note", "feishu"}


def make_atom_id(course_id, title, quote):
    """内容哈希做 id —— 同一资料重复抽取天然幂等。"""
    raw = f"{course_id}|{title}|{quote}"
    return "a_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def load_atoms(path):
    """读取并折叠为 {atom_id: atom}（同一 id 以最后一条为准）。"""
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            aid = rec.get("atom_id")
            if aid:
                out[aid] = rec
    return out


def append_atoms(path, atoms):
    """批量追加。返回实际写入条数。"""
    if not atoms:
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for a in atoms:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    return len(atoms)


def update_atom(path, atom_id, **fields):
    """在现有原子上打补丁（追加一条新记录）。原子不存在时返回 None。"""
    atoms = load_atoms(path)
    cur = atoms.get(atom_id)
    if cur is None:
        return None
    nxt = dict(cur)
    nxt.update(fields)
    nxt["updated_at"] = datetime.now().isoformat(timespec="seconds")
    append_atoms(path, [nxt])
    return nxt


def set_status(path, atom_ids, status, reason=""):
    """批量改状态（人工确认 / 拒绝）。返回变更列表。"""
    atoms = load_atoms(path)
    changed = []
    for aid in atom_ids:
        if aid not in atoms:
            continue
        rec = update_atom(path, aid, status=status, status_reason=reason,
                          confirmed_at=datetime.now().isoformat(timespec="seconds")
                          if status == STATUS_CONFIRMED else None)
        changed.append(rec)
    return changed


def stats(atoms):
    by_status, by_type, by_course, by_kind = {}, {}, {}, {}
    for a in atoms.values():
        by_status[a.get("status")] = by_status.get(a.get("status"), 0) + 1
        by_type[a.get("type")] = by_type.get(a.get("type"), 0) + 1
        by_course[a.get("course")] = by_course.get(a.get("course"), 0) + 1
        by_kind[(a.get("source") or {}).get("kind")] = \
            by_kind.get((a.get("source") or {}).get("kind"), 0) + 1
    return {"total": len(atoms), "by_status": by_status, "by_type": by_type,
            "by_course": by_course, "by_source_kind": by_kind}


def confirmed(atoms, course_id=None):
    out = [a for a in atoms.values()
           if a.get("status") == STATUS_CONFIRMED]
    if course_id:
        out = [a for a in out if a.get("course") == course_id]
    return sorted(out, key=lambda a: a["atom_id"])


def validate(atom):
    """入库前的结构校验。返回问题列表（空表示合法）。"""
    problems = []
    if not atom.get("atom_id"):
        problems.append("缺少 atom_id")
    if atom.get("type") not in ATOM_TYPES:
        problems.append(f"非法 type: {atom.get('type')}")
    if not (atom.get("title") or "").strip():
        problems.append("缺少 title")
    if not (atom.get("statement") or "").strip():
        problems.append("缺少 statement")
    src = atom.get("source") or {}
    if src.get("kind") not in SOURCE_KINDS:
        problems.append(f"非法 source.kind: {src.get('kind')}")
    if not (src.get("ref") or "").strip():
        problems.append("缺少 source.ref（无出处的原子不许入库）")
    if not src.get("verified"):
        problems.append("source.verified 为假（引文未在原文中找到）")
    return problems
