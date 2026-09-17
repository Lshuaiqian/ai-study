#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
"""把花笺里的课程笔记**重建**成老 9 课体系。

为什么需要重建而不是改名：骨架从「西二 11 门课」换成了「老 9 课」，
旧笔记（F0-…、ST-…）在新体系里没有对应课程，留着只会两边都乱。

三件事：

1. **归档而不是删除**：旧笔记整篇移到 `study/archive/huajian-<时间戳>/`，
   花笺里不再显示，但文件还在。F0 那篇有你自己写的笔记和 AI 整理稿，
   删掉是不可逆的，移走是可逆的。
2. **按课序排列**：花笺的列表是 `sort_by_key(Reverse(updated_at))`——按修改时间
   倒序。所以让**第 1 课的 updatedAt 最大、第 9 课最小**，列表就是 L1→L9 从上到下。
   同时把文件 mtime 也设成同一时刻：花笺在 metadata 缺失时会按 mtime 重建索引，
   两边一致才不会一重建就乱。
3. 顺序由 `topo_courses` 决定（前置关系说了算），不靠手写名单。

用法：
    python study\\tools\\rebuild_huajian.py            # 预览
    python study\\tools\\rebuild_huajian.py --apply    # 执行（会先归档旧笔记）
"""
import json
import os
import shutil
import sys
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # study
sys.path.insert(0, BASE)

from notes import discover, load_metadata, scan, write_note          # noqa: E402
from notes.huajian import make_entry, note_path                       # noqa: E402
from system import (CODE_LABEL, load_active, load_placement,         # noqa: E402
                    topo_courses)
from tools.scaffold import build_plan                                 # noqa: E402

PLACEMENT = os.path.join(BASE, "system", "placement-py9.json")
ARCHIVE = os.path.join(BASE, "archive")
FOLDER = "西二AI-2026"
# 时间戳基准：用**当前时刻**，让刚重建的课程笔记成为最新的那一批，
# 于是它们排在花笺列表顶部、按 L1→L9 顺序连着（花笺是按修改时间倒序的）。
# 不固定成某个常量：固定成过去的时间点会让课程笔记被压在旧笔记下面，
# 实测第一次用的 2026-01-01 就出现了「自己的笔记浮在课程笔记之上」。
BASE_TIME = datetime.now()


