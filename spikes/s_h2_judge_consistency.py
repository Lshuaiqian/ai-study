"""S-H2 Spike：判分一致性验证（可行性深化文档 §4.2）

目的：验证"门禁判分是否具备一致性"——同一份答案多次判定是否得到稳定结论。
方法：5 份人工标注的答案（2 明确通过 / 1 边界 / 2 明确不通过）× 判 3 次。
      判定用结构化 rubric 逐项判定（3 个判定点），而非 LLM 自由打分。

关键配置（由 S-H0 探针实测确定）：
  - model = deepseek-flash
  - thinking = disabled     ← 思考模式默认开启且忽略 temperature，必须关闭才能固定随机性
  - temperature = 0
  - response_format = json_object  ← 验证可行性文档 §6 适配点 4

通过标准：每份答案 3 次得分极差 ≤ 0.05；且 4 份明确标注答案分类 100% 正确。
只读 + 只写结果 JSON，不改任何现有 Agent 代码。
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
RUNS = 3
MODEL = "deepseek-flash"

QUESTION = "为什么 Python 多线程算不快（GIL），与 C++ 线程差别？"

# 判定点：把"掌握"拆成可独立判定的最小命题
RUBRIC = [
    "P1 指出 GIL 是 CPython 的全局解释器锁，且同一时刻只有一个线程执行 Python 字节码",
    "P2 区分 CPU 密集（拿不到多核加速）与 IO 密集（等 IO 时释放 GIL，仍能提速）",
    "P3 与 C++ 对照（C++ 线程可真并行利用多核），并给出绕过方式（多进程 / 原生扩展释放 GIL）",
]

ANSWERS = [
    {
        "id": "A1", "expect": "pass",
        "text": (
            "GIL 是 CPython 的全局解释器锁：同一进程内同一时刻只有一个线程能执行 Python 字节码，"
            "所以纯 CPU 密集的多线程代码无法利用多核，多线程反而可能因为切换开销更慢。"
            "但对 IO 密集型任务（网络、文件），线程在等 IO 时会释放 GIL，多线程仍然能显著提速。"
            "对比 C++：std::thread 是真正的多核并行，没有这个限制。"
            "要在 Python 里拿到多核并行，得用 multiprocessing 多进程，"
            "或者把热点放到 NumPy / 原生扩展里（它们在计算时会释放 GIL）。"
        ),
    },
    {
        "id": "A2", "expect": "pass",
        "text": (
            "因为 GIL 让 CPython 同一时刻只有一个线程执行字节码，CPU 密集的多线程拿不到多核，"
            "只有 IO 密集时线程等 IO 会释放 GIL 才有效。"
            "C++ 线程没有这个限制，可以真并行；Python 想并行算得用多进程。"
        ),
    },
    {
        "id": "A3", "expect": "fail",
        "text": "因为 Python 有 GIL，所以同一时间只能有一个线程运行，多线程其实是假的并行，开了也没用。",
    },
    {
        "id": "A4", "expect": "fail",
        "text": "GIL 是一个可以手动关掉的锁，用 threading.Lock 就能释放；Python 多线程慢是因为线程池创建开销大。",
    },
    {
        "id": "A5", "expect": "fail",
        "text": "因为 Python 是解释型语言，本来就比 C++ 慢，所以多线程也快不起来。",
    },
]

SYSTEM = (
    "你是一个严格的技术判分器。只依据给定的判定点逐项判定，不看文采、不看篇幅、不因为答案长就给分。\n"
    "对每个判定点输出 verdict：\"pass\"（明确且正确地说到了）、\"partial\"（沾边但不完整或有轻微偏差）、"
    "\"fail\"（没说、说错或概念混淆）。\n"
    "必须输出 JSON，格式：\n"
    '{"points": [{"id": "P1", "verdict": "pass|partial|fail", "evidence": "引用答案中的原句或写 无"}, ...], '
    '"comment": "一句话总评"}\n'
    "points 必须恰好 3 项，顺序与给定判定点一致。"
)

VERDICT_SCORE = {"pass": 1.0, "partial": 0.5, "fail": 0.0}


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
        return json.loads(resp.read().decode("utf-8"))


def judge(base, key, answer_text):
    user = (
        f"【题目】{QUESTION}\n\n"
        f"【判定点】\n" + "\n".join(RUBRIC) + "\n\n"
        f"【学生答案】\n{answer_text}\n\n"
        "请按判定点逐项判定，以 JSON 输出。"
    )
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
        ],
        "max_tokens": 1200,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "stream": False,
    }
    body = call(base, key, payload)
    raw = body["choices"][0]["message"].get("content") or ""
    usage = body.get("usage", {})
    data = json.loads(raw)
    pts = data.get("points") or []
    if len(pts) != 3:
        raise ValueError(f"points 数量异常: {len(pts)} | raw={raw[:200]}")
    scores = [VERDICT_SCORE.get(p.get("verdict"), 0.0) for p in pts]
    return {
        "score": round(sum(scores) / len(scores), 4),
        "verdicts": [p.get("verdict") for p in pts],
        "comment": data.get("comment", ""),
        "usage": usage,
        "raw": raw,
    }


def main():
    cfg = load_cfg()
    base = cfg["base_url"].rstrip("/")
    key = cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        print("!! 无 api_key")
        return 2

    print(f"S-H2 判分一致性 Spike  |  model={MODEL}  thinking=disabled  temp=0  runs={RUNS}")
    print("=" * 78)

    records = []
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0,
                   "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0}
    errors = []

    for ans in ANSWERS:
        runs = []
        for r in range(RUNS):
            try:
                res = judge(base, key, ans["text"])
                runs.append(res)
                u = res["usage"]
                for k in total_usage:
                    total_usage[k] += u.get(k, 0) or 0
            except urllib.error.HTTPError as e:
                errors.append(f"{ans['id']}#{r+1} HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{ans['id']}#{r+1} {type(e).__name__}: {e}")
            time.sleep(0.5)

        scores = [x["score"] for x in runs]
        rng = round(max(scores) - min(scores), 4) if scores else None
        mean = round(sum(scores) / len(scores), 4) if scores else None
        records.append({
            "id": ans["id"], "expect": ans["expect"],
            "scores": scores, "mean": mean, "range": rng,
            "verdicts": [x["verdicts"] for x in runs],
            "comments": [x["comment"] for x in runs],
        })
        flag = "OK " if (rng is not None and rng <= 0.05) else "!! "
        print(f"{flag}{ans['id']} 期望={ans['expect']:4s} 得分={scores} "
              f"均值={mean} 极差={rng}")

    print("=" * 78)

    # 一致性判定
    stable = [r for r in records if r["range"] is not None and r["range"] <= 0.05]
    print(f"[指标1] 极差 ≤ 0.05 的答案数: {len(stable)}/{len(records)}")

    # 分类正确性（4 份明确标注；A3 为边界，单独观察）
    decisive = [r for r in records if r["expect"] in ("pass", "fail")]
    correct = 0
    for r in decisive:
        if r["mean"] is None:
            continue
        got = "pass" if r["mean"] >= 0.6 else "fail"
        if got == r["expect"]:
            correct += 1
        else:
            print(f"      !! 分类错误: {r['id']} 期望 {r['expect']} 实得 {r['mean']} -> {got}")
    print(f"[指标2] 明确标注答案分类正确: {correct}/{len(decisive)}")

    borderline = [r for r in records if r["expect"] == "fail" and r["id"] == "A3"]
    if borderline:
        print(f"[观察] 边界答案 A3 得分={borderline[0]['mean']}（预期落在 0.5 以下）")

    cost_in = (total_usage["prompt_cache_miss_tokens"] or total_usage["prompt_tokens"]) / 1e6 * 1.0
    cost_hit = (total_usage["prompt_cache_hit_tokens"] or 0) / 1e6 * 0.02
    cost_out = total_usage["completion_tokens"] / 1e6 * 4.0
    cost = cost_in + cost_hit + cost_out
    print(f"[用量] 输入未命中={total_usage['prompt_cache_miss_tokens']} "
          f"命中={total_usage['prompt_cache_hit_tokens']} 输出={total_usage['completion_tokens']}")
    print(f"[成本] 本次总消耗 ≈ {cost:.5f} 元（按空闲时段价）")

    if errors:
        print(f"[错误] {len(errors)} 条:")
        for e in errors:
            print("      " + e)

    verdict = (
        "PASS" if (len(stable) == len(records) and correct == len(decisive)) else "REVIEW"
    )
    print("=" * 78)
    print(f"H2 结论: {verdict}")
    print("  通过标准 = 极差全部 ≤0.05 且 明确标注答案分类 100% 正确")

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(OUT_DIR, f"s_h2_{stamp}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "model": MODEL, "thinking": "disabled", "temperature": 0, "runs": RUNS,
            "question": QUESTION, "rubric": RUBRIC,
            "records": records, "errors": errors,
            "usage_total": total_usage, "cost_cny_estimated": round(cost, 5),
            "verdict": verdict,
        }, f, ensure_ascii=False, indent=2)
    print(f"结果已保存: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
