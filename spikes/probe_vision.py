"""探针：验证 deepseek-flash 的图像理解能力。

要回答的问题：
  1. flash 的视觉通道能否用（官方价目表标注"图像理解 支持"）
  2. 图片走 base64 data URI 是否可行、体积上限大概在哪
  3. 识别质量够不够做"截图 → 笔记"这类用途

用法：
    python probe_vision.py <图片路径> [提问]
"""
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CFG = r"E:\Agents\python-tutor\config.json"
MODEL = "deepseek-flash"
TIMEOUT = 180
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif"}


def load_cfg():
    with open(CFG, "r", encoding="utf-8") as f:
        return json.load(f)


def call(base, key, payload):
    req = urllib.request.Request(base + "/v1/chat/completions",
                                 data=json.dumps(payload).encode("utf-8"), method="POST")
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    question = sys.argv[2] if len(sys.argv) > 2 else \
        "请描述这张图片：如果是界面截图，说出是什么软件、有哪些可见文字；如果是照片，描述主体与场景。"

    ext = os.path.splitext(path)[1].lower()
    mime = MIME.get(ext, "image/png")
    with open(path, "rb") as f:
        raw = f.read()
    b64 = base64.b64encode(raw).decode("ascii")
    print(f"图片：{path}")
    print(f"  原始 {len(raw)/1024:.1f} KB｜base64 {len(b64)/1024:.1f} KB｜{mime}")

    cfg = load_cfg()
    key = cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY", "")
    base = cfg["base_url"].rstrip("/")

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            {"type": "text", "text": question},
        ]}],
        "max_tokens": 1200,
        "thinking": {"type": "disabled"},
        "stream": False,
    }

    t0 = time.time()
    try:
        body = call(base, key, payload)
    except urllib.error.HTTPError as e:
        print(f"\n❌ HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ {type(e).__name__}: {e}")
        return 1

    msg = body["choices"][0]["message"]
    usage = body.get("usage", {})
    print(f"\n✅ 成功（{time.time()-t0:.1f}s）")
    print(f"usage：{usage}")
    print("-" * 60)
    print(msg.get("content") or "（空）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
