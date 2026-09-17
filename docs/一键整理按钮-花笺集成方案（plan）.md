# 花笺「一键整理」按钮 — 集成方案（plan 模式）

> 目标读者：实现这个按钮的人（很可能就是下一次会话的我自己）。
> 状态：**方案已定，未动工**。后端能力（整理 + 质询 + 反馈给 AI）已经跑通并验证，见文末 §9。

---

## 1. 目标与非目标

### 目标
在花笺（floral-notepaper）的笔记编辑界面加一个**「一键整理」按钮**，点一下就把当前这篇课程笔记走完
`整理 → 结构化反馈 → 落盘（三区覆写）→ 反馈进掌握度` 全流程，并把过程与结果**在花笺里看见**。

### 非目标（明确不做，避免范围失控）
- 不在花笺里**重写**整理逻辑。整理的大脑始终是 `study/notedoctor/tidier.py`，花笺只是**触发器 + 显示器**。
- 不做实时协作、不做云端同步。
- 不在 P1 里做批量（一次整理所有课程笔记）和质询按钮 —— 放 P3/P4。
- 不改花笺现有多级分类补丁（`PATCH-多层分类.diff`）的既有行为。

---

## 2. 为什么不是「加个按钮调一下 CLI」这么简单

三个必须先解决的前置问题，否则按钮会做成一个会咬人的东西：

| # | 问题 | 现状 | 后果（如果不管） |
|---|---|---|---|
| P-1 | **课程↔笔记的映射靠标题前缀** | `find_note()` 用 `CODE_LABEL[course_id] + "-"` 匹配标题，如 `F0-环境搭建` | 用户在花笺里把标题改成「环境搭建」→ 按钮报「找不到笔记」。**已核实这不是假设**：`services/notes.rs:917-923` 的 `update_note` 在标题变化时写新文件名并回收旧文件（文件名由 `safe_file_stem(title)` 生成），所以改标题＝改文件名 |
| P-2 | **整理要跑 30–90 秒、调 2 次模型** | CLI 是同步阻塞、结果打到 stdout | 直接 `invoke` 会卡死 UI 或让 WebView 假死；用户以为没反应就再点一次 |
| P-3 | **整理会覆写磁盘上的这篇笔记** | 花笺编辑器是**内存 buffer + 自动保存** | 用户手上有未保存的改动时点按钮 → 整理基于旧内容，随后花笺的自动保存又把整理结果盖回去 |

**结论：先补 CLI 契约（P-1、P-2），再动 UI（P-3 在 UI 层兜）。**

---

## 3. 前置改造 A：让笔记自带课程身份（解决 P-1）

### 3.1 脚手架写入课程标记
`scaffold.py` 创建/更新笔记时，在正文**顶部**写一行 HTML 注释（花笺渲染时不可见，改动最小）：

```markdown
<!-- study: course=west2-f0 stage=F0 -->
# F0 · 环境搭建
```

- 选 HTML 注释而不是 YAML frontmatter：花笺的 markdown 渲染链路（`src/features/markdown/`）对注释天然透明，不需要动渲染；YAML 会被当正文渲染出分隔线。
- `scaffold.py` 的 `update` 模式**只替换「✍️ 我的笔记」之前的头部**，这行标记正好在头部，会被幂等刷新（课程代号变了也能自愈）。

### 3.2 CLI 支持按路径定位
给 `study/tools/tidy.py` 与 `interrogate.py` 加一个参数：

```
--path "E:\Docs\usual\笔记\notes\西二AI-2026\<uuid>_F0-环境搭建.md"
```

解析顺序（每一步失败才退到下一步，全部失败才报错）：

1. `--path` 给出的文件 → 读开头的 `<!-- study: course=... -->`；
2. 没有标记 → 用**花笺 metadata.json 里的 id** 反查 `scan()` 到的标题前缀（兼容老笔记）；
3. 都没有 → 报错 `NOT_A_COURSE_NOTE`，附上「先跑 scaffold.py 建立课程笔记」的提示。

`--course` 与 `--path` 同时给出时 `--path` 优先（GUI 只传 `--path`）。

> 验收：把 F0 笔记标题改成「环境搭建」，`tidy.py --path <file>` 仍然能找到 `west2-f0`。

---

## 4. 前置改造 B：给 CLI 一个机器可读的输出契约（解决 P-2）

