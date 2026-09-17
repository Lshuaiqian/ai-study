#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
"""把自检题写进体系文件。

为什么需要自检题
    桥接目前只能记 `code` 一维——因为导师没有结构化的问题可问、study 没有判定点可判。
    自检题（问题 + 判定点）是 quiz 维度的唯一依据，也是「一键整理」判掌握度的基础。

放置原则
    问题**不用自问自答式**（"什么是 X"），而要求解释、对比、给反例——
    这样才能区分"背过"与"懂了"。每题 3 个判定点，便于结构化判分。

用法：
    python study\\system\\add_self_check.py            # 预览
    python study\\system\\add_self_check.py --write     # 写回体系
"""
import io
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYSTEM_PATH = os.path.join(BASE, "system", "west2-ai-2026.json")

# 只给 Foundation 五课写（导师先教这一段）；其余课等用到再补
SELF_CHECK = {
    "west2-f0": [
        {"id": "Q1",
         "question": "在你自己的机器上，pip 装包很慢或直接失败，你会怎么排查？",
         "points": [
             "说出换镜像源（-i 参数或写进 pip 配置）",
             "能区分「源的问题」与「网络/代理问题」的排查路径",
             "知道虚拟环境能隔离依赖、避免污染全局 Python",
         ]},
        {"id": "Q2",
         "question": "Apple 中文排版规范里，什么时候加空格、什么时候不加？举出至少三条。",
         "points": [
             "中英文之间加空格",
             "中文与数字之间加空格，但数字与单位之间不加",
             "中文语境用全角标点，代码/英文语境用半角",
         ]},
        {"id": "Q3",
         "question": ".gitignore 是干什么的？如果一个很大的文件已经被 commit 了，再把它写进 .gitignore 还有用吗？",
         "points": [
             "说明 .gitignore 决定哪些文件不被 Git 追踪",
             "指出对**已被追踪**的文件无效，需要先 git rm --cached",
             "知道大文件不该进仓库（历史里会永久保留，clone 会变慢）",
         ]},
    ],
    "west2-f1": [
        {"id": "Q1",
         "question": "用一句话说清 Python 的 with 语句与 C++ RAII 的关系，并举一个**不是文件**的资源例子。",
         "points": [
             "说明 with 通过上下文管理器协议在退出时释放资源",
             "说出与 RAII 的相同点（作用域结束即释放）与不同点（Python 需显式写 with）",
             "举出非文件资源：锁、数据库连接、事务、临时目录",
         ]},
        {"id": "Q2",
         "question": "用嵌套列表推导式把 [[1,2],[3,4]] 转置成 [[1,3],[2,4]]，怎么写？求值顺序是怎样的？",
         "points": [
             "写出等价于 [[row[i] for row in m] for i in range(len(m[0]))] 的写法",
             "说明推导式的求值顺序（写在后面的 for 是外层循环）",
             "说明与手写 for + append 相比的可读性与性能差异",
         ]},
        {"id": "Q3",
         "question": "什么时候必须用类而不是函数？魔术方法（__str__ / __eq__ / __len__）到底解决什么问题？",
         "points": [
             "说明类用于把状态与行为绑在一起",
             "说明魔术方法让自定义类型融入语言自带协议（长度、打印、相等、运算）",
             "给出一个实际例子，并说明不用魔术方法会怎样",
         ]},
    ],
    "west2-f2": [
        {"id": "Q1",
         "question": "怎么判断一个网页是静态 HTML 还是 JS 动态渲染？如果是动态的，你怎么办？",
         "points": [
             "给出判断方法：对比直接请求拿到的响应与浏览器渲染后的 DOM",
             "指出响应里没有目标数据而页面有，说明是 JS 异步加载",
             "给出对策：找背后的 XHR/fetch 接口、用无头浏览器、或换数据源",
         ]},
        {"id": "Q2",
         "question": "robots.txt 是什么？爬之前要不要看？为什么必须限速？",
         "points": [
             "说明它在站点根目录声明可访问范围（User-agent / Disallow / Allow / Crawl-delay）",
             "明确态度：应遵守，属行业惯例而非技术强制",
             "说明限速的理由：不给对方服务器造成压力，也降低自己被封的风险",
         ]},
        {"id": "Q3",
         "question": "被 403 / 429 拦住时你怎么排查？这两个状态码有什么区别？",
         "points": [
             "403 = 服务器理解请求但拒绝执行（缺 UA / 缺登录态 / IP 被封禁）",
             "429 = 请求过于频繁，应降速 + 指数退避（必要时读 Retry-After）",
             "给出排查路径：先用 curl 手动复现 → 对比浏览器请求头 → 检查 cookie → 再调整策略",
         ]},
    ],
    "west2-f3": [
        {"id": "Q1",
         "question": "零样本分类为什么不用训练就能分类？它的局限是什么？",
         "points": [
             "说明模型已在大规模语料上预训练，具备通用语义理解",
             "说明做法：把候选标签当作文本提示，模型给每个标签打分",
             "指出局限：标签的措辞会显著影响结果，且无法处理它没见过的概念",
         ]},
        {"id": "Q2",
         "question": "BERT 的 [MASK] 填空与指令模型的对话，本质区别是什么？",
         "points": [
             "BERT 是掩码语言模型：双向看上下文，做填空/抽取",
             "指令模型是自回归生成：按 prompt 逐字续写",
             "说明用途差异：分类与抽取 vs 对话与生成",
         ]},
        {"id": "Q3",
         "question": "调用大模型时，为什么要在提示里限制输出格式（比如要求只输出 JSON）？",
         "points": [
             "说明输出要被程序消费，格式不稳就没法可靠解析",
             "说明约束越具体，模型越不容易跑偏（角色设定 / few-shot / 结构约束）",
             "举出一个具体的约束写法与它解决的问题",
         ]},
    ],
    "west2-f4": [
        {"id": "Q1",
         "question": "科研路线与应用路线分别看重什么能力？你选哪条，为什么？",
         "points": [
             "科研：数学基础、论文阅读、实验设计与复现",
             "应用：工程能力、系统设计、交付与协作",
             "明确说出自己的选择及理由（结合自身情况，不是复述）",
         ]},
        {"id": "Q2",
         "question": "答辩被追问时，对方通常从哪几个角度问？你该怎么准备？",
         "points": [
             "原理：为什么这么做，机制是什么",
             "取舍：有没有别的方案，为什么不用",
             "边界与坑：什么情况下会失效，踩过什么坑",
         ]},
    ],
}


def main():
    write = "--write" in sys.argv
    with open(SYSTEM_PATH, "r", encoding="utf-8") as f:
        system = json.load(f)

    changed = 0
    for c in system["courses"]:
        cid = c["course_id"]
        if cid not in SELF_CHECK:
            continue
        qs = SELF_CHECK[cid]
        c["self_check"] = qs
        n_pts = sum(len(q["points"]) for q in qs)
        print(f"  {cid:10s} {len(qs)} 题 / {n_pts} 个判定点")
        changed += 1

    print(f"\n共写入 {changed} 门课的自检题")
    if write:
        with open(SYSTEM_PATH, "w", encoding="utf-8") as f:
            json.dump(system, f, ensure_ascii=False, indent=2)
        print(f"已写回 {os.path.relpath(SYSTEM_PATH, BASE)}")
    else:
        print("（预览模式，加 --write 生效）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
