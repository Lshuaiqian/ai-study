"""core · DeepSeek 客户端。

把 S-H0/S-H2/S-H3 验证过的调用约定固化下来，避免每个角色各写一份：
  - 显式关闭思考模式（唯一有效写法 "thinking": {"type": "disabled"}；
    "enable_thinking": false 实测无效）
  - 结构化输出走 response_format=json_object（H2 15/15 + H3 3/3 解析成功）
  - 请求体把【稳定前缀】放前面、易变内容放后面，吃满缓存命中价（0.02 元/百万）
  - 统计 usage 并估算成本
"""
import json
import time
import urllib.error
import urllib.request

from .config import price_of


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, cfg):
        self.cfg = cfg
        self.base = cfg["base_url"].rstrip("/")
        self.model = cfg["model"]
        self.key = cfg["api_key"]
        self.timeout = cfg.get("timeout_seconds", 120)
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0,
                      "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0}
        self.calls = 0
        if not self.key:
            raise LLMError("未找到 api_key（study/config.json、DEEPSEEK_API_KEY、"
                           "或 E:\\Agents\\python-tutor\\config.json 均为空）")

    # ---------- 底层 ----------
    def _post(self, payload, retries=3):
        data = json.dumps(payload).encode("utf-8")
        last = None
        for attempt in range(retries):
            req = urllib.request.Request(self.base + "/v1/chat/completions",
                                         data=data, method="POST")
            req.add_header("Authorization", "Bearer " + self.key)
            req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")
                # 429 / 5xx 退避重试；4xx 参数类错误直接抛
                if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                    last = f"HTTP {e.code}: {body[:200]}"
                    time.sleep(1.5 ** attempt)
                    continue
                raise LLMError(f"HTTP {e.code}: {body[:300]}") from None
            except Exception as e:  # noqa: BLE001
                last = f"{type(e).__name__}: {e}"
                if attempt < retries - 1:
                    time.sleep(1.5 ** attempt)
                    continue
                raise LLMError(last) from None
        raise LLMError(last or "unknown")

    @staticmethod
    def _count(usage, acc):
        for k in acc:
            acc[k] += usage.get(k, 0) or 0

    # ---------- 对外 ----------
    def chat(self, system, user, *, json_mode=False, max_tokens=None,
             temperature=0.0, thinking=None):
        """单轮对话。system 作为稳定前缀（利于 KV 缓存命中）。"""
        if thinking is None:
            thinking = self.cfg.get("thinking", False)
        if max_tokens is None:
            max_tokens = self.cfg["max_tokens_json" if json_mode else "max_tokens_chat"]

        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "stream": False,
            "thinking": {"type": "enabled" if thinking else "disabled"},
        }
        if not thinking:
            # 思考模式会忽略 temperature，所以只在非思考模式下设置
            payload["temperature"] = temperature
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        body = self._post(payload)
        self.calls += 1
        self._count(body.get("usage", {}), self.usage)
        msg = body["choices"][0]["message"]
        content = msg.get("content") or ""
        if json_mode:
            try:
                return json.loads(content)
            except json.JSONDecodeError as e:
                raise LLMError(f"JSON 解析失败: {e} | 原文前 300 字: {content[:300]}") from None
        return content

    def cost(self):
        return price_of(self.cfg, self.model,
                        self.usage["prompt_cache_hit_tokens"],
                        self.usage["prompt_cache_miss_tokens"]
                        or self.usage["prompt_tokens"],
                        self.usage["completion_tokens"])

    def report(self):
        return (f"[LLM] {self.calls} 次调用 | 输入 命中={self.usage['prompt_cache_hit_tokens']} "
                f"未命中={self.usage['prompt_cache_miss_tokens']} "
                f"输出={self.usage['completion_tokens']} | 成本≈{self.cost():.5f} 元")
