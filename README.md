# Review Agent v2.0

AI 驱动的课程笔记生成器，将 PPT/PDF 课件材料转换为结构化的 Markdown 笔记和 PDF 文件。

---

## 功能介绍

1. 将课程 PPT/PDF 文件放入输入文件夹
2. 运行 Agent，自动按课程和周次分类每个文件
3. 获得结构化的 Markdown 笔记，并可导出为 PDF

每份生成的笔记包含：
- 核心知识大纲 -- 课程的结构化思维导图
- 关键概念与术语表 -- 术语及其定义和记忆锚点
- 重点总结 -- 考试相关重点
- 详细笔记 (AI 扩展) -- 用通俗语言解释的概念
- 实验解答 (如适用) -- 答案、解释、避坑指南和环境清单

---

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/CHOWLAN233/reviewSystem.git
cd reviewSystem
```

### 2. 环境配置

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置 API 密钥

```bash
# 从模板创建 .env 文件
cp .env.example .env
```

编辑 `.env` 文件，至少设置 API 密钥：

```bash
API_KEY=sk-your-api-key-here
```

也可以进入程序后在 `[4] Settings` 菜单中配置。

### 4. 添加课程文件

将 PPT/PDF 文件放入 `01_Input_PPTs/` 文件夹。支持按子文件夹组织（例如按课程名称）：

```
01_Input_PPTs/
├── CS101/
│   ├── Week1_Intro.pptx
│   └── Week2_Variables.pdf
└── MATH201/
    ├── Chapter1_Limits.pptx
    └── Chapter2_Derivatives.pdf
```

### 5. 运行

```bash
python main.py
```

---

## CLI 菜单说明

运行 `python main.py` 后进入交互式菜单：

```
============================================================
         Review Agent v2.0
    AI-Powered Lecture Note Generator
============================================================

  [1] Upload & Process Files
  [2] View Exported PDFs / Output
  [3] Processing History
  [4] Settings
  [5] Regenerate Files
  [6] Exit
```

### [1] Upload & Process Files -- 上传并处理文件

- 自动打开输入文件夹，方便用户拖入文件
- 按 Enter 后扫描文件夹，列出所有支持的 PPT/PDF 文件
- 标记每个文件的状态: `[NEW/MODIFIED]` 或 `[up-to-date]`
- 支持文件选择:
  - 直接按 Enter: 处理所有新增/修改的文件 (默认)
  - 输入序号如 `1,3,5`: 只处理指定的文件
  - 输入 `all`: 强制处理所有文件 (包括已处理过的)
- 确认后开始处理，实时显示进度条
- 处理完成后提示是否导出 PDF
  - 导出前自动检测系统中文字体是否可用
- 自动打开输出文件夹展示结果
- 按 Ctrl+C 中断时自动保存已完成文件的状态

### [2] View Exported PDFs / Output -- 查看导出文件

- 显示输出目录的完整目录树结构
- 列出所有已生成的 PDF 和 Markdown 文件及其大小
- 按 `o` 键直接在文件管理器中打开输出文件夹
- 按 Enter 返回主菜单

### [3] Processing History -- 处理历史

- 显示所有已处理文件的记录（来源：`.sync_state.json`）
- 包含: 文件名、处理状态、处理时间、输出路径
- 按状态统计: processed / errors / skipped
- 支持查看原始 JSON 数据
- 支持清除/重置处理历史

### [4] Settings -- 设置

可以在菜单中修改以下配置（修改后自动写入 `.env` 文件）：

| 设置项 | 说明 | 校验 |
|--------|------|------|
| API Key | LLM API 密钥 | 长度 >= 8 才保存 |
| Model Preset | 模型预设 (budget / balanced / maximum) | 必须为有效预设名 |
| Classifier Model | 分类模型 | 格式: provider/model-name |
| Summarizer Model | 总结模型 | 格式: provider/model-name |
| Lab Solver Model | 实验解答模型 | 格式: provider/model-name |
| Input Directory | 输入文件夹路径 | 检查父目录可访问性 |
| Output Directory | 输出文件夹路径 | 检查父目录可访问性 |
| Log Level | 日志级别 | DEBUG/INFO/WARNING/ERROR |
| Review Mode | 二次审查模式 | off/basic/deep |
| View/Edit .env | 直接查看 .env 内容 | API key 自动掩码显示 |

- `[9] Review Mode`: 二次审查模式 (off/basic/deep)
- 启动时自动检测 `.env` 中是否有缺失的配置项（对比 `.env.example`），并提示用户

### [5] Regenerate Files -- 重新生成

- 先弹出确认提示，告知将覆盖现有输出
- 弹出输入文件夹供用户确认文件就位
- 扫描并列出所有文件，显示每个文件的处理状态和时间
- 选择要重新生成的文件（序号逗号分隔，或 `all` 全部）
- 二次确认后清除选中文件的状态记录
- 重新运行 pipeline，覆盖原输出文件夹
- 可选导出 PDF，完成后弹出输出文件夹

### [6] Exit -- 退出

退出程序。

---

## 批量模式

除了交互式菜单，也支持命令行参数进行批量处理：

```bash
# 基本用法
python main.py --preset budget              # 使用经济型模型
python main.py --dry-run                    # 仅预览分类，不消耗 token
python main.py --force file1.pptx           # 强制重新处理指定文件
python main.py --input ./my_ppts            # 自定义输入目录
python main.py --output ./my_notes          # 自定义输出目录
python main.py --pdf                        # 处理完成自动导出 PDF
python main.py --log-level DEBUG            # 详细日志