现在 CLI 打的是给人看的中文报告。GUI 去 `grep` 中文输出是**不可维护**的，所以加 `--json`：

```
python study\tools\tidy.py --path <file> --apply --json
```

stdout 变为 **JSONL（一行一个 JSON 对象）**，`stderr` 仍可放人类可读日志：

```jsonc
{"type":"stage","name":"load","msg":"已识别课程 west2-f0"}
{"type":"stage","name":"tidy","msg":"正在整理（1/2：改写）"}
{"type":"stage","name":"feedback","msg":"正在整理（2/2：结构化反馈）"}
{"type":"report","payload":{"coverage":0.61,"note_dimension":0.8133,
                           "gaps":[{"id":"K2","status":"partial","why":"..."}],
                           "todo":["补 IDE 配置"],"glossary_count":6}}
{"type":"done","ok":true,"course_id":"west2-f0","note_id":"af919b01-...",
 "changed":{"user_zone":false,"ai_zone":"replaced","history_appended":1},
 "version":"20260916-205258","note_path":"E:\\...\\af919b01-..._F0-环境搭建.md"}
```

失败时：

```jsonc
{"type":"error","code":"EMPTY_NOTES","msg":"「我的笔记」还是空的或只有模板注释"}
```

**退出码约定**（Rust 侧据此分类，不去解析文本）：

| 码 | 含义 | GUI 表现 |
|---|---|---|
| 0 | 成功 | 显示报告 + 「撤销本次整理」 |
| 1 | 用户可理解的失败（空笔记 / 模型失败 / 写入失败） | 黄色提示，可重试 |
| 2 | 参数错（课程不存在等） | 红色提示，属 bug |
| 3 | 不是课程笔记 / 找不到笔记 | 提示「这不是课程笔记」+ 引导 |

> 为什么必须做：`--json` 同时让「过程可见」和「可测试」。GUI 的每个分支都能被一个 JSON 断言覆盖，
> 不用开真窗口点按钮。

---

## 5. 后端改造（花笺 Rust 侧）

### 5.1 配置项
`src-tauri/src/services/notes.rs` 的 `AppConfig`（所有字段都有 `#[serde(default)]`，加新字段对旧 config 向后兼容）：

```rust
#[serde(default)] pub study_enabled: bool,          // 默认 false：不打扰不用它的人
#[serde(default = "default_study_root")]
pub study_root: String,                             // 默认 "E:\\Docs\\Code\\Java\\book"
#[serde(default = "default_study_python")]
pub study_python: String,                           // 默认 "E:\\Develop\\python\\python.exe"
#[serde(default = "default_study_timeout_s")]
pub study_timeout_s: u64,                           // 默认 180
```

设置页（`src/features/settings/`）加一组「学习助手」：开关、Python 路径、study 根目录、超时。
设置页要能**测连通**：调 `study_ping`，跑 `python -c "import sys;print(sys.version)"` 并回报。

### 5.2 新命令（注册进 `src-tauri/src/lib.rs:470` 的 `generate_handler!`）

| 命令 | 作用 |
|---|---|
| `study_ping() -> {ok, python_version, study_root, error}` | 设置页的连通性检查 |
| `study_tidy_start(note_path, apply: bool) -> {run_id}` | 起一个后台整理；`apply=false` 即预览 |
| `study_tidy_cancel(run_id)` | 取消（杀子进程） |
| `study_tidy_rollback(note_path, version) -> {ok}` | 撤销：调 `tidy.py --rollback <version>` |

新建 `src-tauri/src/services/study.rs`（与 `notes.rs` 平级，保持模块化）。

### 5.3 流式与生命周期
- `std::process::Command` + `Stdio::piped()`，**在 `std::thread::spawn` 里逐行读 stdout**，
  每读到一行就 `app.emit("study://tidy/event", line)`。这个「线程 + emit」的模式 `desktop.rs` 已经在用（`start()` / `emit_from_message`），照抄即可。
- **必须在同一个线程里做 `child.wait()` 并在超时后 `child.kill()`**，否则取消/超时会留下孤儿 python 进程。
- 一个 `note_path` 同时只允许一个 run：用 `Mutex<HashMap<String, RunHandle>>` 做互斥，
  重复点按钮直接返回已有 `run_id`（防止用户狂点触发 4 次模型调用）。
