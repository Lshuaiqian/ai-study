# Phase 1（P0）· Markdown 笔记记录与管理模式 · 详细设计

> 上游文档：`AI辅助学习-App-可行性分析.md`
> 目标：把"能记、能找、能管"的 Markdown 笔记闭环做成可运行版本
> 范围红线：**本阶段不做 AI、不做飞书同步、不做 PDF 解析**

---

## 1. P0 要回答的唯一问题

> **「我用这个记一学期课，会不会想退回飞书文档？」**

如果不会 → 继续投 P1。如果会 → 先修交互，别急着上 AI。
因此 P0 的每一个设计决策都优先服务**记录速度**和**找回速度**。

---

## 2. 三种记录模式

| 模式 | 场景 | 交互要点 |
| --- | --- | --- |
| **快速捕获 Quick Capture** | 上课/看书时脑子里闪过一句 | 全局快捷键（`Ctrl+Shift+N`）唤起浮层，只写纯文本，回车即存进 `inbox/`，**不打断当前动作** |
| **源码模式 Source** | 写公式、代码、表格 | CodeMirror 6，左侧行号，`Tab` 缩进，`Ctrl+B/I/K` 加粗/斜体/链接，粘贴图片自动落盘并插入 `![](attachments/xxx.png)` |
| **所见即所得 WYSIWYG** | 边听边整理 | 富文本编辑，但**落盘永远是 Markdown**（序列化器是核心组件，必须单测覆盖） |
| **分屏预览 Split** | 校稿 | 左源码右渲染，滚动同步 |

**共同规则**：
- 自动保存：编辑停止 800ms 后落盘（防抖），另加 `Ctrl+S` 立即保存
- 每次落盘写一份快照到 `.history/<note-id>/<timestamp>.md`（保留最近 50 个）
- 所有模式共享同一份 md，切换模式不丢格式

---

## 3. 笔记文件格式（本地 = 唯一真源）

### 3.1 目录结构

```
study/
├── notes/                          # 笔记正文（人可读、可被 Git 管理）
│   ├── 数据结构与算法/
│   │   ├── 01-复杂度分析.md
│   │   ├── 02-线性表.md
│   │   └── _course.md              # 课程元信息（目标/大纲/资料清单）
│   └── 操作系统/
│       └── ...
├── inbox/                          # 快速捕获的原始速记，待整理
│   └── 2026-02-14-1032.md
├── attachments/                    # 图片与附件（按 年月 分子目录）
├── templates/                      # 笔记模板
├── .history/                       # 版本快照
└── study.db                        # 索引与元数据（可随时重建）
```

**原则**：
1. **删掉 `study.db` 不丢任何内容**——所有检索、标签、双链都能从 md 重建。数据库只是缓存。
2. 文件名 = `NN-标题.md`（`NN` 保证课程内顺序），标题重复时追加短哈希。
3. 用户可用任何编辑器/同步盘/Git 直接操作这些文件，App 不产生私有不透明格式。

### 3.2 Frontmatter 规范

```markdown
---
id: n_7f3a91c2                  # 不可变，创建时生成（短 ULID），重命名不改
title: 复杂度分析
course: 数据结构与算法           # 与 _course.md 的 course 字段对应
chapter: 01                     # 章节序号（排序用）
order: 10                       # 章内排序
tags: [算法, 时间复杂度, 面试]
status: active                  # inbox | active | archived
source:                         # 资料来源（P2 才自动填充，P0 手动）
  - type: book
    ref: 《算法导论》第 3 章
created: 2026-02-14T10:32:00+08:00
updated: 2026-02-14T15:20:11+08:00
review_at:                      # 复习日期（P2 由 FSRS 填充）
feishu_node_token:              # 发布后回写，用于幂等更新
content_hash: 3f9a...           # 正文（不含 frontmatter）的 sha256 前 16 位，用于冲突检测
---

# 复杂度分析

正文……
```

**设计说明**：
- `id` 与文件名解耦：重命名/移动文件不会断链、不会丢历史
- `content_hash` 是后续双向同步冲突检测的基础，P0 就先写好
- 未知字段一律保留（避免第三方工具写入的字段被 App 抹掉）

### 3.3 正文中的约定语法

```markdown
[[线性表]]                       # 双链（P1 生效，P0 先解析并建立索引）
[[线性表#数组实现]]              # 指向标题
![[线性表]]                      # 嵌入（P2）
^blk-4f2a                        # 块锚点，供块引用
- [ ] 复习栈与队列的三种实现      # 待办 → P1 抽为学习任务
> [!tip] 考点                    # Callout（渲染层支持）
$$O(n\log n)$$                   # 行间公式
```mermaid ... ```                 # 图表
```