def timestamp_for(index):
    """第 index 篇（从 1 数）的时间戳：序号越小越新。"""
    return (BASE_TIME - timedelta(minutes=index)).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def main():
    argv = sys.argv[1:]
    active = load_active(BASE)
    placement = load_placement(PLACEMENT)
    plan = build_plan(active, FOLDER, False, placement)
    d = discover()
    notes_dir = d["notes_dir"]

    print(f"花笺 notesDir：{notes_dir}")
    print(f"数据目录：{d['data_dir']}")
    existing = scan(notes_dir)
    # **只动课程文件夹里的笔记**。notesDir 根目录与「日常」里是使用者自己的笔记，
    # 归档它们等于把人家的东西从应用里拿走——那不是重建，是破坏。
    to_archive = [n for n in existing if n["category"] == FOLDER]
    others = [n for n in existing if n["category"] != FOLDER]
    print(f"现有笔记 {len(existing)} 篇："
          f"本课程文件夹 {len(to_archive)} 篇，其他分类 {len(others)} 篇（不动）")
    for n in others:
        print(f"   🔒 保留（非课程笔记）：[{n['category'] or '根目录'}] "
              f"{n['title'] or n['file_name']}")
    for n in to_archive:
        print(f"   📦 将归档：{n['title']}")

    print(f"\n将重建 {len(plan)} 篇：")
    for i, item in enumerate(plan, start=1):
        print(f"  {i:2d}. [{item['category']}] {item['title']}  ({len(item['content'])} 字)")

    if "--apply" not in argv:
        print("\n（预览，未写盘。加 --apply 执行）")
        return 0

    # ---- 归档旧课程笔记（其他分类一律不碰）----
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    arch = os.path.join(ARCHIVE, f"huajian-{stamp}")
    os.makedirs(arch, exist_ok=True)
    moved, archived_ids = [], set()
    for n in to_archive:
        rel = os.path.relpath(n["path"], notes_dir)
        dst = os.path.join(arch, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(n["path"], dst)
        moved.append(rel)
        if n["id"]:
            archived_ids.add(n["id"])
        print(f"  📦 归档 {rel}")
    if moved:
        print(f"  （{len(moved)} 篇已移到 {arch}，没有删除）")

    # ---- 写新笔记 ----
    entries = []
    for i, item in enumerate(plan, start=1):
        note_id, path = write_note(notes_dir, item["title"], item["content"],
                                   item["category"])
        ts = timestamp_for(i)
        entry = make_entry(note_id, item["title"], os.path.basename(path),
                           item["category"], item["content"])
        entry["createdAt"] = ts
        entry["updatedAt"] = ts          # 花笺按它倒序排 → L1 在最上面
        entries.append(entry)
        # 文件 mtime 也设成同一时刻：花笺按 mtime 重建索引时顺序不变
        epoch = (BASE_TIME - timedelta(minutes=i)).timestamp()
        os.utime(path, (epoch, epoch))
        print(f"  ✅ {item['title']}")

    # ---- 写 metadata：保留使用者的其他笔记，只替换课程那部分 ----
    meta_path = os.path.join(d["data_dir"], "metadata.json")
    old_meta = (load_metadata(d["data_dir"]).get("notes") or [])
    # 被归档的课程笔记从索引里去掉；其他分类原样留着——只写新 11 条会让
    # 使用者自己的笔记在花笺里凭空消失（list_notes 会把索引里没有的文件当不存在）
    kept = [e for e in old_meta if e.get("id") not in archived_ids]
    # 顺手清掉指向已不存在文件的陈旧索引：花笺的 list_notes 会把这类条目过滤掉，
    # 但它们留在 metadata.json 里，"应用里到底有什么"就会对不上。
    #
    # 坑：花笺的 metadata 是 **camelCase**（`fileName` / `updatedAt`）。
    # 第一版读的是 snake_case `file_name` → 一律取到 None → 把使用者的笔记
    # 全判成陈旧索引删掉了。文件还在磁盘上，但索引里没了。所以两个键都读。
    def _file_name_of(e):
        return e.get("fileName") or e.get("file_name")

    def _alive(e):
        name = _file_name_of(e)
        if not name:
            return False
        return os.path.isfile(note_path(notes_dir, name, e.get("category", "")))
    stale = [e for e in kept if not _alive(e)]
    kept = [e for e in kept if _alive(e)]
    if stale:
        print(f"  🧹 清理 {len(stale)} 条陈旧索引（文件已不存在）："
              f"{[e.get('title') or _file_name_of(e) for e in stale]}")
    if os.path.isfile(meta_path):
        shutil.copy2(meta_path, f"{meta_path}.bak-{stamp}")
    tmp = meta_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"notes": kept + entries}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, meta_path)
    print(f"\n✅ 已重建 {len(entries)} 篇（索引里另有 {len(kept)} 篇非课程笔记保留）"
          f"\n   旧笔记归档在 {arch}")

    # ---- 自检 1：花笺会怎么排 ----
    listed = sorted(entries, key=lambda e: e["updatedAt"], reverse=True)
    order = [e["title"] for e in listed]
    expect = [item["title"] for item in plan]
    if order != expect:
        print("❌ 排序自检失败：花笺显示顺序与课序不一致")
        for a, b in zip(order, expect):
            if a != b:
                print(f"   实际 {a}  ←→  期望 {b}")
        return 1
    print("✅ 排序自检：花笺列表顺序 = 课序（L1 在最上）")
    for i, t in enumerate(order, start=1):
        print(f"  {i:2d}. {t}")

    # ---- 自检 2：CLI 能不能按代号找回每一课 ----
    from tools.tidy import find_note
    fresh = scan(notes_dir)
    bad = [cid for cid in topo_courses(active)
           if find_note(notes_dir, cid) is None]
    for cid in topo_courses(active):
        n = find_note(notes_dir, cid)
        assert n is not None, cid
    if bad:
        print(f"❌ 找不到这些课的笔记：{bad}")
        return 1
    print(f"✅ 定位自检：{len(topo_courses(active))} 门课都能按 "
          f"L1..L9 代号找回自己的笔记")
    return 0


if __name__ == "__main__":
    sys.exit(main())
