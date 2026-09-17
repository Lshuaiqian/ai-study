"""notes · 花笺（floral-notepaper）连接器。

格式核实自源码 `refs/floral-notepaper`（Tauri 2 + React，MIT）：

    <data_dir>/config.json      设置，其中 notesDir 可自定义笔记目录
    <data_dir>/metadata.json    {"notes":[{id,title,fileName,category,
                                           createdAt,updatedAt,wordCount,preview}]}
    <notesDir>/<分类>/<id>_<标题>.md     笔记正文就是普通 Markdown，无私有格式
    <notesDir>/<id>.md                   标题为空时不带标题后缀

关键结论：**花笺的笔记就是普通 Markdown 文件 + 一份 JSON 索引**，
所以连接它不需要插件、不需要 API —— 直接读写目录即可。
分类（文件夹）在花笺里已经存在，就是目录名。

设计原则：
  - 默认**只读**：任何写操作都要显式调用，且写 metadata 前先备份
  - 扫描**递归**：花笺当前只认一层分类，但本连接器按相对路径取分类，
    这样将来花笺支持多层时（见 notes.rs 改动建议）无需再改这里
"""
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone

# 花笺自定义目录时可能带也可能不带 notes 后缀（源码 v1.0.4 迁移逻辑如此）
UUID_RE = re.compile(r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                     r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")
ILLEGAL_STEM = re.compile(r'[\\/:*?"<>|\r\n\t]')


def default_data_dir():
    """花笺默认数据目录：Windows/macOS 用「文档/花笺」。"""
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, "Documents", "花笺"),
                 os.path.join(home, "OneDrive", "Documents", "花笺"),
                 os.path.join(home, "文档", "花笺")):
        if os.path.isdir(cand):
            return cand
    return os.path.join(home, "Documents", "花笺")


def discover(data_dir=None):
    """定位花笺的 data_dir / notes_dir / metadata.json。

    notesDir 优先级：config.json 的 notesDir > <data_dir>/notes。
    """
    data_dir = data_dir or os.environ.get("FLORAL_NOTEPAPER_DATA_DIR") or default_data_dir()
    config_path = os.path.join(data_dir, "config.json")
    config = {}
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:  # noqa: BLE001
            config = {}

    notes_dir = config.get("notesDir") or os.path.join(data_dir, "notes")
    return {
        "data_dir": data_dir,
        "config_path": config_path,
        "config": config,
        "notes_dir": notes_dir,
        "metadata_path": os.path.join(data_dir, "metadata.json"),
        "exists": os.path.isdir(notes_dir),
    }


# ---------------- 只读：扫描与解析 ----------------

def parse_id(file_name):
    """从 `<id>_<标题>.md` 或 `<id>.md` 里取 id。取不到返回 None（非花笺笔记）。"""
    if not file_name.lower().endswith(".md"):
        return None
    m = UUID_RE.match(file_name)
    return m.group(1) if m else None


def infer_title(file_name, content=""):
    """标题推断顺序：文件名里的标题部分 → 正文首个 # 标题 → 空。"""
    stem = file_name[:-3] if file_name.lower().endswith(".md") else file_name
    m = UUID_RE.match(stem)
    if m:
        rest = stem[m.end():].lstrip("_").strip()
        if rest:
            return rest
    for line in (content or "").splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return ""


def scan(notes_dir, limit=None):
    """递归扫描笔记目录。

    分类 = 相对 notes_dir 的目录路径（用 / 分隔）。
    花笺当前只写一层，但这里按多层处理，向后兼容。
    """
    out = []
    if not os.path.isdir(notes_dir):
        return out
    root = os.path.abspath(notes_dir)
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not name.lower().endswith(".md"):
                continue
            path = os.path.join(dirpath, name)
            rel_dir = os.path.relpath(dirpath, root)
            category = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                mtime = 0
            out.append({
                "id": parse_id(name),
                "file_name": name,
                "title": infer_title(name),
                "category": category,
                "path": path,
                "size": os.path.getsize(path),
                "mtime": mtime,
            })
            if limit and len(out) >= limit:
                return out
    return sorted(out, key=lambda n: (n["category"], n["file_name"]))


