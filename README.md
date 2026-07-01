# 📚 Review Agent

AI-powered lecture note generator that transforms PPT/PDF course materials into
structured, review-ready Markdown notes.

## What It Does

1. **Drop** your lecture PPT/PDF files into `01_Input_PPTs/`
2. **Run** the agent – it auto-classifies each file by course & week number
3. **Read** beautifully structured Markdown notes in `02_Output_Notes/`

Each generated note includes:
- 🗺 **Core Knowledge Outline** – structured mental map of the lecture
- 📖 **Key Concepts & Glossary** – terms with definitions and memory aids
- ⚡ **Critical Takeaways** – exam-relevant highlights
- 📝 **Detailed AI-Expanded Notes** – concepts explained in plain language
- 🧪 **Lab Solutions** *(if applicable)* – answers, explanations, pitfalls, and environment checklist

## Quick Start

### 1. Setup

```bash
# Clone and enter the project
cd reviewSystem

# Create virtual environment
python -m venv venv
source venv/bin/activate      # macOS / Linux
venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure API Keys

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:
```bash
API_KEY=sk-your-api-key-here
```

### 3. Add Your Course Files

Drop your PPT/PDF files into the `01_Input_PPTs/` folder:
```
01_Input_PPTs/
├── CS101_Week1_Intro.pptx
├── 操作系统_第3周_进程管理.pdf
└── ML_week5_neural_nets.pptx
```

### 4. Run

**Command-line:**
```bash
python main.py
```

**Web interface:**
```bash
streamlit run app.py
```

### CLI Options

| Flag | Description |
|------|-------------|
| `--dry-run` | Scan & classify only – no token spending |
| `--force file1.pptx file2.pdf` | Force reprocess specific files |
| `--preset budget` | Use budget-friendly models |
| `--preset maximum` | Use most powerful models |
| `--input ./my_ppts` | Custom input directory |
| `--output ./my_notes` | Custom output directory |
| `--log-level DEBUG` | Verbose logging |

## Output Structure

```
02_Output_Notes/
└── CS101_计算机科学导论/
    └── Week_01_Introduction/
        ├── summary.md           # Lecture review notes
        └── lab_solution.md      # (only if lab detected)
```

## How It Works

```
PPT/PDF → Extract text → AI Classification → AI Summarization
                                              ↘ (if lab) AI Lab Solver
                                              → Markdown Writer → Output
```

- **Incremental**: Uses MD5 hashing via `.sync_state.json` – only processes new or modified files
- **Multi-model**: LiteLLM enables one-line model switching (Gemini, Claude, DeepSeek, Ollama, …)
- **Two-step AI**: Cheap model for classification, powerful model for content generation
- **Resilient**: Per-file isolation – one broken file won't crash the batch; automatic state backup

## Model Presets

| Preset | Classifier | Summarizer | Lab Solver |
|--------|-----------|------------|------------|
| `budget` | Gemini Flash | DeepSeek Chat | DeepSeek Chat |
| `balanced` | Gemini Flash | Claude Sonnet | Claude Sonnet |
| `maximum` | Claude Sonnet | Claude Opus | Claude Opus |

Set via `.env` (`PRESET=balanced`) or CLI (`--preset balanced`).

You can override individual models in `.env`:
```bash
CLASSIFIER_MODEL=gemini/gemini-2.0-flash
SUMMARIZER_MODEL=claude-sonnet-4-20250514
LAB_SOLVER_MODEL=deepseek/deepseek-chat
```

## Supported File Formats

- `.pptx` – PowerPoint presentations (text + speaker notes)
- `.ppt` – Legacy PowerPoint (limited support)
- `.pdf` – PDF documents

> ⚠ **Image-heavy slides**: The current version extracts text only. For diagram-heavy courses,
> use a Vision LLM-capable model or convert slides to text-rich format first.

## Project Structure

```
reviewSystem/
├── main.py                  # CLI entry point
├── app.py                   # Streamlit entry point
├── requirements.txt
├── .env.example
├── 01_Input_PPTs/           # ← Drop your files here
├── 02_Output_Notes/         # ← Generated notes appear here
├── prompts/                 # LLM prompt templates
└── src/
    ├── config/              # Settings & env management
    ├── scanner/             # File discovery & state tracking
    ├── parser/              # PPTX & PDF text extraction
    ├── llm/                 # LiteLLM client wrapper
    ├── classifier/          # AI course/week classifier
    ├── generator/           # Summarizer, Lab Solver, Markdown Writer
    ├── pipeline.py          # Core orchestrator
    └── ui/                  # Streamlit web interface
```

## License

MIT
