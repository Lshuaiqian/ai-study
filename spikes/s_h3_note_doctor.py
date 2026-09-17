"""S-H3 Spike：笔记纠错假阳性验证（可行性深化文档 §4.3）

目的：验证"笔记医生"指出的错误是否真的是错误——假阳性最伤信任。
方法：构造一篇含【已知植入错误】+【正确表述】+【资料未覆盖的知识点】的学生笔记，
      喂给笔记医生原型，人工比对它标出的每一条。

测量三项：
  precision  = 标为 error 且确实是植入错误的条数 / 标为 error 的总条数
  recall     = 被标出的植入错误数 / 植入错误总数
  FP(正确句)  = 把正确表述误标为 error 的条数
  降级正确性  = 资料未覆盖的错误是否被正确标为 uncertain 而非 error

关键配置：thinking=disabled + temperature=0 + JSON Output（与 H2 一致）
只读 + 只写结果 JSON。
"""
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CFG = r"E:\Agents\python-tutor\config.json"
OUT_DIR = r"E:\Docs\Code\Java\book\spikes\results"
TIMEOUT = 120
MODEL = "deepseek-flash"

# ---------- 课程知识点（决定"覆盖"维度） ----------
COURSE_POINTS = [
    "HTTP 请求/响应结构",
    "requests 基本用法与 Session",
    "异常处理与超时/重试",
    "robots.txt 与请求礼仪",
]

# ---------- 学习库资料（笔记医生可以引用的依据） ----------
# 注意：故意不覆盖"timeout 默认值"，用来测"无依据时是否降级为 待确认"
MATERIAL = """[M1] HTTP 是无状态协议；服务器不保存请求之间的关联，登录态依赖 Cookie 或 Token 在客户端保存并随请求携带。
[M2] GET 把参数放在 URL 的 query string 中，语义是"读取"；POST 把数据放在请求体 body 中，语义是"提交/创建"。二者是语义与位置的区别，不是安全等级的区别。
[M3] requests 的 get/post 默认不会自动重试。需要重试必须显式配置（如 urllib3 的 Retry 或自己写循环）。
[M4] HTTP 404 表示请求的资源不存在（Not Found）；5xx 才表示服务器端错误。
[M5] json.dumps() 把 Python 对象序列化成 JSON 字符串；json.loads() 把 JSON 字符串反序列化成 Python 对象。
[M6] requests.Session 会复用底层 TCP 连接，并对同一主机的请求保持 Cookie。
[M7] resp.raise_for_status() 在响应状态码为 4xx 或 5xx 时抛出 HTTPError 异常。
[M8] 响应正文的字符编码可用 resp.encoding 显式指定，避免中文乱码。
"""

# ---------- 学生笔记（植入 5 个错误 + 5 句正确表述） ----------
NOTE = """# 爬虫笔记 · HTTP 与 requests

## HTTP 基础
- HTTP 是无状态协议，靠 Cookie / Token 维持登录态。（C1 正确）
- HTTP 状态码 404 表示服务器内部错误。（E2 植入错误：404 是资源不存在）
- GET 把数据放在 URL 里，POST 放在 body 里。（C3 正确）

## requests 用法
- GET 请求也可以带请求体传数据，而且比 POST 更安全。（E3 植入错误：语义混淆）
- requests.Session 能复用 TCP 连接。（C2 正确）
- requests.get() 默认会自动重试 3 次，所以不用自己写重试。（E1 植入错误：默认不重试）
- timeout 参数不写也没关系，requests 默认 30 秒超时。（E5 植入错误：资料未覆盖，测降级）

## 数据解析
- json.loads() 用于把 Python 对象转成 JSON 字符串。（E4 植入错误：说反了）
- raise_for_status() 遇到 4xx / 5xx 会抛异常。（C4 正确）
- resp.encoding 可以指定响应编码，避免中文乱码。（C5 正确）

## 其他
- 我没写 robots.txt 相关的内容。（应被"覆盖"维度判为缺失）
"""