# 新增功能
python main.py --version                    # 查看版本号
python main.py --log-file agent.log         # 同时将日志写入文件
python main.py --pdf --log-file run.log     # 组合使用
```

---

## 输出结构

```
02_Output_Notes/
└── {Course_Name}/                    # 课程文件夹
    ├── md/                           # Markdown 笔记 (课程级别)
    │   ├── Week_01_Topic_summary.md
    │   ├── Week_01_Topic_lab_solution.md
    │   ├── Week_02_Topic_summary.md
    │   └── ...
    ├── Week_01_Topic/                # 单周文件夹
    │   ├── summary.pdf               # 生成的 PDF
    │   ├── lab_solution.pdf          # 实验解答 PDF
    │   └── original_file.ppt         # 原始文件副本
    └── Week_02_Topic/
        └── ...
```

Markdown 文件统一放在课程级别的 `md/` 子文件夹中，便于集中管理和搜索。

---

## 模型预设

| Preset | Classifier | Summarizer | Lab Solver |
|--------|-----------|------------|------------|
| budget | Gemini Flash | DeepSeek Chat | DeepSeek Chat |
| balanced | Gemini Flash | Claude Sonnet | Claude Sonnet |
| maximum | Claude Sonnet | Claude Opus | Claude Opus |

通过 `.env` 文件 (`PRESET=balanced`) 或 CLI 菜单 [4] Settings 设置。

也可以单独覆盖模型：
```bash
CLASSIFIER_MODEL=gemini/gemini-2.0-flash
SUMMARIZER_MODEL=claude-sonnet-4-20250514
LAB_SOLVER_MODEL=deepseek/deepseek-chat
```

---

## 跨平台支持

| 平台 | 状态 | 中文字体 (PDF) |
|------|------|---------------|
| Windows 11 | 完全支持 | Microsoft YaHei (系统自带) |
| macOS | 完全支持 | PingFang SC (系统自带) |
| Linux | 完全支持 | 需安装 `fonts-noto-cjk` |

### Linux 中文字体安装

```bash
# Debian / Ubuntu
sudo apt install fonts-noto-cjk

# Fedora
sudo dnf install google-noto-cjk-fonts

# Arch
sudo pacman -S noto-fonts-cjk
```

程序在导出 PDF 前会自动检测系统中文字体，如缺失会给出安装提示。

---

## 工作原理

```
PPT/PDF -> 提取文本 -> AI 分类 -> AI 总结
                                  -> (如有实验) AI 实验解答
                                  -> Markdown 写入 -> 输出
```

- **增量同步**: 使用 MD5 哈希追踪处理状态，仅处理新增或修改的文件
- **多模型**: LiteLLM 支持一行切换模型 (Gemini、Claude、DeepSeek、Ollama 等)
- **两步 AI**: 廉价模型用于分类，强大模型用于内容生成
- **容错性**: 单文件隔离，一个文件出错不会中断整批处理；Ctrl+C 中断时自动保存已完成的文件状态
- **文件选择**: 支持按序号选择要处理的文件，灵活控制处理范围
- **配置校验**: 模型名称和路径在保存前会进行格式校验，减少配置错误
- **版本提醒**: 自动对比 `.env.example` 检测新增的配置项

---

## 支持的文件格式

- `.pptx` -- PowerPoint 演示文稿 (文本 + 演讲者备注)
- `.ppt` -- 旧版 PowerPoint (支持有限，使用二进制提取)
- `.pdf` -- PDF 文档

> 注意: 当前版本仅提取文本。对于图片较多的幻灯片，请使用支持 Vision 的 LLM 模型。

---

## 项目结构

```
reviewSystem/
├── main.py                  # CLI 入口 (交互式菜单 + 批量模式)
├── convert_md_to_pdf.py     # MD -> PDF 导出工具
├── requirements.txt         # Python 依赖
├── .env.example             # 环境变量模板
├── 01_Input_PPTs/           # <-- 在此放入 PPT/PDF 文件
├── 02_Output_Notes/         # <-- 生成的笔记和 PDF 出现于此
├── prompts/                 # LLM 提示词模板
└── src/
    ├── config/              # 配置与环境变量管理
    ├── scanner/             # 文件发现与状态追踪
    ├── parser/              # PPTX 与 PDF 文本提取
    ├── llm/                 # LiteLLM 客户端封装
    ├── classifier/          # AI 课程/周次分类器
    ├── generator/           # 总结器、实验解答器、Markdown 写入器
    └── pipeline.py          # 核心编排器
```

---

## v2.0 更新内容

相对于 v1.x 的改进：

1. 移除前端页面，改为纯命令行交互
2. Markdown 文件统一放在课程级别的 `md/` 子文件夹
3. 新增交互式 CLI 菜单 (5 个选项)
4. 选项 [1] 自动打开输入/输出文件夹
5. 选项 [1] 支持按序号选择要处理的文件
6. 选项 [1] Ctrl+C 中断时自动保存部分结果
7. 选项 [2] 按 `o` 键打开输出文件夹
8. 选项 [4] 模型名、路径等输入项增加格式校验
9. 选项 [4] 启动时自动对比 `.env.example` 检测缺失配置
10. 批量模式新增 `--version` 和 `--log-file` 参数
11. PDF 导出前自动检测系统中文字体并给出提示
12. 完善跨平台支持 (Windows / macOS / Linux)

---

## License

MIT
