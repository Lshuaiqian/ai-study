# 贡献指南

感谢你对 AI 辅助学习系统的兴趣！

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/Lshuaiqian/ai-study.git
cd ai-study

# 2. Python 3.10+（推荐 3.12）
python --version

# 3. 安装依赖（核心仅需标准库；requests 用于联网验证）
pip install -r requirements.txt

# 4. 跑测试（408 单测，不联网）
python -m unittest discover -s study/tests

# 5. 看课程体系
python study/tools/system.py next
```

## 配置 LLM

复制 `study/config.example.json`（如有）或直接设置环境变量：

```bash
export DEEPSEEK_API_KEY="sk-..."
```

不要把 `study/config.json` 提交到仓库（已在 `.gitignore` 中）。

## 提交规范

- 功能性改动请附带测试（`study/tests/test_*.py`，`python -m unittest` 风格）
- 文档改动请同步更新 `README.md` 对应章节
- 保持"学生个体、本地、可信"的定位（详见 README §1.0）：不做教练端、不做多用户、不做排行榜

## 提 PR 前

- [ ] `python -m unittest discover -s study/tests` 全绿
- [ ] 不引入新的硬编码绝对路径（用环境变量或相对仓库根目录）
- [ ] 不提交 `study/config.json`、API key、个人笔记数据