- Windows 下要 `CREATE_NO_WINDOW`，否则会闪一个黑框。

### 5.4 安全边界（重要）
`study_tidy_start` 会**执行一个用户可配置路径下的可执行文件**，本质是任意命令执行入口。

- 只接受 `note_path` 与 `apply` 两个参数，**绝不接受任意命令行**；
- `note_path` 必须落在花笺自己的 `notesDir` 下（`canonicalize` 后做前缀校验，防 `..` 穿越）；
- `python` 与脚本路径由配置拼装，不由前端传入。

---

## 6. 前端改造

### 6.1 交互状态机

```
        点「一键整理」
idle ──────────────────▶ saving        把未保存的 buffer 先落盘（notes_update）
                            │            失败 → failed
                            ▼
                        previewing     跑 apply=false，拿报告（约 30s，进度条 + 可取消）
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
        有内容可整（报告非空）          EMPTY_NOTES
              │                           │
              ▼                           ▼
        confirming                  提示「先写点东西」
        「将改写 🤖 AI 整理 区，           （按钮置灰，不弹窗）
          你的笔记一字不动」
              │ 确认
              ▼
         applying ──▶ done       显示报告 + 「撤销本次整理」/「去花笺里看看」
              │
              └──▶ failed        显示 code + msg + 「重试」
```

**为什么必须两步（preview → confirm）**：整理会动用户的真实笔记文件。一步到位的按钮在
「笔记还是模板」或「模型理解偏了」时会做一次无意义的改写，而用户只看到笔记变了。
预览模式的成本是**一次额外模型调用**（约 0.006 元）；这个钱值得花。

### 6.2 关键：脏 buffer 冲突（P-3 的解法）

- 点按钮 → 先 `notes_update` 强制保存当前笔记，**等保存确认后**再起整理；
- 整理完成（`done` 事件）→ 从磁盘 `notes_get` 重新读回，替换编辑器内容；
- **但**若在整理期间用户又改了 buffer（比较 `updatedAt` / `wordCount`），**不要静默覆盖**，
  弹冲突对话框：「笔记在你整理期间被修改过，要[重新整理] / [保留你的修改并丢弃整理结果]」。
- 整理期间把编辑器置为**只读**并显示「AI 正在整理…（可取消）」横幅，从源头上减少冲突。

### 6.3 UI 落点
- **P1**：`src/components/MainWindow.tsx` 的编辑器工具栏加一个按钮 + 一个侧边/底部「整理报告」抽屉。
  报告直接渲染 §4 的 `report.payload`：覆盖率进度条、逐知识点 ✅🟡⚪、术语表、查缺补漏清单（可勾选）。
- **P2**：报告里的「查缺补漏」项加「复制到我的笔记」按钮（把待办写进「✍️ 我的笔记」区的末尾）——
  这样下一轮整理能看到它。
- **P3**：`src/components/NoteWall.tsx`（便签墙）加多选 + 批量「一键整理」，队列化跑，逐个报结果。
- **P4**：加「AI 质询」按钮，对应 `interrogate.py --write-back`，写入独立的「🧪 AI 质询」区。

### 6.4 前端文件约定
沿用现有 `features/<域>/api.ts` + `api.test.ts` 的写法，新建：

```
src/features/study/api.ts          // invoke 封装 + 事件订阅（listen("study://tidy/event")）
src/features/study/api.test.ts     // mock invoke / listen，覆盖 §6.1 每个分支
src/features/study/useTidyRun.ts   // 状态机 hook（idle/saving/previewing/confirming/applying/done/failed）
src/features/study/TidyPanel.tsx   // 报告抽屉
```

`useTidyRun` 用纯函数 reducer 实现状态机，这样 §6.1 的转移可以在 vitest 里全测，不需要真窗口。

---

## 7. 分阶段与验收标准

| 阶段 | 内容 | 验收（可测，不靠肉眼） |
|---|---|---|
| **P0** | CLI 前置改造：`--path`、课程标记、`--json`、退出码 | 单测：改名后仍能定位课程；`--json` 每行 `json.loads` 通过；四个退出码各有一个用例 |
| **P1** | Rust `study_ping` / `study_tidy_start` / `cancel` + 前端按钮 + 报告抽屉 + preview→confirm | `cargo test` 覆盖：非 notesDir 路径被拒、超时被杀、重复点击复用 run；vitest 覆盖状态机全部分支 |
| **P2** | 脏 buffer 冲突对话框 + 撤销按钮 + 查缺补漏回填 | 手动场景脚本走一遍：边改边整理、整理后立即撤销，笔记回到整理前状态 |
| **P3** | 便签墙批量整理 | 批量 5 篇：一篇空笔记不阻塞其余；结果逐条可查 |
| **P4** | 质询按钮 | 质询区与整理区共存不互相吞并（已有 `verify_note_loop.py` 33 项断言可直接复用） |