---

## 4. 管理模型：三个正交维度

草图的"笔记管理"不能只做成文件夹树，需要三个互相独立的维度：

| 维度 | 载体 | 回答的问题 | 举例 |
| --- | --- | --- | --- |
| **课程 / 章节** | 目录 + frontmatter | "这门课学到哪了" | 数据结构 → 01 复杂度分析 |
| **标签** | `tags:` | "这个主题在哪些课里出现过" | `#时间复杂度` 横跨算法、操作系统 |
| **双链 / 反链** | `[[...]]` 解析 | "这个概念依赖什么、被谁用到" | 动态规划 ← 最优子结构 |

**侧边栏三件套**（P0 只做前两个）：
1. **课程树**：课程 → 章节 → 笔记，支持拖拽移动（改 frontmatter + 移动文件，原子操作）
2. **标签云 / 标签筛选**：多标签交集筛选
3. **反链面板**（P1）：当前笔记被哪些笔记引用 + 引用上下文片段

**检索**（P0）：
- SQLite FTS5，中文采用 **trigram 分词**（避免引入分词词典依赖）；P1 若效果不佳再换 jieba 预处理
- 检索范围：标题 / 正文 / 标签 / frontmatter 全部字段
- 结果高亮 + **定位到命中段落**，而不是只给文件名
- 支持检索语法：`tag:算法 course:操作系统 "精确短语" -排除词`
- 热键 `Ctrl+P` 唤起命令面板（笔记跳转 + 命令执行二合一）

---

## 5. 本地 API 设计

沿用现有 `book` 项目的风格：纯 JDK、`com.sun.net.httpserver`、`{ok, data}` 响应包装。

### 5.1 笔记

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/notes?course=&tag=&status=&sort=&page=&size=` | 列表（读索引，不扫盘） |
| `POST` | `/api/notes` | 新建 `{title, course, chapter, tags, content}` |
| `GET` | `/api/notes/{id}` | 详情（返回 `content` 原始 md + 渲染后的 html） |
| `PUT` | `/api/notes/{id}` | 保存 `{content, baseHash}`；`baseHash` 不匹配 → `409` 冲突 |
| `PATCH` | `/api/notes/{id}/meta` | 只改元信息（标题/标签/课程/状态），不触发正文冲突 |
| `POST` | `/api/notes/{id}/move` | 移动课程/章节（原子改 frontmatter + 文件路径） |
| `DELETE` | `/api/notes/{id}` | 软删除（移到 `.trash/`） |
| `GET` | `/api/notes/{id}/history` | 快照列表 |
| `POST` | `/api/notes/{id}/restore/{ts}` | 回滚到某个快照 |
| `GET` | `/api/notes/{id}/backlinks` | 反链（P1） |

### 5.2 结构

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/courses` | 课程树（课程 → 章节 → 笔记摘要） |
| `GET/PUT` | `/api/courses/{name}` | 课程元信息（目标 / 大纲 / 资料清单） |
| `GET` | `/api/tags` | 标签及计数 |
| `GET` | `/api/search?q=` | 全文检索，返回命中片段与高亮区间 |
| `GET` | `/api/inbox` | 待整理速记 |
| `POST` | `/api/inbox/{id}/promote` | 速记 → 正式笔记（转正） |

### 5.3 系统

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 健康检查 |
| `POST` | `/api/reindex` | 全量重建索引（从 md 重建 `study.db`） |
| `GET` | `/api/export?format=md\|html` | 整库导出 |

**并发与一致性**：
- 写文件：临时文件 + `ATOMIC_MOVE`（与 `book` 项目的 `DataStore` 一致）
- 每篇笔记一把细粒度锁；`PUT` 校验 `baseHash`，不一致返回 `409` 让前端提示"文件被外部修改"
- **外部修改检测**：文件监听（JDK `WatchService`）→ 变更则重新解析该文件并更新索引，推送给前端热更新

---

## 6. AI 整理流水线契约（P1 实现，P0 先定接口）

这是草图里 `ai笔记整理` 节点的落地方式。**核心原则：AI 不直接改用户的笔记，只产出"建议"。**

```
输入:  { raw: "粗笔记正文", course, attachments? }
输出:  {
  suggestions: [
    { kind: "structure",  diff: "...", reason: "合并了 3 条重复的散点" },
    { kind: "title",      from: "无标题", to: "红黑树的插入与旋转" },
    { kind: "tags",       add: ["红黑树","平衡树"], remove: [] },
    { kind: "summary",    text: "..." },
    { kind: "glossary",   items: [{term:"黑高", def:"..."}] },
    { kind: "todos",      items: [{text:"手推一次左旋过程", due:null}] },
    { kind: "links",      items: [{target:"[[二叉搜索树]]", context:"..."}] }
  ],
  model: "...", tokens: 1234
}
```