def read_note(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def load_metadata(data_dir):
    path = os.path.join(data_dir, "metadata.json")
    if not os.path.isfile(path):
        return {"notes": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def index_by_id(metadata):
    return {n["id"]: n for n in (metadata.get("notes") or []) if n.get("id")}


def reconcile(scanned, metadata):
    """把磁盘扫描结果与 metadata.json 对照，暴露不一致。

    花笺自己在 rebuild 时会从文件系统推断，所以不一致不是错误，
    但值得知道——尤其是"文件在但索引里没有"（花笺可能看不到它）。
    """
    known = index_by_id(metadata)
    scanned_ids = {n["id"] for n in scanned if n["id"]}
    return {
        "tracked": sorted(scanned_ids & set(known)),
        # 只统计"符合花笺命名规范但索引里没有"的——花笺下次 rebuild 会收进来。
        # 不符合命名规范的（id 为 None）单独一桶，花笺永远不会认它们。
        "untracked_files": sorted(n["file_name"] for n in scanned
                                  if n["id"] and n["id"] not in known),
        "missing_files": sorted(i for i in known if i not in scanned_ids),
        "non_huajian_md": sorted(n["file_name"] for n in scanned if not n["id"]),
    }


# ---------------- 写：与花笺命名规范一致 ----------------

def safe_file_stem(title):
    """对齐花笺的 safe_file_stem：去掉文件系统非法字符与首尾空白/点。"""
    stem = ILLEGAL_STEM.sub("", (title or "").strip())
    stem = stem.strip().strip(".")
    return stem[:80]


def new_note_id():
    return str(uuid.uuid4())


def build_file_name(note_id, title):
    stem = safe_file_stem(title)
    return f"{note_id}_{stem}.md" if stem else f"{note_id}.md"


def note_path(notes_dir, file_name, category=""):
    parts = [p for p in (category or "").replace("\\", "/").split("/") if p and p != "."]
    if any(p == ".." for p in parts):
        raise ValueError("分类路径不允许包含 ..")
    return os.path.join(notes_dir, *parts, file_name)


def write_note(notes_dir, title, content, category="", note_id=None):
    """按花笺规范落盘一篇笔记，返回 (note_id, path)。

    注意：只写 .md 文件，**不动 metadata.json**——
    花笺在 metadata 缺失/为空时会自动 rebuild，所以先写文件是安全的。
    需要让索引立刻生效时再显式调用 upsert_metadata。
    """
    note_id = note_id or new_note_id()
    file_name = build_file_name(note_id, title)
    path = note_path(notes_dir, file_name, category)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content if content.endswith("\n") else content + "\n")
    return note_id, path


def upsert_metadata(data_dir, entry, backup=True):
    """把一条笔记记录写进 metadata.json（原子替换，默认先备份）。"""
    meta_path = os.path.join(data_dir, "metadata.json")
    metadata = load_metadata(data_dir)
    notes = metadata.setdefault("notes", [])
    for i, n in enumerate(notes):
        if n.get("id") == entry["id"]:
            notes[i] = {**n, **entry}
            break
    else:
        notes.append(entry)

    if backup and os.path.isfile(meta_path):
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        shutil.copy2(meta_path, f"{meta_path}.bak-{stamp}")

    tmp = meta_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    os.replace(tmp, meta_path)
    return metadata


def make_entry(note_id, title, file_name, category, content):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    return {
        "id": note_id, "title": title, "fileName": file_name,
        "category": category or "",
        "createdAt": now, "updatedAt": now,
        "wordCount": len(re.sub(r"\s+", "", content or "")),
        "preview": _preview(content),
    }


def _preview(content, limit=80):
    for line in (content or "").splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:limit]
    return ""


# ---------------- 与学习库对接 ----------------

def to_materials(notes, notes_dir=None, max_chars=4000):
    """把花笺笔记转成学习库可抽取的素材（kind='note' → derived 权威级）。

    注意：从学生自己的笔记抽出的原子是 derived，**不能用来判定他自己的笔记有错**
    （见 library/extractor.py 的 AUTHORITY_BY_KIND）。
    """
    out = []
    for n in notes:
        text = read_note(n["path"]) if notes_dir is not None or n.get("path") else ""
        out.append({
            "id": n.get("id") or n["file_name"],
            "title": n.get("title") or n["file_name"],
            "category": n.get("category", ""),
            "path": n.get("path"),
            "text": text[:max_chars],
            "truncated": len(text) > max_chars,
        })
    return out
