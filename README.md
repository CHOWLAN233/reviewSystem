# 📚 Review Agent / 复习助手

AI-powered lecture note generator that transforms PPT/PDF course materials into
structured, review-ready Markdown notes.

AI 驱动的课程笔记生成器，将 PPT/PDF 课件材料转换为结构化的、可用于复习的 Markdown 笔记。

---

## What It Does / 功能介绍

1. **Drop** your lecture PPT/PDF files into `01_Input_PPTs/`
2. **Run** the agent – it auto-classifies each file by course & week number
3. **Read** beautifully structured Markdown notes in `02_Output_Notes/`

---

1. **放入** 课程 PPT/PDF 文件到 `01_Input_PPTs/` 文件夹
2. **运行** Agent – 自动按课程和周次分类每个文件
3. **阅读** `02_Output_Notes/` 中结构精美的 Markdown 笔记

Each generated note includes / 每份生成的笔记包含：
- 🗺 **核心知识大纲 / Core Knowledge Outline** – structured mental map of the lecture / 课程的结构化思维导图
- 📖 **关键概念与术语表 / Key Concepts & Glossary** – terms with definitions and memory aids / 术语及其定义和记忆锚点
- ⚡ **重点总结 / Critical Takeaways** – exam-relevant highlights / 考试相关重点
- 📝 **详细笔记（AI 扩展）/ Detailed Notes (AI-Expanded)** – concepts explained in plain language / 用通俗语言解释的概念
- 🧪 **实验解答 / Lab Solutions** *(if applicable / 如适用)* – answers, explanations, pitfalls, and environment checklist / 答案、解释、避坑指南和环境清单

---

## Quick Start / 快速开始

### 1. Setup / 环境配置

```bash
# Clone and enter the project / 克隆并进入项目
cd reviewSystem

# Create virtual environment / 创建虚拟环境
python -m venv venv
source venv/bin/activate      # macOS / Linux
venv\Scripts\activate         # Windows

# Install dependencies / 安装依赖
pip install -r requirements.txt
```

### 2. Configure API Keys / 配置 API 密钥

```bash
cp .env.example .env
```

Edit `.env` and set at minimum / 编辑 `.env`，至少设置：
```bash
API_KEY=sk-your-api-key-here
```

### 3. Add Your Course Files / 添加课程文件

Drop your PPT/PDF files into the `01_Input_PPTs/` folder / 将 PPT/PDF 文件放入 `01_Input_PPTs/` 文件夹：
```
01_Input_PPTs/
├── CS101_Week1_Intro.pptx
├── 操作系统_第3周_进程管理.pdf
└── ML_week5_neural_nets.pptx
```

### 4. Run / 运行

**命令行 / Command-line：**
```bash
python main.py
```

**网页界面 / Web interface：**
```bash
streamlit run app.py
```

---

### CLI Options / 命令行选项

| Flag / 选项 | Description / 描述 |
|------|-------------|
| `--dry-run` | Scan & classify only – no token spending / 仅扫描和分类，不消耗 token |
| `--force file1.pptx file2.pdf` | Force reprocess specific files / 强制重新处理指定文件 |
| `--preset budget` | Use budget-friendly models / 使用经济型模型 |
| `--preset maximum` | Use most powerful models / 使用最强模型 |
| `--input ./my_ppts` | Custom input directory / 自定义输入目录 |
| `--output ./my_notes` | Custom output directory / 自定义输出目录 |
| `--log-level DEBUG` | Verbose logging / 详细日志 |

---

## Output Structure / 输出结构

```
02_Output_Notes/
└── CS101_计算机科学导论/
    └── Week_01_Introduction/
        ├── summary.md           # 课程复习笔记 / Lecture review notes
        └── lab_solution.md      # 实验解答 (仅当检测到实验时) / (only if lab detected)
```

---

## How It Works / 工作原理

```
PPT/PDF → 提取文本 Extract text → AI 分类 AI Classification → AI 总结 AI Summarization
                                                              ↘ (如有实验 if lab) AI 实验解答 AI Lab Solver
                                                              → Markdown 写入 Markdown Writer → 输出 Output
```

- **增量同步 / Incremental**：使用 MD5 哈希通过 `.sync_state.json` 追踪状态 – 仅处理新增或修改的文件
- **多模型 / Multi-model**：LiteLLM 支持一行切换模型（Gemini、Claude、DeepSeek、Ollama 等）
- **两步 AI / Two-step AI**：廉价模型用于分类，强大模型用于内容生成
- **容错性 / Resilient**：单文件隔离 – 一个文件出错不会中断整批处理；自动状态备份

---

## Model Presets / 模型预设

| Preset | Classifier / 分类器 | Summarizer / 总结器 | Lab Solver / 实验解答 |
|--------|-----------|------------|------------|
| `budget` / 经济型 | Gemini Flash | DeepSeek Chat | DeepSeek Chat |
| `balanced` / 均衡型 | Gemini Flash | Claude Sonnet | Claude Sonnet |
| `maximum` / 最强型 | Claude Sonnet | Claude Opus | Claude Opus |

Set via `.env` (`PRESET=balanced`) or CLI (`--preset balanced`). / 通过 `.env` (`PRESET=balanced`) 或 CLI (`--preset balanced`) 设置。

You can override individual models in `.env` / 可在 `.env` 中单独覆盖模型：
```bash
CLASSIFIER_MODEL=gemini/gemini-2.0-flash
SUMMARIZER_MODEL=claude-sonnet-4-20250514
LAB_SOLVER_MODEL=deepseek/deepseek-chat
```

---

## Supported File Formats / 支持的文件格式

- `.pptx` – PowerPoint presentations / PowerPoint 演示文稿（文本 + 演讲者备注）
- `.ppt` – Legacy PowerPoint / 旧版 PowerPoint（支持有限）
- `.pdf` – PDF documents / PDF 文档

> ⚠ **图片较多的幻灯片 / Image-heavy slides**：当前版本仅提取文本。对于图表较多的课程，请使用支持 Vision 的 LLM 模型，或先将幻灯片转换为富文本格式。

---

## Project Structure / 项目结构

```
reviewSystem/
├── main.py                  # CLI 入口 / CLI entry point
├── app.py                   # Streamlit 入口 / Streamlit entry point
├── convert_to_pdf.py        # PDF 导出工具 / PDF export tool
├── requirements.txt         # Python 依赖 / Python dependencies
├── .env.example             # 环境变量模板 / Environment template
├── 01_Input_PPTs/           # ← 在此放入文件 / Drop your files here
├── 02_Output_Notes/         # ← 生成的笔记出现于此 / Generated notes appear here
├── prompts/                 # LLM 提示词模板 / LLM prompt templates
└── src/
    ├── config/              # 配置与环境变量管理 / Settings & env management
    ├── scanner/             # 文件发现与状态追踪 / File discovery & state tracking
    ├── parser/              # PPTX 与 PDF 文本提取 / PPTX & PDF text extraction
    ├── llm/                 # LiteLLM 客户端封装 / LiteLLM client wrapper
    ├── classifier/          # AI 课程/周次分类器 / AI course/week classifier
    ├── generator/           # 总结器、实验解答器、Markdown 写入器 / Summarizer, Lab Solver, Markdown Writer
    ├── pipeline.py          # 核心编排器 / Core orchestrator
    └── ui/                  # Streamlit 网页界面 / Streamlit web interface
```

---

## License / 许可证

MIT
