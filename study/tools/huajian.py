#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""花笺（floral-notepaper）连接器 CLI。

默认**只读**：info / list / read / reconcile 都不动任何文件。
写操作（new / import）需要显式加 --yes。

用法：
    python study\\tools\\huajian.py info
    python study\\tools\\huajian.py list
    python study\\tools\\huajian.py reconcile
    python study\\tools\\huajian.py read 30d7efc2
    python study\\tools\\huajian.py new --title "第3课笔记" --category 学习 --content-file notes.md --yes
    python study\\tools\\huajian.py import --course py-agent-03 --category 学习 --yes
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.store import read_text                                   # noqa: E402
from notes import (discover, load_metadata, make_entry, read_note,  # noqa: E402
                   reconcile, scan, upsert_metadata, write_note)


def _arg(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def cmd_info(argv):
    d = discover(_arg(argv, "--data-dir"))
    print("花笺数据定位")
    print(f"  data_dir     {d['data_dir']}")
    print(f"  config.json  {'存在' if os.path.isfile(d['config_path']) else '缺失'}"
          f"  {d['config_path']}")
    print(f"  notes_dir    {d['notes_dir']}  {'✅' if d['exists'] else '❌ 不存在'}")
    print(f"  metadata     {d['metadata_path']}")
    cfg = d["config"]
    for k in ("locale", "theme", "defaultViewMode", "noteAutoSave",
              "tileRenderMarkdown", "notesDir"):
        if k in cfg:
            print(f"  config.{k:22s} {cfg[k]}")
    if d["exists"]:
        notes = scan(d["notes_dir"])
        meta = load_metadata(d["data_dir"])
        print(f"\n磁盘上 .md 文件 {len(notes)} 个｜metadata 记录 {len(meta.get('notes') or [])} 条")
        cats = sorted({n['category'] for n in notes})
        print(f"分类（文件夹）：{cats if cats else '（无，全在根目录）'}")
    return 0


def cmd_list(argv):
    d = discover(_arg(argv, "--data-dir"))
    cat = _arg(argv, "--category")
    notes = scan(d["notes_dir"])
    if cat is not None:
        notes = [n for n in notes if n["category"] == cat]
    meta = load_metadata(d["data_dir"])
    known = {n["id"]: n for n in (meta.get("notes") or [])}
    print(f"共 {len(notes)} 篇")
    for n in notes:
        m = known.get(n["id"])
        flag = "✓" if m else "?"
        title = (m or {}).get("title") or n["title"] or "（无标题）"
        wc = (m or {}).get("wordCount", "-")
        print(f"  [{flag}] {(n['id'] or '非花笺')[:8]}  {title[:34]:34s} "
              f"分类={n['category'] or '(未分类)':10s} {wc} 字")
    if any(not n["id"] for n in notes):
        print("\n  ? = 文件在目录里但文件名不是花笺的 UUID 规范，花笺可能不认它")
    return 0


def cmd_read(argv):
    d = discover(_arg(argv, "--data-dir"))
    key = argv[0] if argv and not argv[0].startswith("-") else _arg(argv, "--id")
    if not key:
        print("用法：read <id 前缀 或 文件名>")
        return 2
    for n in scan(d["notes_dir"]):
        if (n["id"] or "").startswith(key) or n["file_name"] == key:
            print(f"# {n['file_name']}  [{n['category'] or '未分类'}]")
            print(f"# {n['path']}")
            print("-" * 60)
            print(read_note(n["path"]))
            return 0
    print(f"未找到：{key}")
    return 1


def cmd_reconcile(argv):
    d = discover(_arg(argv, "--data-dir"))
    r = reconcile(scan(d["notes_dir"]), load_metadata(d["data_dir"]))
    print("磁盘与 metadata.json 对照")
    print(f"  两边都有（花笺可见）      {len(r['tracked'])}")
    for i in r["tracked"]:
        print(f"      {i}")
    if r["untracked_files"]:
        print(f"  文件在但索引里没有        {len(r['untracked_files'])}"
              f"  ← 花笺下次 rebuild 才会收进来")
        for f in r["untracked_files"]:
            print(f"      {f}")
    if r["missing_files"]:
        print(f"  索引里有但文件不在        {len(r['missing_files'])}  ← 花笺会显示成空笔记")
        for i in r["missing_files"]:
            print(f"      {i}")
    if r["non_huajian_md"]:
        print(f"  不符合花笺命名规范的 .md  {len(r['non_huajian_md'])}"
              f"  ← 花笺不会把它们当笔记")
        for f in r["non_huajian_md"]:
            print(f"      {f}")
    return 0


def cmd_new(argv):
    if "--yes" not in argv:
        print("这是写操作：会在花笺笔记目录里新建 .md，并更新 metadata.json。")
        print("确认无误请加 --yes 重跑。")
        return 2
    d = discover(_arg(argv, "--data-dir"))
    title = _arg(argv, "--title", "")
    category = _arg(argv, "--category", "")
    content_file = _arg(argv, "--content-file")
    content = read_text(content_file) if content_file else _arg(argv, "--content", "")
    if not content:
        print("需要 --content 或 --content-file")
        return 2
    note_id, path = write_note(d["notes_dir"], title, content, category)
    file_name = os.path.basename(path)
    upsert_metadata(d["data_dir"], make_entry(note_id, title, file_name, category, content))
    print(f"✅ 已写入 {path}")
    print(f"   metadata.json 已更新（原文件已备份为 .bak-*）")
    print(f"   花笺里应该能看到标题「{title}」，分类「{category or '未分类'}」")
    return 0


def cmd_import(argv):
    if "--yes" not in argv:
        print("这是写操作：会调用模型抽原子并写入学习库（library/atoms.jsonl）。")
        print("确认无误请加 --yes 重跑。")
        return 2
    from core.config import load_config
    from core.llm import LLM
    from library import (append_atoms, dedupe, extract_candidates,
                         find_near_duplicates, load_atoms, render_duplicates,
                         to_atoms)

    course_id = _arg(argv, "--course", "py-agent-03")
    category = _arg(argv, "--category")
    d = discover(_arg(argv, "--data-dir"))
    notes = scan(d["notes_dir"])
    if category is not None:
        notes = [n for n in notes if n["category"] == category]
    if not notes:
        print("没有可导入的笔记")
        return 1

    import json
    curriculum = None
    cdir = os.path.join(BASE, "curriculum")
    for name in sorted(os.listdir(cdir)):
        if name.endswith(".json"):
            with open(os.path.join(cdir, name), encoding="utf-8") as f:
                data = json.load(f)
            if data.get("course_id") == course_id:
                curriculum = data
                break
    if not curriculum:
        print(f"找不到课程 {course_id}")
        return 2

    llm = LLM(load_config())
    lib_path = os.path.join(BASE, "library", "atoms.jsonl")
    total_new = 0
    for n in notes:
        text = read_note(n["path"])
        if len(text.strip()) < 20:
            continue
        ref = f"huajian:{n['file_name']}"
        res = extract_candidates(llm, curriculum, text, ref)
        atoms = to_atoms(res["verified"], course_id, source_kind="note", source_ref=ref)
        fresh, _dup = dedupe(atoms, load_atoms(lib_path))
        append_atoms(lib_path, fresh)
        total_new += len(fresh)
        print(f"  {n['file_name'][:40]:40s} 候选 {res['raw_count']}｜"
              f"引文通过 {len(res['verified'])}｜新增 {len(fresh)}")
    print(f"\n共新增 {total_new} 个 pending 原子（kind=note → derived 权威级）")
    print(render_duplicates(find_near_duplicates(load_atoms(lib_path), course_id=course_id)))
    print(llm.report())
    print("\n提示：derived 原子不能作为笔记纠错的依据（循环论证），"
          "更适合做『关联建议』。确认：library.py confirm <id...>")
    return 0


def show_help():
    print(__doc__)


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        show_help()
        return 0
    cmd = argv[0]
    rest = argv[1:]
    table = {"info": cmd_info, "list": cmd_list, "read": cmd_read,
             "reconcile": cmd_reconcile, "new": cmd_new, "import": cmd_import}
    if cmd not in table:
        print(f"未知子命令：{cmd}\n")
        show_help()
        return 2
    return table[cmd](rest)


if __name__ == "__main__":
    sys.exit(main())
