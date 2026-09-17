"""通过 GitHub API 浏览/抓取仓库（github.com 直连不通时用这个）。

用法：
    python fetch_gh_repo.py Achilng/floral-notepaper                 # 列出全部文件
    python fetch_gh_repo.py Achilng/floral-notepaper --grep store    # 只看路径含关键词的
    python fetch_gh_repo.py Achilng/floral-notepaper --get README.md src-tauri/Cargo.toml
"""
import base64
import io
import json
import os
import sys
import urllib.error
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

API = "https://api.github.com"
TIMEOUT = 60
OUT_ROOT = r"E:\Docs\Code\Java\book\refs"


def gh(path):
    req = urllib.request.Request(API + path)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "study-app-ref-fetcher")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def repo_info(slug):
    info = gh(f"/repos/{slug}")
    print(f"仓库：{info['full_name']}")
    print(f"  描述：{info.get('description')}")
    print(f"  语言：{info.get('language')}｜stars {info.get('stargazers_count')}"
          f"｜默认分支 {info.get('default_branch')}｜license "
          f"{(info.get('license') or {}).get('spdx_id')}")
    return info


def tree(slug, branch):
    data = gh(f"/repos/{slug}/git/trees/{branch}?recursive=1")
    return data.get("tree") or []


def fetch_file(slug, branch, path, out_dir):
    data = gh(f"/repos/{slug}/contents/{path}?ref={branch}")
    if data.get("type") != "file":
        print(f"  跳过（不是文件）：{path}")
        return None
    content = base64.b64decode(data["content"]).decode("utf-8", "replace")
    target = os.path.join(out_dir, path.replace("/", os.sep))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  ↓ {path}  ({len(content)} 字符)")
    return target


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    slug = argv[0]
    info = repo_info(slug)
    branch = info.get("default_branch", "main")

    if "--get" in argv:
        paths = argv[argv.index("--get") + 1:]
        out_dir = os.path.join(OUT_ROOT, slug.split("/")[-1])
        print(f"抓取 {len(paths)} 个文件 → {out_dir}")
        for p in paths:
            try:
                fetch_file(slug, branch, p, out_dir)
            except urllib.error.HTTPError as e:
                print(f"  ✗ {p}  HTTP {e.code}")
        return 0

    files = tree(slug, branch)
    grep = argv[argv.index("--grep") + 1].lower() if "--grep" in argv else None
    shown = 0
    for node in files:
        if node["type"] != "blob":
            continue
        p = node["path"]
        if grep and grep not in p.lower():
            continue
        print(f"  {node.get('size', 0):>7}  {p}")
        shown += 1
    print(f"\n共 {len([n for n in files if n['type'] == 'blob'])} 个文件"
          + (f"，匹配 {shown} 个" if grep else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
