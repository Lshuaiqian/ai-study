"""S-H0 探针：验证 DeepSeek 连通性 + 模型名可用性。

回答可行性深化文档 §10 待决问题 1：
    现有配置里的 `deepseek-chat` 是否仍可解析？
    迁移到 `deepseek-flash` 是否可行？

只读脚本：不写任何文件，不改配置。密钥从现有 config.json 读取。
"""
import json
import os
import sys
import urllib.error
import urllib.request

CFG = r"E:\Agents\python-tutor\config.json"
TIMEOUT = 40


def load_cfg():
    with open(CFG, "r", encoding="utf-8") as f:
        return json.load(f)


def call(url, key, payload=None, method="GET"):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def main():
    cfg = load_cfg()
    base = cfg["base_url"].rstrip("/")
    key = cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        print("!! 未找到 api_key（config 与环境变量均为空）")
        return 2

    print("base_url =", base)
    print("configured model =", cfg.get("model"))
    print("-" * 60)

    # ① 模型列表
    try:
        status, body = call(base + "/v1/models", key)
        ids = [m.get("id") for m in body.get("data", [])]
        print(f"[1] GET /v1/models -> HTTP {status}")
        print("    可用模型:", ", ".join(ids) if ids else "(空)")
    except urllib.error.HTTPError as e:
        print(f"[1] GET /v1/models -> HTTP {e.code}  {e.read()[:300]!r}")
        ids = []
    except Exception as e:  # noqa: BLE001
        print(f"[1] GET /v1/models -> 连接失败: {type(e).__name__}: {e}")
        ids = []

    print("-" * 60)

    # ② 逐个试 chat/completions，确认模型名能否解析
    for name in [cfg.get("model"), "deepseek-flash", "deepseek-v4-pro"]:
        if not name:
            continue
        payload = {
            "model": name,
            "messages": [{"role": "user", "content": "只回复两个字：可用"}],
            "max_tokens": 16,
            "temperature": 0,
            "stream": False,
        }
        try:
            status, body = call(base + "/v1/chat/completions", key, payload, "POST")
            content = body["choices"][0]["message"].get("content", "")
            usage = body.get("usage", {})
            print(f"[2] {name:20s} -> HTTP {status} | 回复={content!r} | usage={usage}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            print(f"[2] {name:20s} -> HTTP {e.code} | {detail}")
        except Exception as e:  # noqa: BLE001
            print(f"[2] {name:20s} -> 连接失败: {type(e).__name__}: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
