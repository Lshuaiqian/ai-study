"""gate · 迁移应用（transfer）维度的评分。

为什么单独做：`transfer` 是防"背答案 / 抄练习"的关键维度，也是原设计里唯一
让门禁真正有意义的一环——只有换了场景还能做出来，才说明知识是可迁移的。

复用 `gate.rubric.judge_answer` 的结构化判定点机制（H2 已验证的确定性方案），
换一套判定点与系统提示词即可。
"""
from gate.rubric import judge_answer

TRANSFER_SYSTEM = (
    "你是一个严格的技术判分器，正在评估学生是否**真的把知识迁移到了新场景**。\n"
    "重点不是代码写得好不好，而是判断：他是理解了方法，还是把原来的代码复制粘贴改了个名字。\n"
    "逐判定点给出 verdict：pass（明确做到）、partial（部分做到/有保留）、fail（没做到）。\n"
    "只有把概念搞反才置 fatal_misconception=true；「做得不够好」不算致命。\n"
    "必须输出 JSON：\n"
    '{"points":[{"id":"P1","verdict":"pass|partial|fail","evidence":"引用原句/代码或写 无"}],'
    '"fatal_misconception":false,"fatal_reason":"","comment":"一句话总评"}'
)

TRANSFER_POINTS = [
    "P1 真的换了目标对象（站点 / 页面 / 数据集不同），不是把原练习原样提交",
    "P2 复用了请求与抽取的框架，而不是把结果硬编码成新站点的特例（例：写死标题列表而非解析 DOM）",
    "P3 说明了改了哪几处、以及为什么这么改（体现理解，而不是碰运气跑通）",
    "P4 产物有效：说明了抓到多少条 / 结果结构合理，能看出真的跑过",
]


def score_transfer(llm, task, artifact_source, explanation=""):
    """评估迁移题产物。返回 {score, verdicts, evidence, fatal..., comment}。"""
    question = f"【迁移任务】{task['title']}\n{task['brief']}"
    answer = (
        f"【迁移产物代码】\n```python\n{artifact_source}\n```\n\n"
        f"【学生的说明】\n{explanation or '（未提供说明）'}"
    )
    res = judge_answer(llm, question, TRANSFER_POINTS, answer, system=TRANSFER_SYSTEM)
    res["points"] = TRANSFER_POINTS
    return res
