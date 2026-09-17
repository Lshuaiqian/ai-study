#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证已迁移的 python-tutor：真的调它自己被改过的函数，而不是看代码猜。

检查三件事：
  1. tutor.py 语法可编译
  2. chat_once 现在真的走 deepseek-flash 且带着 thinking=disabled
  3. tool_read_image 能读一张真实截图并返回有效内容
"""
import io
import os
import py_compile
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

AGENT_DIR = r"E:\Agents\python-tutor"
SCREENSHOT = r"C:\Users\Lshuaiqian\Pictures\Screenshots\屏幕截图 2026-05-19 203537.png"

print("=" * 66)
print("[1] 语法检查")
try:
    py_compile.compile(os.path.join(AGENT_DIR, "tutor.py"), doraise=True,
                       cfile=os.path.join(tempfile.gettempdir(), "t.pyc"))
    print("  ✅ tutor.py 编译通过")
except Exception as e:  # noqa: BLE001
    print(f"  ❌ 编译失败：{type(e).__name__}: {e}")
    sys.exit(1)

sys.path.insert(0, AGENT_DIR)
import tutor  # noqa: E402

cfg = tutor.load_config()
print(f"\n  生效配置：model={cfg['model']} thinking={cfg.get('thinking')} "
      f"max_tokens={cfg.get('max_tokens')} vision_model={cfg.get('vision_model')}")
print(f"  FILE_READ_LIMIT = {tutor.FILE_READ_LIMIT}")

print("\n[2] chat_once 实调（验证模型与思考模式真的生效）")
body = tutor.chat_once(cfg, [{"role": "user", "content": "只回复两个字：可用"}], None)
usage = body.get("usage", {})
cdet = usage.get("completion_tokens_details") or {}
print(f"  模型返回：{body['choices'][0]['message'].get('content','')!r}")
print(f"  usage={usage}")
print(f"  reasoning_tokens={cdet.get('reasoning_tokens')} "
      f"→ {'✅ 思考模式已关闭' if not cdet.get('reasoning_tokens') else '⚠️ 仍在思考模式'}")

print("\n[3] tool_read_image 实调（用真实截图）")
work = os.path.join(tempfile.gettempdir(), "py_tutor_vision_check")
os.makedirs(work, exist_ok=True)
shutil.copy2(SCREENSHOT, os.path.join(work, "shot.png"))
cfg2 = dict(cfg)
cfg2["practice_dir"] = work

out = tutor.tool_read_image(cfg2, {"file": "shot.png"})
print(f"  返回 {len(out)} 字符：")
print("  " + "\n  ".join(out.splitlines()[:12]))

print("\n[4] 越界保护")
print("  ", tutor.tool_read_image(cfg2, {"file": "..\\..\\config.json"})[:60])
print("  ", tutor.tool_read_image(cfg2, {"file": "不存在.png"})[:60])

ok = (not cdet.get("reasoning_tokens")) and len(out) > 100
print("\n" + "=" * 66)
print(f"结论：{'PASS' if ok else 'CHECK'}")
sys.exit(0 if ok else 1)
