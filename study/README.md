# study · AI 辅助学习 App（P0 单课掌握闭环）

这是 `goal-c45413f5-6200-451a-a4b4-03a15d6f4f5a` 的实现目录。
设计依据：`../docs/AI辅助学习-App-系统设计（融合版）.md`、`../docs/AI辅助学习-App-可行性深化（S4定案版）.md`

> **临时位置说明**：本目录暂放在 `book` 工作区内（本会话唯一可写目录），
> 最终应整体迁到 `E:\Docs\Code\Java\study`。搬运时只需拷贝整个 `study/` 目录，无外部依赖。

---

## 已实现（P0）

| 模块 | 文件 | 状态 |
| --- | --- | --- |
| 统一配置（模型 / 思考模式 / 预算 / 密钥解析） | `core/config.py` | ✅ |
| DeepSeek 客户端（固化实测结论） | `core/llm.py` | ✅ |
| 原子写盘 / JSON 读写 | `core/store.py` | ✅ |
| **四维掌握度 + 门禁 + 逃生阀 + L1/L2/L3 + 回炉** | `gate/mastery.py` | ✅ 纯逻辑 |
| 代码实践维度（机检 + 点评合成） | `gate/codecheck.py` | ✅ |
| 自检判分器（H2 验证方案） | `gate/rubric.py` | ✅ |
| **迁移题评分**（防背答案） | `gate/transfer.py` | ✅ 复用判定点机制 |
| **代码导师**（逐行点评 → `findings.json`） | `tutor/reviewer.py` | ✅ 四段式 + 结构化 |
| **练习代码执行器**（路径白名单 / 超时 / 依赖检测） | `tutor/runner.py` | ✅ |
| **笔记医生**（覆盖确定性 + 准确带出处） | `notedoctor/doctor.py` | ✅ H3 验证方案 |
| 第 3 课课程定义（知识点声明 / 任务 / 验收 / 门禁） | `curriculum/py_agent_03.json` | ✅ |
| 第 1、2 课 declares（补上前置，跨课边才成立） | `curriculum/py_agent_0{1,2}.json` | ✅ 内容待 S-H1 补资料 |
| **知识点 DAG 构建 + 校验**（环 / 未知引用 / 写法不一致） | `graph/builder.py` | ✅ |
| **体系图渲染**（路线状态 / 知识点 Mermaid / 自洽性检查） | `graph/render.py` | ✅ |
| 路线骨架（9 课，课程级硬前置） | `route.json` | ✅ |
| 体系图 CLI | `tools/render_graph.py` | ✅ |
| **课程准入门禁**（开课之前查前置，补上"单课可绕过路线"的洞） | `flow/entry.py` | ✅ |
| **事件日志**（自省机制的数据底座，JSONL append-only） | `plan/events.py` | ✅ |
| **复习队列 + 间隔阶梯**（回炉/待复查/到期，按深度排序） | `plan/review.py` | ✅ |
| **今日视图 + 自省周报** | `plan/report.py` | ✅ |
| Planner CLI | `tools/plan.py` | ✅ |
| **花笺（floral-notepaper）连接器**（读/写普通 Markdown + metadata.json） | `notes/huajian.py` | ✅ 已连上真实数据 |
| 花笺 CLI（info / list / read / reconcile / new / import） | `tools/huajian.py` | ✅ 默认只读 |
| **python-tutor → 4.1-flash 迁移 + 视觉**（可回滚） | `integrations/migrate_py_tutor.py` | ✅ 已应用并验证 |
| 端到端运行器 | `p0_demo.py` | ✅ |
| 确定性单测 | `tests/` | ✅ **201 项** |

## 实测结论（已固化进代码）

1. **思考模式必须显式关闭**：`{"thinking": {"type": "disabled"}}` 是唯一有效写法
   （`enable_thinking: false` 实测无效）。默认开启时会**忽略 `temperature`**，
   并吃掉 **~75–79% 的输出预算**。
2. **判分必须走结构化判定点** + `temperature=0` + `JSON Output`，
   否则不可复现（H2 实测：该组合下极差 0.0）。