PLANTED = {
    "E1": {"quote_hint": "默认会自动重试 3 次", "kind": "error_covered", "truth": "requests 默认不重试 [M3]"},
    "E2": {"quote_hint": "404 表示服务器内部错误", "kind": "error_covered", "truth": "404=资源不存在，5xx=服务器错误 [M4]"},
    "E3": {"quote_hint": "GET 请求也可以带请求体", "kind": "error_covered", "truth": "GET 参数在 URL，安全等级不是区别点 [M2]"},
    "E4": {"quote_hint": "json.loads() 用于把 Python 对象转成 JSON", "kind": "error_covered", "truth": "说反了：dumps 才是序列化 [M5]"},
    "E5": {"quote_hint": "默认 30 秒超时", "kind": "error_uncovered", "truth": "资料未覆盖 → 应降级为 uncertain"},
}
CORRECT = ["C1", "C2", "C3", "C4", "C5"]

SYSTEM = (
    "你是笔记审校员。对照【学习库资料】检查【学生笔记】。规则严格：\n"
    "1) 只有当笔记的说法与资料明确冲突时，才可判 verdict=\"error\"，且必须给出 source_ref（资料编号如 M3）。\n"
    "2) 若你怀疑有问题但资料里没有依据，一律判 verdict=\"uncertain\"，source_ref 留空。\n"
    "3) 保持正确的表述不要报。看不懂或只是简略的，不要报。\n"
    "4) 另需判断笔记对【课程知识点】的覆盖情况。\n"
    "必须输出 JSON：\n"
    '{"issues":[{"quote":"笔记原句","verdict":"error|uncertain","reason":"说明","source_ref":"M3 或 空"}],'
    '"coverage":{"covered":["知识点"],"missing":["知识点"]},"summary":"一句话总评"}\n'
    "issues 里只列你认为有问题的句子；没有就返回空数组。"
)


def load_cfg():
    with open(CFG, "r", encoding="utf-8") as f:
        return json.load(f)


def call(base, key, payload):
    req = urllib.request.Request(
        base + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"), method="POST")
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def diagnose(base, key):
    user = (f"【课程知识点】\n" + "\n".join(f"- {p}" for p in COURSE_POINTS) +
            f"\n\n【学习库资料】\n{MATERIAL}\n\n【学生笔记】\n{NOTE}\n\n请以 JSON 输出体检结果。")
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user}],
        "max_tokens": 2500,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "stream": False,
    }
    body = call(base, key, payload)
    raw = body["choices"][0]["message"].get("content") or ""
    return json.loads(raw), body.get("usage", {}), raw


def match_planted(quote):
    """把模型报出的句子映射回我们植入的错误编号"""
    q = (quote or "").replace(" ", "")
    for pid, meta in PLANTED.items():
        hint = meta["quote_hint"].replace(" ", "")
        if hint in q or q in hint:
            return pid
        # 宽松匹配：取 hint 前 8 字
        if len(hint) >= 8 and hint[:8] in q:
            return pid
    return None


def match_correct(quote):
    q = (quote or "").replace(" ", "")
    keys = {
        "C1": ["无状态", "Cookie", "Token"],
        "C2": ["Session", "复用"],
        "C3": ["GET", "body"],
        "C4": ["raise_for_status", "4xx", "5xx"],
        "C5": ["encoding", "乱码"],
    }
    for cid, kws in keys.items():
        if all(k in q for k in kws[:2]) if len(kws) >= 2 else kws[0] in q:
            return cid
    return None