每个阶段结束都跑一次：
```
python -m unittest discover -s study\tests          # 333 项
python study\integrations\verify_tidy_apply.py      # 49 项
python study\integrations\verify_note_loop.py       # 33 项
pnpm vitest run && pnpm tauri build --debug         # 花笺侧
```

---

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| 模型慢/挂 → 按钮像卡死 | 逐行流式事件 + 进度条 + 超时可配 + 可取消 |
| 整理把用户写的东西改坏 | 三区隔离（已实现且有 33 项端到端断言）；预览→确认两步；撤销按钮；整理期间编辑器只读 |
| 用户狂点按钮烧钱 | 同一笔记 run 互斥，重复点击复用 `run_id` |
| python 路径/study 路径配错 | `study_ping` 显式体检，给出人话原因，不要让按钮无声失败 |
| 花笺上游改动导致 patch 冲突 | 改动集中在 3 个文件（`services/notes.rs`、`lib.rs`、`MainWindow.tsx`）+ 1 个新目录，冲突面小；优先提 PR 而非长期维护 fork |
| 用户没装 python | `study_enabled` 默认 false；`study_ping` 失败时按钮隐藏，不显示报错 |

---

## 9. 已经就绪的后端能力（本次会话完成并验证）

按钮要调的东西**已经能跑**，且有端到端验证撑着：

- **`study/tools/tidy.py`** —— 一键整理。三区模型：
  ```
  ## ✍️ 我的笔记     ← 用户的区：AI 永不改动
  ## 🤖 AI 整理       ← 整块替换（幂等，不会越整理越长）
  ## 🧪 AI 质询       ← 整块替换（与整理区并列，互不吞并）
  ## 📚 整理历史      ← 只追加，可回滚
  ```
  整理稿落盘到 `state/note_versions/<note_id>/<ts>.md`，`--rollback <ts>` 可回到任一版。
- **反馈给 AI 已闭环**：整理出的缺口写进 `state/findings/<course>-tidy.json`，
  `interrogate.py` 下次质询会把它读进来并**优先追问**这些点
  （实测输出 `↻ 带入上一轮整理的 5 个缺口`，追问精准打在 K2/K8 上）。
- **不会 AI 给自己打分**：`split_note` 在 AI 区边界截断，AI 写的整理稿不计入覆盖率/掌握度。
- **不摘牌**：笔记里没写到 ≠ 没掌握；已通过的知识点只标 `note_gap` + `recheck_due`，不翻 `passed`。
- **预览零副作用**：不加 `--apply` 时不写笔记、不改掌握度、不塞回炉队列。
- 端到端断言：`verify_tidy_apply.py` 49 项、`verify_note_loop.py` 33 项，全绿。

### 尚未接上的一环（需你确认，再动）
质询的结论目前**只回填到笔记的质询区**，没有写进 `state/mastery.json`。
也就是说：`达成度 44%` 显示给你看、也留在笔记里，但**门禁/Planner 读不到它**。

要不要写进去，取决于一个策略选择：
- **写**：质询 verdict 进 `atoms`（沿用「不摘牌」规矩），Planner 就能把缺口排进复习；代价是
  笔记质询的权重实际上变成了掌握度的一部分，需要重新校准 `gate/mastery.py` 的四维权重。
- **不写**：质询只是「体检报告」，掌握度只由代码/测验/迁移/笔记四维决定。

我倾向**写**，但先等你定，因为它会改评分语义。

---

## 10. 需要你拍板的三件事

1. **质询结论要不要进掌握度**（§9 末尾）——影响评分语义。
2. **按钮放哪**：编辑器工具栏（单篇，P1）先做；便签墙批量（P3）要不要一起排期。
3. **要不要给花笺提 PR**：改 3 个文件 + 加 1 个模块，比长期维护 fork 划算；但走 PR 会被 upstream review 节奏牵制。
