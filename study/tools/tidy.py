#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
"""一键整理：把花笺里的课程笔记整理成教材级复习稿，并把结论反馈给掌握度。

**不是覆写。** 笔记分三个区，整理只动 AI 区：

    ## ⚡ 你的起点 / ## 📋 考核要求     ← 脚手架区（可更新）
    ## ✍️ 我的笔记                     ← 你的区：AI 永不改动
    ## 🤖 AI 整理                       ← AI 区：整块替换（幂等）
    ## 📚 整理历史                      ← 追加区：只追加、不删

每次整理的整理稿落盘到 `state/note_versions/<note_id>/<时间戳>.md`，可回滚到任一版。

**预览零副作用**：不加 `--apply` 时既不写笔记，也不改掌握度、不塞回炉队列。

用法：
    python study\\tools\\tidy.py --course west2-f2                # 预览（不写）
    python study\\tools\\tidy.py --course west2-f2 --apply        # 写入（三区替换）
    python study\\tools\\tidy.py --course west2-f2 --soft --apply  # 只排版，不改语义，不调模型
    python study\\tools\\tidy.py --course west2-f2 --versions      # 看历史版本
    python study\\tools\\tidy.py --course west2-f2 --rollback 20260916-143200

给 GUI（花笺「一键整理」按钮）用的机器接口：
    python study\\tools\\tidy.py --path "<笔记绝对路径>" --apply --json

`--json` 时 **stdout 是 JSONL**（一行一个对象：stage / report / done / error），
人类可读日志改走 stderr。GUI 只读 JSON、不 grep 中文。`--path` 与 `--course`
同时给出时 `--path` 优先。

**退出码**（GUI 据此分类，不解析文本）：
    0 成功 ｜ 1 用户可理解的失败（空笔记 / 模型失败 / 写入失败）
    2 参数错（课程不存在等，属 bug） ｜ 3 不是课程笔记 / 找不到笔记
"""
import json
import os
import re
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.config import load_config                              # noqa: E402
from core.llm import LLM                                         # noqa: E402
from core.store import write_text                                # noqa: E402
from notedoctor.tidier import (build_payload, compose, compose_rollback,  # noqa: E402
                               queued_gaps, render_report, save_version,
                               soft_tidy, split_zones, tidy, user_substance,
                               write_state)
from notes import (discover, infer_title, make_entry, parse_id,  # noqa: E402
                   read_note, scan, upsert_metadata)
from system import (CODE_LABEL, course_index, load_placement,     # noqa: E402
                    load_system, protection_map, to_curriculum)

SYSTEM_PATH = None      # 运行时由 active_paths 决定（见 system/active.py）
PLACEMENT_PATH = None      # 运行时由 active_paths 决定
STATE_DIR = os.path.join(BASE, "state")