def main():
    cfg = load_cfg()
    base = cfg["base_url"].rstrip("/")
    key = cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        print("!! 无 api_key")
        return 2

    print(f"S-H3 笔记纠错假阳性 Spike | model={MODEL} thinking=disabled temp=0")
    print("=" * 78)

    results = []
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "prompt_cache_hit_tokens": 0}
    RUNS = 3
    for r in range(RUNS):
        try:
            data, usage, raw = diagnose(base, key)
        except urllib.error.HTTPError as e:
            print(f"run#{r+1} HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}")
            continue
        except Exception as e:  # noqa: BLE001
            print(f"run#{r+1} {type(e).__name__}: {e}")
            continue
        results.append(data)
        for k in usage_total:
            usage_total[k] += usage.get(k, 0) or 0
        time.sleep(0.6)

    if not results:
        print("!! 全部失败")
        return 3

    for i, data in enumerate(results, 1):
        issues = data.get("issues") or []
        cov = data.get("coverage") or {}
        flagged_err = [x for x in issues if x.get("verdict") == "error"]
        flagged_unc = [x for x in issues if x.get("verdict") == "uncertain"]
        print(f"\n--- run#{i}  报出问题 {len(issues)} 条（error {len(flagged_err)} / uncertain {len(flagged_unc)}）")
        for x in issues:
            pid = match_planted(x.get("quote"))
            cid = match_correct(x.get("quote"))
            tag = f"[植入{pid}]" if pid else (f"[正确句{cid}]" if cid else "[未识别]")
            print(f"    {x.get('verdict'):9s} {tag:12s} ref={x.get('source_ref') or '-':4s} "
                  f"| {str(x.get('quote'))[:38]}")
        print(f"    覆盖: covered={cov.get('covered')} missing={cov.get('missing')}")

    print("\n" + "=" * 78)
    # 取三次的并集/交集统计（conservative：按每次分别算，取最差）
    precisions, recalls, fps, degrade_ok = [], [], [], []
    for data in results:
        issues = data.get("issues") or []
        errs = [x for x in issues if x.get("verdict") == "error"]
        tp = sum(1 for x in errs if match_planted(x.get("quote")) in ("E1", "E2", "E3", "E4"))
        precisions.append(tp / len(errs) if errs else 1.0)
        recalls.append(len({match_planted(x.get("quote")) for x in errs
                            if match_planted(x.get("quote")) in ("E1", "E2", "E3", "E4")}) / 4)
        fpc = sum(1 for x in errs if match_correct(x.get("quote")))
        fps.append(fpc)
        # E5 应被标 uncertain（或至少不是 error）
        e5_as_error = any(match_planted(x.get("quote")) == "E5" and x.get("verdict") == "error"
                          for x in issues)
        degrade_ok.append(not e5_as_error)

    print(f"[precision] 三次 = {[f'{p:.2f}' for p in precisions]}  → 最差 {min(precisions):.2f}"
          f"（标准 ≥ 0.95）")
    print(f"[recall   ] 三次 = {[f'{r:.2f}' for r in recalls]}  → 最差 {min(recalls):.2f}")
    print(f"[误报正确句] 三次 = {fps}（标准：0 条）")
    print(f"[E5 降级正确] 三次 = {degrade_ok}（资料未覆盖时不应断言为 error）")
    print(f"[用量] {usage_total}")
    cost = (usage_total["prompt_tokens"] - usage_total["prompt_cache_hit_tokens"]) / 1e6 * 1.0 \
        + usage_total["prompt_cache_hit_tokens"] / 1e6 * 0.02 \
        + usage_total["completion_tokens"] / 1e6 * 4.0
    print(f"[成本] 3 次体检 ≈ {cost:.5f} 元")

    verdict = "PASS" if (min(precisions) >= 0.95 and min(fps) == 0 and all(degrade_ok)) else "REVIEW"
    print("=" * 78)
    print(f"H3 结论: {verdict}")

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(OUT_DIR, f"s_h3_{stamp}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"model": MODEL, "runs": len(results), "raw_results": results,
                   "planted": PLANTED, "correct_ids": CORRECT,
                   "precision": precisions, "recall": recalls, "fp_correct": fps,
                   "degrade_ok": degrade_ok, "usage_total": usage_total,
                   "cost_cny_estimated": round(cost, 5), "verdict": verdict},
                  f, ensure_ascii=False, indent=2)
    print(f"结果已保存: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