3. **`deepseek-chat` 仍可用**，但新功能按 `deepseek-flash` 设计。
4. **环境缺依赖 ≠ 学生写错**：课程把 BeautifulSoup 标为"可安装增强"，而本机
   确实没装 bs4。`runner.check_imports()` 先做依赖检测，Tutor 提示词里明确
   "因此跑不通不要算作学生的错误"。

## 运行

```bat
:: 单元测试（纯计算 + 子进程执行，不联网）
E:\Develop\python\python.exe -m unittest discover -s study\tests

:: 端到端闭环（真实调用 API + 真实运行爬虫，约 0.03 元）
E:\Develop\python\python.exe study\p0_demo.py
E:\Develop\python\python.exe study\p0_demo.py --no-run   :: 跳过网络运行
```

密钥解析顺序：`study/config.json` → 环境变量 `DEEPSEEK_API_KEY` →
复用 `E:\Agents\python-tutor\config.json`。**不需要**在这里再存一份密钥。

## 端到端验证结果（最近一次真实运行）

```
场景 A · 首次提交
  code 0.8400 | quiz 0.7778 | note 0.7800 | transfer 0.0000
  mastery 0.6444  < 0.85  → ❌ 未通过
  失败原因：总分不足 / transfer 未交 / 必会覆盖 80%
  处置：L1_补练（针对 transfer 追加任务）· 带疑点前进：可用
场景 B · L1 补练后重新提交
  code 0.8720 | quiz 0.7778 | note 0.9350 | transfer 1.0000
  mastery 0.8866  ≥ 0.85  → ✅ 通过
全程 11 次调用，成本 ≈ 0.027 元
```

真实验证到的行为：

- **Tutor 点评逐行锚定**：如"第 44 行 403 直接 return None 不重试"、
  "第 51 行退避 sleep 未更新 `_last_request_at`"，并给 C++ 对照与引导追问，**不代写**
- **`findings.json` 落盘** → `knowledge_gaps: ["K3"]` 直接进掌握度模型并触发回炉
- **迁移题评分识别"真迁移 vs 抄练习"**：4/4 判定点 pass，评语指出"区分了爬虫骨架
  与站点特定解析"
- **笔记医生抓错带出处**：植入错误被判 `major` 且 `source_ref=M2` 正确
- **无依据不硬判**：资料未覆盖的说法降级为 `❓ 待你核对`
- **真实运行**：示例爬虫实跑抓到 60 条（书名/价格/星级/链接齐全）

## 知识点体系图（第 4 轮）

```bat
E:\Develop\python\python.exe study\tools\render_graph.py --course py-agent-03 --soft
E:\Develop\python\python.exe study\tools\render_graph.py --out study\state\graph.md
```

两层节点（9 门课 + 16 个知识点）与四类边：`requires` 硬前置、`part_of` 结构、
`contrast` 对比（含"手写 html.parser vs BeautifulSoup"这类真对比）、
`applies_to` 会用到哪。校验器会报出：环、未知引用、以及
**人写的 `declares` 与 `route.json` 不一致**（第 4 轮就靠它抓出两处）。

第 3 课的知识点真的连回了第 1、2 课，例如：

```
K2 HTML 结构基础与简单解析
   ← 前置：L1 语法+OOP K3 class 与魔术方法
      ｜写 HTMLParser 子类需要 class 与继承——这是真实依赖，不是摆设
K4 反爬初步
   ← 前置：L2 HTTP/JSON K1 HTTP 方法与状态码
   ← 前置：L1 语法+OOP K2 异常处理 try/except/with
```

**它抓到的两个真实问题**（见下节）。

## Planner：今日视图 + 自省周报（第 5 轮）

```bat
E:\Develop\python\python.exe study\tools\plan.py
E:\Develop\python\python.exe study\tools\plan.py --today 2026-09-17
```

三件东西：

1. **课程准入门禁** `flow/entry.py` —— 补上真实的洞：`gate.evaluate()` 只做课程内部判定，
   不知道前置课过没过。第 4 轮体系图抓到过"第 3 课已通过但前置未通过"，
   说明单课闭环能被绕过。现在开课之前必须先过 `entry_check`；
   **已通过的课不允许直接重进**（需显式重修）。