UI 表现：右侧「AI 建议」面板，**逐条** 接受 / 忽略 / 编辑后再接受；接受后进入编辑器的撤销栈。
**被拒绝的建议不写回笔记，只记录采纳率用于后续调优。**

> 反模式警告：整篇"一键 AI 重写"会摧毁用户对自己笔记的熟悉感——而熟悉感正是复习效率的来源。这是很多 AI 笔记产品失败的原因。

---

## 7. 飞书单向发布（P1，调用序列已核验）

```
本地 md ──①转换──> blocks  ──②插入──> 飞书文档 ──③挂载──> 知识库节点
```

1. `POST /open-apis/docx/v1/documents/blocks/convert`
   `{content_type:"markdown", content:"..."}`
   → 拿到 `blocks` + `first_level_block_ids`
2. 若 `blocks.length > 1000`：**分批**调用
   `POST /open-apis/docx/v1/documents/{document_id}/blocks/{block_id}/descendant`
3. 表格块：**先删除 `merge_info`**（只读字段，传入会报错）
4. 图片块：`POST /open-apis/drive/v1/media/upload_all`（以 Image BlockID 作 `parent_node`）→ 再 `PATCH` 块，`replace_image` 操作
5. 首次发布用 `POST /open-apis/wiki/v2/spaces/{space_id}/nodes`（`obj_type: docx`, `node_type: origin`, `parent_node_token` = 章节目录节点）创建并挂载；把返回的 `node_token` 写回 frontmatter
6. 再次发布同 `id`：命中 `feishu_node_token` → **更新**既有文档（避免重复创建）

**失败处理**：
- 限频 `99991400` / `1069923` → 指数退避（1s → 2s → 4s → 8s，最多 5 次）
- 建一个 `publish_queue`（落盘），失败任务可重试、可查状态
- 反向拉取（blocks → md）**仅用于**提示"飞书端被他人改过"，不自动写回本地

---

## 8. 前端页面结构

```
┌────────────────┬────────────────────────────┬──────────────┐
│ 侧边栏          │ 编辑器                      │ 右侧面板      │
│                │                            │              │
│ ▸ 课程树        │  [源码|分屏|WYSIWYG]  [AI] │  大纲        │
│ ▸ 标签          │                            │  反链 (P1)   │
│ ▸ 收件箱 (3)    │  # 复杂度分析               │  AI 建议(P1) │
│ ▸ 全部笔记      │  ...                       │  版本历史     │
│                │                            │              │
│ [+ 新建] [🔍]   │  800ms 自动保存 · 已保存 ✓  │              │
└────────────────┴────────────────────────────┴──────────────┘
```

- 左侧可折叠；右侧仅在需要时出现（默认收起，保证写作区足够宽）
- 顶部状态栏显示：保存状态 / 字数 / 最后修改时间 / **外部修改提示**
- 无 CDN 依赖（与 `book` 项目一致）：markdown-it / highlight.js / KaTeX / Mermaid 全部本地打包

---

## 9. P0 验收清单

- [ ] 从按下 `Ctrl+Shift+N` 到写完一句速记并关闭浮层，**≤3 秒**，且不离开当前页面
- [ ] 一学期 200 篇笔记、30 万字级别下，全文检索响应 **<200ms**
- [ ] 用 VS Code 直接改一篇笔记 → App 3 秒内自动刷新并提示
- [ ] 删掉 `study.db` → 重启 → 索引、标签、双链、课程树全部自动重建，内容无丢失
- [ ] Markdown 往返：`md → WYSIWYG → md`，行内代码/公式/表格/待办不丢格式
- [ ] 公式（KaTeX）、代码高亮、Mermaid、表格、Callout 全部正常渲染
- [ ] 移动笔记到别的章节后，`[[双链]]` 仍能正确解析
- [ ] 连续记录 7 天真实课程笔记，主观意愿上不想退回飞书文档 ← **唯一的终极验收项**

---

## 10. 明确不做（P0 边界）

| 不做 | 原因 |
| --- | --- |
| AI 整理 / RAG 答疑 | 笔记模式没打磨好之前，AI 只是噪音 |
| 飞书同步 | 需要独立的 Provider 层设计与重试队列 |
| PDF / 视频 / 网页解析 | 质量不可控，会拖垮项目节奏 |
| 多人协作、CRDT | 单人场景无收益，成本极高 |
| 移动端 / 小程序 | Web 先跑通 |
| 端到端加密 | 默认纯本地已足够，上云时再议 |
