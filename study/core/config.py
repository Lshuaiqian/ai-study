"""core · 统一配置。

设计要点（由 S-H0/S-H2/S-H3 实测确定，见 docs/AI辅助学习-App-可行性深化（S4定案版）.md）：
  - 模型默认 deepseek-flash（1M 上下文 / JSON Output / 可选视觉）
  - 思考模式默认【关闭】：默认开启时会忽略 temperature 并吃掉 ~75-79% 输出预算
  - 判分 / 体检等需要确定性的调用必须 thinking=False + temperature=0

密钥解析顺序（**不许把任何真实密钥写进仓库**）：
  1. 环境变量 `DEEPSEEK_API_KEY`（推荐：CI 与多机共用都靠它）
  2. `study/config.json` 的 `api_key`（本地文件，已被 .gitignore 排除）
  3. 环境变量 `STUDY_KEY_FILE` 指向的任意配置文件（想复用别的 Agent 的
     config.json 就用它，**不要**在代码里写死别人机器上的绝对路径）

这里曾经有一行 `FALLBACK_CFG = r"E:\\Agents\\python-tutor\\config.json"`：
它把某台机器上的私有路径写死在共享代码里，别人 clone 下来跑不通，
而且谁本地复制了这个文件就会把密钥带进仓库。已删除。
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULTS = {
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-flash",
    "api_key": "",
    "thinking": False,            # 默认关闭思考模式
    "max_tokens_chat": 4000,      # 点评类
    "max_tokens_json": 2500,      # 结构化输出类
    "timeout_seconds": 120,
    "work_dir": os.path.join(BASE_DIR, "work"),
    "notes_dir": os.path.join(BASE_DIR, "notes"),
    "curriculum_dir": os.path.join(BASE_DIR, "curriculum"),
    "state_dir": os.path.join(BASE_DIR, "state"),
    # 价格（元/百万 tokens，空闲时段），仅用于成本估算
    "price": {
        "deepseek-flash": {"in_miss": 1.0, "in_hit": 0.02, "out": 4.0},
        "deepseek-v4-pro": {"in_miss": 4.5, "in_hit": 0.15, "out": 13.5},
        "deepseek-chat": {"in_miss": 1.0, "in_hit": 0.02, "out": 4.0},
    },
}


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def load_config():
    cfg = dict(DEFAULTS)
    cfg.update(_read_json(CONFIG_PATH))

    # 密钥：环境变量优先，其次本地 config.json（已被 .gitignore 排除），
    # 最后允许用 STUDY_KEY_FILE 指向一个外部配置文件（**由使用者自己指定**，
    # 而不是代码写死路径）。
    if not cfg.get("api_key"):
        cfg["api_key"] = os.environ.get("DEEPSEEK_API_KEY", "")
    if not cfg.get("api_key"):
        key_file = os.environ.get("STUDY_KEY_FILE", "")
        if key_file:
            cfg["api_key"] = _read_json(key_file).get("api_key", "")

    for key in ("work_dir", "notes_dir", "curriculum_dir", "state_dir"):
        os.makedirs(cfg[key], exist_ok=True)
    return cfg


def describe_key_source():
    """密钥是从哪来的——报错时用它给一句人话，别让人对着 401 猜。"""
    if _read_json(CONFIG_PATH).get("api_key"):
        return f"{CONFIG_PATH}（本地文件，已被 .gitignore 排除）"
    if os.environ.get("DEEPSEEK_API_KEY"):
        return "环境变量 DEEPSEEK_API_KEY"
    key_file = os.environ.get("STUDY_KEY_FILE", "")
    if key_file and _read_json(key_file).get("api_key"):
        return f"环境变量 STUDY_KEY_FILE → {key_file}"
    return ""


def price_of(cfg, model, hit_tokens, miss_tokens, out_tokens):
    p = cfg["price"].get(model) or next(iter(cfg["price"].values()))
    return (hit_tokens / 1e6) * p["in_hit"] + (miss_tokens / 1e6) * p["in_miss"] \
        + (out_tokens / 1e6) * p["out"]
