#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 E:\\Agents\\python-tutor 迁移到 deepseek-flash（4.1 Flash）并加上视觉能力。

改动（全部先备份，可一键回滚）：
  1. config.json：model → deepseek-flash；显式 thinking=false；max_tokens 1500 → 4000；
     新增 vision_model
  2. tutor.py chat_once：显式关闭思考模式，且仅在非思考模式下发 temperature
     （思考模式会忽略 temperature 并吃掉 ~75-79% 输出预算 —— 这是实测结论）
  3. tutor.py 新增 read_image 工具：让导师能「看」学生贴的报错/题目截图
  4. 提高单文件读取上限（6000 → 12000 字符）

用法：
    python migrate_py_tutor.py --dry-run     # 只打印将要做的改动
    python migrate_py_tutor.py               # 实际写入（自动备份）
    python migrate_py_tutor.py --rollback    # 从最新备份还原
"""
import io
import json
import os
import shutil
import sys
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TARGET_DIR = r"E:\Agents\python-tutor"
CONFIG = os.path.join(TARGET_DIR, "config.json")
TUTOR = os.path.join(TARGET_DIR, "tutor.py")
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")

DRY = "--dry-run" in sys.argv
ROLLBACK = "--rollback" in sys.argv


def log(msg):
    print(("  [dry] " if DRY else "  ") + msg)


# ---------------- 1. config.json ----------------

def migrate_config():
    with open(CONFIG, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    before = dict(cfg)

    cfg["model"] = "deepseek-flash"
    cfg["thinking"] = False              # 显式关闭思考模式
    cfg["max_tokens"] = 4000             # 1500 装不下四段式点评
    cfg["vision_model"] = "deepseek-flash"
    cfg.setdefault("temperature", 0.6)
    # 注：单文件读取上限改在 tutor.py 的 FILE_READ_LIMIT 常量上，
    # 这里不再加没人读的 file_read_limit 配置项，免得误导。

    changed = {k: (before.get(k), cfg.get(k)) for k in cfg
               if before.get(k) != cfg.get(k) or k not in before}
    for k, (o, n) in changed.items():
        log(f"config.{k}: {o!r} → {n!r}")

    if not DRY:
        shutil.copy2(CONFIG, f"{CONFIG}.bak-{STAMP}")
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    return len(changed)


# ---------------- 2/3/4. tutor.py ----------------

OLD_PAYLOAD = '''    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": cfg.get("temperature", 0.6),
        "max_tokens": cfg.get("max_tokens", 1500),
        "stream": False,
    }'''

NEW_PAYLOAD = '''    # 思考模式默认开启：会忽略 temperature，且实测吃掉 ~75-79% 的输出预算
    # （max_tokens=1500 时正文只剩 300 多 token，四段式点评会被腰斩）。
    # 唯一有效的关闭写法是 thinking={"type": "disabled"}。
    thinking = bool(cfg.get("thinking", False))
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "max_tokens": cfg.get("max_tokens", 4000),
        "stream": False,
        "thinking": {"type": "enabled" if thinking else "disabled"},
    }
    if not thinking:
        payload["temperature"] = cfg.get("temperature", 0.6)'''

OLD_LIMIT = "FILE_READ_LIMIT = 6000        # 单文件最多读入字符"
NEW_LIMIT = "FILE_READ_LIMIT = 12000       # 单文件最多读入字符（点评要同时看代码+笔记）"

OLD_TOOL_ANCHOR = '''    {
        "type": "function",
        "function": {
            "name": "update_progress",'''

NEW_TOOL_ENTRY = '''    {
        "type": "function",
        "function": {
            "name": "read_image",
            "description": ("查看练习区里的一张图片（报错截图、题目截图、手写照片），"
                            "返回图中可见的文字与内容描述。学生贴图时用它。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {"type": "string",
                             "description": "练习区里的图片文件名，如 error.png"},
                    "question": {"type": "string",
                                 "description": "你想从图里知道什么（可选）"},
                },
                "required": ["file"],
            },
        },
    },
''' + OLD_TOOL_ANCHOR

OLD_DISPATCH = '''        if name == "update_progress":
            return tool_update_progress(cfg, args, progress, lessons)'''
NEW_DISPATCH = '''        if name == "update_progress":
            return tool_update_progress(cfg, args, progress, lessons)
        if name == "read_image":
            return tool_read_image(cfg, args)'''

VISION_FUNC = '''

# ---------------- 视觉：让导师能「看」图 ----------------

IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".webp": "image/webp", ".gif": "image/gif"}
IMAGE_B64_LIMIT = 8_000_000          # base64 字符串长度上限，超过就拒绝


def tool_read_image(cfg, args):
    """把练习区里的图片交给视觉模型，返回文字描述给主循环。

    做法上是个"视觉子调用"：主循环本身不需要有视觉能力，
    它只需要拿到图中的文字与要点。实测 deepseek-flash 读终端截图
    能准确抄出报错码与命令，足够支撑"贴报错截图让导师看"。
    """
    import base64

    name = (args or {}).get("file", "")
    question = (args or {}).get("question") or (
        "描述这张图片。如果是终端/报错截图或题目截图，"
        "请把可见的关键文字（命令、报错码、题面）完整抄录出来，再说明它意味着什么。")

    path = os.path.join(cfg["practice_dir"], name)
    if not os.path.isfile(path):
        return f"文件不存在：{name}（只允许读练习区里的图片）"
    mime = IMAGE_MIME.get(os.path.splitext(path)[1].lower())
    if not mime:
        return f"不支持的图片格式：{os.path.splitext(path)[1]}"

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    if len(b64) > IMAGE_B64_LIMIT:
        return f"图片太大（base64 {len(b64)//1024} KB），请压缩或裁剪后再试"

    payload = {
        "model": cfg.get("vision_model") or cfg["model"],
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            {"type": "text", "text": question},
        ]}],
        "max_tokens": 1200,
        "thinking": {"type": "disabled"},
        "stream": False,
    }
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + cfg["api_key"]})
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("timeout_seconds", 120)) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return f"视觉识别失败 HTTP {e.code}：{e.read().decode('utf-8', 'replace')[:200]}"
    except Exception as e:  # noqa: BLE001
        return f"视觉识别失败：{type(e).__name__}: {e}"
    return body["choices"][0]["message"].get("content") or "（未识别出内容）"
'''


def migrate_tutor():
    with open(TUTOR, "r", encoding="utf-8") as f:
        src = f.read()
    original = src
    n = 0

    for label, old, new in (
        ("chat_once: 关闭思考模式 + 提高 max_tokens", OLD_PAYLOAD, NEW_PAYLOAD),
        ("FILE_READ_LIMIT 6000 → 12000", OLD_LIMIT, NEW_LIMIT),
        ("TOOLS: 注册 read_image", OLD_TOOL_ANCHOR, NEW_TOOL_ENTRY),
        ("call_tool: 分派 read_image", OLD_DISPATCH, NEW_DISPATCH),
    ):
        if new.split("\n")[0] in src and old not in src:
            log(f"{label} —— 已应用过，跳过")
            continue
        if old not in src:
            log(f"⚠️ {label} —— 找不到锚点，跳过（手工确认）")
            continue
        src = src.replace(old, new, 1)
        log(f"{label} ✅")
        n += 1

    if "def tool_read_image" not in src:
        src = src.rstrip("\n") + "\n" + VISION_FUNC
        log("追加 tool_read_image 实现 ✅")
        n += 1
    else:
        log("tool_read_image 已存在，跳过")

    if src != original and not DRY:
        shutil.copy2(TUTOR, f"{TUTOR}.bak-{STAMP}")
        with open(TUTOR, "w", encoding="utf-8") as f:
            f.write(src)
    return n


# ---------------- 回滚 ----------------

def rollback():
    n = 0
    for target in (CONFIG, TUTOR):
        baks = sorted(f for f in os.listdir(os.path.dirname(target))
                      if f.startswith(os.path.basename(target) + ".bak-"))
        if not baks:
            print(f"  {os.path.basename(target)}：没有备份")
            continue
        latest = os.path.join(os.path.dirname(target), baks[-1])
        shutil.copy2(latest, target)
        print(f"  {os.path.basename(target)} ← {baks[-1]}")
        n += 1
    print(f"已还原 {n} 个文件")
    return 0


def main():
    if ROLLBACK:
        print("回滚 python-tutor：")
        return rollback()

    print(f"目标：{TARGET_DIR}{'（dry-run）' if DRY else ''}")
    if not os.path.isfile(CONFIG) or not os.path.isfile(TUTOR):
        print(f"✗ 找不到 config.json 或 tutor.py，请检查路径")
        return 2

    print("\n[1] config.json")
    nc = migrate_config()
    print("\n[2] tutor.py")
    nt = migrate_tutor()

    print(f"\n完成：config 改动 {nc} 项，代码补丁 {nt} 处")
    if DRY:
        print("（dry-run，未写入任何文件）")
    else:
        print(f"备份后缀：.bak-{STAMP}")
        print(f"回滚：python {os.path.basename(__file__)} --rollback")
    return 0


if __name__ == "__main__":
    sys.exit(main())
