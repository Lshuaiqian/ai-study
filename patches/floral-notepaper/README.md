# 花笺（floral-notepaper）改造补丁

这个目录放的是**对上游花笺的改造**，以补丁形式提供，而不是把整个仓库副本塞进来。

## 为什么是补丁，不是源码副本

上游仓库完整副本有 **6.25 GB**（`src-tauri/target/` 构建目录 6 GB + `node_modules` 142 MB），
而且它是**别人的项目**（MIT，版权归 Achilng）。把它整份放进本项目会造成三个问题：
仓库体积失控、许可证归属混乱、以及上游一更新就产生大面积无意义 diff。

补丁只有 **66 KB**，可读、可审、可选择性应用。

## 上游信息

| 项 | 值 |
|---|---|
| 仓库 | https://github.com/Achilng/floral-notepaper |
| 基线 commit | `69a43aef87d2d8fa90c7a7d929cd113941f1fde3`（`chore(deps): bump @vitest/mocker (#389)`） |
| 版本 | 1.2.0 |
| 许可证 | MIT（Copyright (c) 2026 Achilng）——补丁作为衍生作品，同样受 MIT 约束，**必须保留上游版权声明** |

## 补丁内容

`多级分类与便签墙.patch`，12 个文件、407 行插入 / 42 行删除，分两块：

**一、多级分类（花笺原本只有单层分类）**

| 文件 | 改动 |
|---|---|
| `src-tauri/src/services/notes.rs` | 分类支持 `父/子` 形式；重命名分类时同步改写子孙前缀；移动笔记时按新路径落盘 |
| `src-tauri/src/lib.rs` | 注册新命令 |
| `src-tauri/src/services/mod.rs` | 导出新模块 |
| `src-tauri/src/desktop.rs` | 菜单/托盘相关接线 |
| `src/locales/{zh-CN,zh-HK,en-US}/translation.json` | 新增文案 |

**二、便签墙（新增视图）**

| 文件 | 改动 |
|---|---|
| `src/components/NoteWall.tsx` | 便签墙组件 |
| `src/features/notes/noteWall.ts` | 纯函数逻辑（布局/排序/分组），与组件分离以便单测 |
| `src/features/notes/noteWall.test.ts` | 26 个用例 |
| `src/components/MainWindow.tsx` | 4 处集成点 |

**三、`src-tauri/src/services/study.rs`（18.6 KB）**

这是「一键整理按钮」的 Rust 侧：以子进程方式调用学习系统的 CLI，
逐行读 stdout 并通过 `app.emit` 推给前端，带超时、取消与笔记路径越界校验。
**注意**：前端按钮与报告面板还没做完，所以这块目前是**可用但未接线**的状态。
完整方案见本仓库 `docs/一键整理按钮-花笺集成方案（plan）.md`。

设计说明另见同目录的 `多级分类-设计说明.md`。

## 怎么应用

```bash
git clone https://github.com/Achilng/floral-notepaper.git
cd floral-notepaper
git checkout 69a43aef87d2d8fa90c7a7d929cd113941f1fde3

# 应用补丁
git apply /path/to/多级分类与便签墙.patch

# 装依赖（补丁里不含 pnpm-lock.yaml，那是生成物）
pnpm install

# 验证
pnpm vitest run                      # 前端测试
cd src-tauri && cargo test           # Rust 测试
```

补丁是用 `git diff --binary` 生成的，**纯 LF、无 BOM**，
已用 `git apply --check -R` 反向验证过完整性（能反向应用 = 内容与源工作区一致）。

## 与上游合并时注意

- 改动集中在 3 个手写文件（`notes.rs`、`lib.rs`、`MainWindow.tsx`）+ 1 个新模块，冲突面小。
- 三个 locale 文件的改动是纯新增键，冲突概率低。
- **建议向上游提 PR 而不是长期维护 fork**：这几个能力（多级分类、便签墙）对其他用户也有价值，
  走 PR 能被 review 也能被维护；长期 fork 会越拖越难合。