2. **复习队列** `plan/review.py` —— 不是 FSRS，也不假装是。P0/P1 只要一个能跑、可解释、
   可测的阶梯：`INTERVALS = [1, 3, 7, 16, 35]` 天，通过则 stage+1，没通过则归零。
   三类入口：`review_queue`（回炉）/ `recheck_due`（待复查）/ `next_review`（到期）。
3. **自省周报** `plan/report.py` —— 代码量、掌握度变化、笔记最弱维度、回炉记录，
   外加**课末复盘三问留空给你作答**（AI 不打分——一旦打分就会变成应付）。
   建议部分强制可执行，不写"继续加油"。

真实输出（本次运行）：

```
【复习 9】
  · py-agent-02:K1  HTTP 方法与状态码        [回炉未清]  stage=0
  · py-agent-02:K2  URL 结构与 Header        [待复查]  stage=0  depth=1
  · py-agent-03:K3  礼貌爬取                 [待复查/到期复习]  depth=2
【代码量】
  有效代码行合计 523（2 次提交）
【掌握度变化】
  第 3 课：0.6557 ↑ 0.8755
【笔记质量】
  平均 0.8575｜最低 0.7800   最弱维度：linking(0.50)、accuracy(0.75)
```

## 开发过程中被实跑/校验揪出的 8 个问题

| # | 问题 | 修正 |
| --- | --- | --- |
| 1 | **示例爬虫抽 0 条**：`article` 里第一个 `<a>` 是封面图链接，解析器把它的 href 当成了详情链接，`title` 永远为空 | 用 `_in_h3` 状态机区分 `h3 > a`；修后实跑 60 条 |
| 2 | **`code` 公式逆向激励**：按 `style 0.05 / warn 0.15` 线性扣分，Tutor 认真给 4 warn + 3 style → 扣 0.75 → 场景 B 反而**未通过**（点评越认真分数越低） | 改为 `error 0.30 / warn 0.08 / style 0`，并**扣分封顶 0.5** |
| 3 | **回炉重复惩罚**：单测断言"同一原子反复回炉应累计打折"失败（1≠2） | 确认实现正确、断言错误：已被打回且未补练通过的原子不应重复打折 |
| 4 | **演示绕过了路线**：体系图报"第 3 课已通过但前置 L2 未通过" | 不是 bug 而是图该有的告警；按真实 `progress.json` 补齐前置后自洽，并新增 `flow/entry.py` 把检查变成硬门禁 |
| 5 | **回炉缺少级联处理**：把 `py-agent-02:K1` 打回后，依赖它的 `K2/K4/K5` 仍标"已通过" → 自洽性报矛盾。但**硬性连带打回是错的** | 新增 `cascade_recheck`：标 `recheck_due`（最多追 3 层），**不翻转 `passed`** |
| 6 | **`course_status` 漏判"进行中"**：只看 `lessons` 记录，忽略"已练但未结算"的课，导致该课显示成"未开始" | 改为：只要有该课的知识点活动就算 in_progress |
| 7 | **周报建议编号错乱**（`1) 1) 3)`）：循环里硬编码了 `1)`，别处又用 `len(out)+1` | 统一用 `enumerate(..., 1)` |
| 8 | **周报与今日视图的待复习数量对不上**（7 vs 9）：`weekly_report` 没接收 `today`，用了系统日期 | 加 `today` 参数并在 CLI 透传；补了一致性测试 |

## 花笺连接与 py 学习 agent 迁移（第 6 轮）

### 花笺（floral-notepaper）——**能连，而且很容易**

源码核实（`Achilng/floral-notepaper`，Tauri 2 + React，MIT）：**笔记就是普通 Markdown**，
没有任何私有格式：

```
<data_dir>/config.json     设置，notesDir 可自定义
<data_dir>/metadata.json   {"notes":[{id,title,fileName,category,createdAt,...}]}
<notesDir>/<分类>/<id>_<标题>.md
```

你本机的实际情况（只读扫描得到）：

```
data_dir   C:\Users\Lshuaiqian\Documents\花笺
notes_dir  E:\Docs\usual\笔记\notes          ← 你自定义过
磁盘 4 篇 / metadata 5 条
reconcile 发现：metadata 里的 30d7efc2 文件不在新目录
                → 花笺里现在会显示成一篇空笔记（可清理）
```

`notesDir` 指向 `E:\Docs\usual\笔记\notes`，正是之前那批 UUID 命名的 md —— 全部对上了。