def _arg(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


# ---------------------------------------------------------------- GUI 契约
# 人类可读日志与机器可读事件分道走：`--json` 时 stdout 只放 JSONL，
# 中文日志挪到 stderr。GUI 因此永远不用 grep 中文输出。
JSON_MODE = {"on": False}


def say(*parts, **kw):
    """人类可读日志。人类模式 → stdout（既有验证脚本照旧断言 stdout）；JSON 模式 → stderr。"""
    kw.setdefault("file", sys.stderr if JSON_MODE["on"] else sys.stdout)
    print(*parts, **kw)


def emit(obj):
    """机器可读事件（JSONL）。只在 --json 模式下输出，永远走 stdout。"""
    if JSON_MODE["on"]:
        print(json.dumps(obj, ensure_ascii=False), file=sys.stdout)


def emit_error(code, msg):
    emit({"type": "error", "code": code, "msg": msg})


# 课程身份标记：脚手架写在正文顶部，花笺渲染时是不可见的 HTML 注释。
#     <!-- study: course=west2-f0 stage=F0 -->
MARKER_RE = re.compile(r"<!--\s*study:([^>]*?)-->")


def parse_course_marker(text):
    """读正文里的课程标记，返回 (course_id, stage)；没有标记返回 (None, None)。

    放在正文顶部而不是 YAML frontmatter：花笺的 markdown 渲染链路对注释天然透明，
    YAML 会被当正文渲染出一条分隔线。scaffold.py 的 update 只刷新「✍️ 我的笔记」
    之前的头部，所以这行会被幂等刷新（课程代号变了也能自愈）。
    """
    m = MARKER_RE.search(text or "")
    if not m:
        return None, None
    kv = dict(re.findall(r"([A-Za-z_]\w*)\s*=\s*([^\s>]+)", m.group(1)))
    return kv.get("course") or None, kv.get("stage") or None


def _code_to_course():
    """课程代号（F0/K2…）→ course_id 的反查表。"""
    return {label: cid for cid, label in CODE_LABEL.items()}


def resolve_course_from_path(path, notes_dir=None):
    """按路径定位课程，返回 (course_id, stage, how)。

    解析顺序（每一步失败才退到下一步）：
      1. 正文顶部的 `<!-- study: course=... -->` 标记；
      2. 兼容老笔记：花笺 id + 标题前缀（`F0-环境搭建` / `F0 环境搭建`）反查；
      3. 兜底：正文首个 `# F0 · ...` 标题里的代号；
    全部失败 → (None, None, None)，调用方按「不是课程笔记」处理（退出码 3）。

    这条路径是给花笺的：用户在花笺里把标题从 `F0-环境搭建` 改成「环境搭建」
    会连带改文件名（花笺按 title 生成 stem），靠标题前缀找笔记就会失效。
    """
    try:
        text = read_note(path)
    except OSError:
        return None, None, None

    cid, stage = parse_course_marker(text)
    if cid:
        return cid, stage, "marker"

    code_map = _code_to_course()
    target = os.path.abspath(path)
    if notes_dir:
        for n in scan(notes_dir):
            if os.path.abspath(n["path"]) != target:
                continue
            title = (n["title"] or "").strip()
            for sep in ("-", " "):
                if sep in title:
                    prefix = title.split(sep, 1)[0].strip()
                    if prefix in code_map:
                        return code_map[prefix], None, "title-prefix"
                    break
            break

    # 标题被改得面目全非时，正文首个标题通常还留着代号
    m = re.search(r"^#\s*([A-Za-z]+\d+)\b", text, re.M)
    if m and m.group(1) in code_map:
        return code_map[m.group(1)], None, "heading"
    return None, None, None


def find_note_by_path(notes_dir, path):
    """在 scan() 结果里按绝对路径取笔记条目；不在 notesDir 下时返回 None。"""
    target = os.path.abspath(path)
    for n in scan(notes_dir):
        if os.path.abspath(n["path"]) == target:
            return n
    return None


def synthesize_note(path):
    """为「不在花笺 notesDir 下」的 Markdown 造一个最小笔记条目（--path 专用）。

    仍然允许整理，只是花笺的 metadata 不会被更新成花笺索引之外的路径。
    """
    name = os.path.basename(path)
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    return {
        "id": parse_id(name),
        "file_name": name,
        "title": infer_title(name, read_note(path)),
        "category": "",
        "path": path,
        "size": size,
        "mtime": 0,
    }


def find_note(notes_dir, course_id):
    code = CODE_LABEL.get(course_id, course_id)
    for n in scan(notes_dir):
        if n["title"].startswith(code + "-") or n["title"].startswith(code + " "):
            return n
    return None


def cmd_versions(note_id):
    d = os.path.join(STATE_DIR, "note_versions", note_id or "unknown")
    if not os.path.isdir(d):
        say(f"还没有版本快照：{d}")
        emit({"type": "versions", "note_id": note_id, "versions": []})
        return 0
    files = sorted(os.listdir(d))
    say(f"📚 版本快照（{len(files)} 份，最新在后）")
    for f in files:
        p = os.path.join(d, f)
        say(f"  {f}　{os.path.getsize(p)} 字节")
    say("\n回滚：tidy.py --course <id> --rollback <去掉 .md 的时间戳>")
    emit({"type": "versions", "note_id": note_id,
          "versions": [{"version": os.path.splitext(f)[0],
                        "bytes": os.path.getsize(os.path.join(d, f))} for f in files]})
    return 0


def cmd_rollback(note, course_id, ts, data_dir=None):
    d = os.path.join(STATE_DIR, "note_versions", note["id"] or "unknown")
    src = os.path.join(d, f"{ts}.md")
    if not os.path.isfile(src):
        say(f"❌ 找不到快照 {src}")
        emit_error("SNAPSHOT_NOT_FOUND", f"找不到快照 {src}")
        return 1
    markdown = read_note(src)
    say(f"将把 AI 整理区回滚为 {ts} 的内容（你的笔记仍然不动）")
    rc = _write_back(note, course_id, markdown, None, ts,
                     rollback=True, data_dir=data_dir)
    if rc == 0:
        emit({"type": "done", "ok": True, "course_id": course_id,
              "note_id": note["id"], "rollback": ts, "note_path": note["path"],
              "changed": {"user_zone": False, "ai_zone": "rolled-back",
                          "history_appended": 1}})
    return rc


def _write_back(note, course_id, markdown, feedback, ts, rollback=False,
                data_dir=None, version_ref=""):
    """只替换 AI 区 + 追加一行历史；用户正文一字不动。

    data_dir 必须一路传下来：`discover()` 不带参数会回到**用户真实的**花笺
    目录，用 --data-dir 做验证时会写错地方。
    """
    old = read_note(note["path"])
    zones = split_zones(old)
    if feedback is None:
        # 回滚：只换整理区，用户区与质询区原样保留
        new_text = compose_rollback(old, markdown, ts)
    else:
        new_text = compose(old, markdown, feedback, ts=ts, version_ref=version_ref)
    # 原子写：先写临时文件再替换——中途崩溃/断电不会把笔记截断成半篇
    write_text(note["path"], new_text)
    d = discover(data_dir)
    upsert_metadata(d["data_dir"], make_entry(
        note["id"] or "", note["title"], os.path.basename(note["path"]),
        note["category"], new_text))
    return 0


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    JSON_MODE["on"] = "--json" in argv

    course_id = _arg(argv, "--course")
    path_arg = _arg(argv, "--path")
    if not course_id and not path_arg:
        say("需要 --course <course_id> 或 --path <笔记路径>"
            "（可用 system.py placement 查看）")
        emit_error("MISSING_TARGET", "需要 --course <course_id> 或 --path <笔记路径>")
        return 2

    system = _active_system()
    courses = course_index(system)
    d = discover(_arg(argv, "--data-dir"))

    # ---- --path 优先：GUI 只传路径。标题改名不该让按钮失灵（P-1）----
    if path_arg:
        if not os.path.isfile(path_arg):
            say(f"❌ 找不到笔记文件：{path_arg}")
            emit_error("NOTE_NOT_FOUND", f"找不到笔记文件：{path_arg}")
            return 3
        resolved, stage, how = resolve_course_from_path(path_arg, d["notes_dir"])
        if not resolved:
            say("❌ 这不是课程笔记：正文没有课程标记，标题也匹配不上课程代号")
            say("   先跑 scaffold.py apply --yes 建立课程笔记")
            emit_error("NOT_A_COURSE_NOTE",
                       "这不是课程笔记：正文没有 <!-- study: course=... --> 标记，"
                       "标题也不匹配任何课程代号（先跑 scaffold.py apply --yes）")
            return 3
        course_id = resolved
        _src = f"（来源：{how}" + (f"，stage={stage}" if stage else "") + "）"
        say(f"🔎 已识别课程 {course_id}{_src}")
        emit({"type": "stage", "name": "load",
              "msg": f"已识别课程 {course_id}{_src}"})

    if course_id not in courses:
        say(f"没有课程 {course_id}")
        emit_error("COURSE_NOT_FOUND", f"没有课程 {course_id}")
        return 2
    curriculum = to_curriculum(system, courses[course_id],
                               _active_placement())
    # placement 已判「已具备/挂账」的点：笔记里没写到也不许摘牌
    protected = protection_map(curriculum)

    if path_arg:
        note = find_note_by_path(d["notes_dir"], path_arg) or synthesize_note(path_arg)
    else:
        note = find_note(d["notes_dir"], course_id)
    if not note:
        say(f"❌ 花笺里找不到 {course_id} 的笔记。先跑 scaffold.py apply --yes")
        emit_error("NOTE_NOT_FOUND",
                   f"花笺里找不到 {course_id} 的笔记，先跑 scaffold.py apply --yes")
        return 3
    if not path_arg:
        emit({"type": "stage", "name": "load", "msg": f"已识别课程 {course_id}"})

    if "--versions" in argv:
        return cmd_versions(note["id"])

    rb = _arg(argv, "--rollback")
    if rb:
        return cmd_rollback(note, course_id, rb, data_dir=d["data_dir"])

    apply_now = "--apply" in argv
    old = read_note(note["path"])
    zones = split_zones(old)
    # 按**实质内容**算，不按字数算：脚手架模板本身就有 200 来字，
    # 按字数会把"还没开始写"当成"有内容"，整理出一篇对模板的点评。
    notes_len = len("".join(user_substance(old).split()))
    say(f"📄 {note['title']}")
    say(f"   你的笔记 {notes_len} 字（模板注释不计）"
        f"｜已有 AI 整理区：{'是' if zones['has_ai'] else '否'}")
    if notes_len < 5:
        say("   ⚠️ 「我的笔记」还是空的或只有模板注释——先写点东西，整理才有东西可整")
        emit_error("EMPTY_NOTES",
                   "「我的笔记」还是空的或只有模板注释——先写点东西，整理才有东西可整")
        return 1

    soft = "--soft" in argv
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    if soft:
        say("   模式：软整理（只排版，不改语义，不调用模型）")
        markdown = soft_tidy(zones["user"])
        feedback = {"system_title": "", "theme": "", "preview": [],
                    "coverage": [], "glossary": [], "todo": [], "errors": [],
                    "uncertain": [], "summary": "（软整理：未做语义判断）"}
        version_path = ""
        payload, queued = None, []
    else:
        say("   ⏳ 正在整理（一次改写 + 一次结构化反馈）……")
        emit({"type": "stage", "name": "tidy",
              "msg": "正在整理（改写 + 结构化反馈）"})
        try:
            res = tidy(LLM(load_config()), curriculum, old)
        except Exception as e:  # noqa: BLE001
            # 断网 / key 失效 / 模型返回坏 JSON 都会走到这里。
            # 此刻笔记与掌握度都还没动过，直接退出去就行，不要抛栈吓人。
            say(f"   ❌ 整理失败：{type(e).__name__}: {e}")
            say("   （笔记与掌握度都没有改动，检查网络或 API key 后重跑）")
            emit_error("MODEL_FAILED", f"{type(e).__name__}: {e}")
            return 1
        markdown, feedback = res["markdown"], res["feedback"]
        if apply_now:
            # 落盘只发生在 --apply：预览不改掌握度、不写快照、不塞回炉队列
            version_path = save_version(STATE_DIR, note["id"], markdown)
            payload, queued = write_state(STATE_DIR, course_id, note["id"],
                                          feedback, version_path,
                                          protected=protected)
        else:
            version_path = ""
            payload = build_payload(course_id, note["id"], feedback)
            queued = queued_gaps(course_id, feedback)
        say()
        say(render_report(feedback, payload, queued, version_path))

    # GUI 的报告契约：覆盖率 / note 维度 / 缺口 / 待办 / 术语数。
    # 软整理没有模型反馈，给一份空载荷而不是缺字段（契约始终成立）。
    if payload is None:
        report_payload = {"coverage": None, "note_dimension": None, "gaps": [],
                          "todo": [], "glossary_count": 0, "soft": True}
    else:
        report_payload = {
            "coverage": payload.get("coverage_ratio"),
            "note_dimension": payload.get("note_dimension"),
            "gaps": [{"id": c.get("id"), "status": c.get("status"),
                      "why": c.get("why", "")}
                     for c in (feedback.get("coverage") or [])
                     if c.get("status") != "covered"],
            "todo": payload.get("todo") or [],
            "glossary_count": payload.get("glossary_count", 0),
        }
    emit({"type": "report", "payload": report_payload})

    version_ref = (os.path.splitext(os.path.basename(version_path))[0]
                   if version_path else "")

    if not apply_now:
        say("\n" + "=" * 62)
        say("（预览模式，未写入：笔记、掌握度、回炉队列都没有改动）")
        say("=" * 62)
        say(markdown[:1200] + ("\n…（已截断）" if len(markdown) > 1200 else ""))
        emit({"type": "done", "ok": True, "applied": False,
              "course_id": course_id, "note_id": note["id"],
              "changed": {"user_zone": False, "ai_zone": "unchanged",
                          "history_appended": 0},
              "version": "", "note_path": note["path"]})
        return 0

    try:
        rc = _write_back(note, course_id, markdown, feedback, ts,
                         data_dir=d["data_dir"],
                         version_ref=version_ref)
    except Exception as e:  # noqa: BLE001
        say(f"   ❌ 写入失败：{type(e).__name__}: {e}")
        say("   （笔记是原子写入的：失败时仍是原来那一份）")
        emit_error("WRITE_FAILED", f"{type(e).__name__}: {e}")
        return 1
    say("\n" + "=" * 62)
    say("✅ 已写入。三个区各归各管：")
    say("   · 「✍️ 我的笔记」——一字未动")
    say("   · 「🤖 AI 整理」——整块替换（幂等，不会越整理越长）")
    say("   · 「📚 整理历史」——追加一行，历史可回滚")
    if version_path:
        say(f"   · 整理稿快照：{version_path}")
        say(f"   · 回滚：tidy.py --course {course_id} --rollback {version_ref}")
    if protected:
        say(f"   · 其中 {len(set(protected) & {k.split(':', 1)[1] for k in queued})} "
            f"个你已具备/挂账的知识点只标了「待复核」，没有摘牌")
    say("=" * 62)
    emit({"type": "done", "ok": True, "applied": True,
          "course_id": course_id, "note_id": note["id"],
          "changed": {"user_zone": False, "ai_zone": "replaced",
                      "history_appended": 1},
          "version": version_ref, "note_path": note["path"]})
    return rc



# ---------------------------------------------------------------- 数据入口
# 体系换过一次骨架（西二 11 门课 → 老 9 课）。硬编码文件路径的结果是
# 「工具还在照旧课表找课程」，所以统一从这里取。`--west2` 可切回原课表做对照。

def _active_system():
    from system import active_paths
    return active_paths(BASE, west2="--west2" in sys.argv)[0]


def _active_placement():
    from system import active_paths
    return active_paths(BASE, west2="--west2" in sys.argv)[1]

if __name__ == "__main__":
    sys.exit(main())
