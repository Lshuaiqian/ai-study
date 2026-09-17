"""S-H0b 探针：确认思考模式对 max_tokens 预算的吞噬，并找到关闭方式。

背景：probe_models.py 发现 deepseek-flash / deepseek-v4-pro 在 max_tokens=16 时
      reasoning_tokens=16、正文为空 —— 思考模式默认开启。
本探针验证：
  1. 提高 max_tokens 后正文是否出现
  2. 思考模式能否关闭（两种候选写法）
  3. 记录 reasoning_tokens 占比，为 max_tokens 配置定档
"""
import io
import json
import os
import sys
import urllib.error
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CFG = r"E:\Agents\python-tutor\config.json"
TIMEOUT = 90


def load_cfg():
    with open(CFG, "r", encoding="utf-8") as f:
        return json.load(f)


def call(base, key, payload):
    req = urllib.request.Request(
        base + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


PROMPT = "用一句话说明 Python 里 list 和 tuple 的核心区别。"


def describe(body):
    ch = body["choices"][0]["message"]
    usage = body.get("usage", {})
    cdetails = usage.get("completion_tokens_details") or {}
    content = (ch.get("content") or "").strip()
    reasoning = (ch.get("reasoning_content") or "").strip()
    return {
        "content": content,
        "content_len": len(content),
        "has_reasoning_field": bool(reasoning),
        "reasoning_len": len(reasoning),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": cdetails.get("reasoning_tokens"),
        "finish_reason": body["choices"][0].get("finish_reason"),
    }


def main():
    cfg = load_cfg()
    base = cfg["base_url"].rstrip("/")
    key = cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY", "")

    cases = [
        ("A 基线 deepseek-chat max_tokens=300", "deepseek-chat", 300, {}),
        ("B flash 思考默认 max_tokens=300", "deepseek-flash", 300, {}),
        ("C flash 思考默认 max_tokens=2000", "deepseek-flash", 2000, {}),
        ("D flash 关思考(thinking=disabled)", "deepseek-flash", 300,
         {"thinking": {"type": "disabled"}}),
        ("E flash 关思考(enable_thinking=False)", "deepseek-flash", 300,
         {"enable_thinking": False}),
        ("F pro 思考默认 max_tokens=600", "deepseek-v4-pro", 600, {}),
    ]

    for label, model, mt, extra in cases:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": PROMPT}],
            "max_tokens": mt,
            "temperature": 0,
            "stream": False,
        }
        payload.update(extra)
        try:
            status, body = call(base, key, payload)
            d = describe(body)
            print(f"--- {label}")
            print(f"    HTTP {status} | finish={d['finish_reason']} "
                  f"| completion={d['completion_tokens']} reasoning={d['reasoning_tokens']}")
            print(f"    content({d['content_len']}字): {d['content'][:90]}")
            if d["has_reasoning_field"]:
                print(f"    [存在 reasoning_content 字段, {d['reasoning_len']}字]")
        except urllib.error.HTTPError as e:
            print(f"--- {label}\n    HTTP {e.code} | {e.read().decode('utf-8', 'replace')[:240]}")
        except Exception as e:  # noqa: BLE001
            print(f"--- {label}\n    失败: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