**文件夹能力：花笺已经有，只是只有一层。** 升级到多层是小改动（后端约 40 行），
详见 `refs/floral-notepaper/PATCH-多层分类.md`。关键发现：写路径是
`PathBuf::join(category)`，Rust 在 Windows 上也把 `/` 当分隔符，
所以 `category="工作/2026"` **现在就能写进 `notes/工作/2026/`**——
要改的只有「扫描递归」和「分类名校验放行 `/`」。

本 App 侧连接器**已按多层实现**，花笺支持多层后这边不用再改。

### python-tutor → deepseek-flash（4.1 Flash）+ 视觉

迁移脚本 `integrations/migrate_py_tutor.py`（先备份，`--rollback` 可还原）已应用：

| 改动 | 内容 |
| --- | --- |
| 模型 | `deepseek-chat` → **`deepseek-flash`** |
| 思考模式 | 显式 `thinking=false`（`chat_once` 里发 `{"type":"disabled"}`）；**仅在非思考模式下发 temperature** |
| max_tokens | 1500 → **4000**（思考模式实测会吃掉 75–79% 预算，1500 会让四段式点评被腰斩） |
| 读取上限 | `FILE_READ_LIMIT` 6000 → **12000** |
| **视觉** | 新增 `read_image` 工具：把练习区的截图交给视觉模型，返回文字描述给主循环 |

`integrations/verify_py_tutor.py` 的实测结果（**调的是它自己被改过的函数**）：

```
✅ tutor.py 编译通过
   model=deepseek-flash thinking=False max_tokens=4000 vision_model=deepseek-flash
   chat_once 实调 → '可用'，reasoning_tokens=None  ← 思考模式确实关闭
   tool_read_image 实调 → 3863 字符，准确抄出 NO_PUBKEY / docker-ce 等关键信息
   越界保护 → ..\..\config.json 被拒绝
```

**视觉实测结论**：终端截图能准确 OCR，3 秒 / 998 tokens（≈0.004 元/张）。
这意味着**可以砍掉 SiliconFlow + PaddleOCR 那条独立链路**，单供应商即可。

## 已知残余方差（诚实记录）

`quiz` / `note` / 门禁判定在 `thinking=disabled + temperature=0` 下**逐字可复现**。
但 Tutor 的 `findings` **条数**是开放式的——同一份代码两次运行可能给出 4 条或 5 条 warn，
实测 `code` 波动约 **±0.03**。

本次结论不受影响（A 低于门限 0.21，B 高于门限 0.04），但**贴近阈值时需二次判定兜底**。
候选缓解手段（未实装）：Tutor 跑两次取 warn 条数较少者；或对 warn 采用递减权重。

## 尚未实现（诚实清单）

| 项 | 说明 |
| --- | --- |
| `quiz` 多次判定取中位数 | H2 显示单次极差已为 0；冗余判定留作阈值边界保护，未实装 |
| 学习库原子抽取（S-H1） | `curriculum/*.json` 的 `materials.atoms` 是**种子内容**，待真实资料替换 |
| 知识点 DAG 可视化 | 课程 JSON 已有 `prerequisites` / `unlocks`，尚未渲染成图 |
| Planner / 周报 / 复习队列 | 回炉机制已实现，排程与报告未做 |
| 飞书管道 | 复用 `E:\Agents\feishu-notes`，尚未接入 |
| Web UI | 目前是 CLI 运行器 |

## 目录结构

```
study/
├── curriculum/py_agent_03.json   # 课程定义（知识点声明 / 任务 / 验收 / 门禁 / 学习库视图）
├── core/                         # 配置 / LLM 客户端 / 原子写盘
├── gate/                         # 掌握度模型 / 机检 / 判分器 / 迁移评分
├── tutor/                        # 代码导师（点评 + findings.json）/ 执行器
├── notedoctor/                   # 笔记医生（体检报告）
├── demo/                         # 演示素材（爬虫 / 笔记 / 自检答案 / 迁移说明）
├── state/mastery.json            # 掌握度状态（可删除重建）
├── state/findings/*.json         # 每次点评的结构化结果
├── state/run/                    # 练习代码的真实运行工作目录
└── tests/                        # 60 项确定性单测
```
