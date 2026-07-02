"""
Internationalization (i18n) for the Review Agent Streamlit UI.

Supports: English (en), Simplified Chinese (zh-CN).

Usage::

    from src.ui.i18n import t, set_lang, LANG

    set_lang("zh-CN")
    print(t("welcome_title"))
"""

from __future__ import annotations

import streamlit as st

# ---------------------------------------------------------------------------
# Default language
# ---------------------------------------------------------------------------
LANG = "en"


def set_lang(lang: str) -> None:
    """Switch the global language."""
    global LANG
    LANG = lang
    st.session_state["lang"] = lang


def init_lang() -> str:
    """Read language from session state, or default to 'en'."""
    lang = st.session_state.get("lang", "en")
    global LANG
    LANG = lang
    return lang


def t(key: str, **kwargs) -> str:
    """
    Return the translation for *key* in the current language.

    Falls back to English if the key is missing in the target language.
    Supports Python format-string interpolation: ``t("files_found", count=9)``.
    """
    global LANG
    lang = st.session_state.get("lang", LANG)
    table = STRINGS.get(lang, STRINGS["en"])
    text = table.get(key)
    if text is None:
        text = STRINGS["en"].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


# ===================================================================
# Translation strings
# ===================================================================

STRINGS = {
    "en": {
        # ---- Landing page ----
        "landing_title": "Welcome to Review Agent",
        "landing_subtitle": "AI-powered lecture note generator",
        "landing_select_lang": "Choose your language / 选择语言",
        "landing_continue": "Get Started",
        "landing_tutorial_title": "Quick Start Guide",
        "landing_tutorial_step1_title": "1. Drop your files",
        "landing_tutorial_step1_desc": "Place your lecture PPT or PDF files into the `01_Input_PPTs` folder. The agent supports `.pptx`, `.ppt`, and `.pdf` formats.",
        "landing_tutorial_step2_title": "2. Configure API",
        "landing_tutorial_step2_desc": "In the sidebar, enter your LLM API key and choose a model preset (`budget` / `balanced` / `maximum`). Click **Apply Configuration**.",
        "landing_tutorial_step3_title": "3. Process",
        "landing_tutorial_step3_desc": "Go to the **Processing** tab and click **Run Pipeline**. The agent will auto-classify each file by course and week, then generate structured Markdown notes.",
        "landing_tutorial_step4_title": "4. Review & Export",
        "landing_tutorial_step4_desc": "Browse generated notes in the **Output Browser** tab. Each note includes a knowledge outline, glossary, key takeaways, and detailed AI-expanded explanations. Run `python convert_to_pdf.py` to export all notes as PDF.",
        "landing_feature1_title": "Auto Classification",
        "landing_feature1_desc": "AI identifies course name, week number, and topic from your slides automatically.",
        "landing_feature2_title": "Structured Notes",
        "landing_feature2_desc": "Generates knowledge outlines, glossaries, takeaways, and expanded explanations.",
        "landing_feature3_title": "Lab Solver",
        "landing_feature3_desc": "Detects lab/practical sessions and produces solutions with pitfalls and environment checklists.",
        "landing_feature4_title": "Incremental Sync",
        "landing_feature4_desc": "Only processes new or modified files — saves API tokens and time.",
        "landing_features_heading": "Core Features",

        # ---- Sidebar ----
        "sidebar_header": "Configuration",
        "sidebar_api_key": "API Key",
        "sidebar_api_key_help": "Your LLM API key. Used for all models unless overridden.",
        "sidebar_preset": "Model Preset",
        "sidebar_preset_help": "Predefined model combinations for different cost/quality trade-offs.",
        "sidebar_advanced": "Advanced",
        "sidebar_classifier_model": "Classifier Model",
        "sidebar_classifier_model_help": "Cheap/fast model for metadata extraction.",
        "sidebar_summarizer_model": "Summarizer Model",
        "sidebar_summarizer_model_help": "Powerful model for deep content generation.",
        "sidebar_lab_model": "Lab Solver Model",
        "sidebar_lab_model_help": "Code-capable model for lab solutions.",
        "sidebar_input_dir": "Input Directory",
        "sidebar_output_dir": "Output Directory",
        "sidebar_state_file": "State File",
        "sidebar_apply": "Apply Configuration",
        "sidebar_applied": "Configuration applied!",
        "sidebar_api_required": "API Key is required!",
        "sidebar_config_error": "Configuration error",

        # ---- Tabs ----
        "tab_dashboard": "Dashboard",
        "tab_processing": "Processing",
        "tab_output": "Output Browser",

        # ---- Dashboard ----
        "dashboard_header": "Dashboard",
        "dashboard_files_input": "Files in Input",
        "dashboard_tracked_state": "Tracked in State",
        "dashboard_processed": "Processed",
        "dashboard_file_list": "Input Files",
        "dashboard_no_files": "No supported files found. Drop some PPT or PDF files into the input directory.",
        "dashboard_recent_log": "Recent Log",
        "dashboard_get_started": "Configure your API key and settings in the sidebar to get started.",
        "dashboard_status_new": "New",
        "dashboard_status_modified": "Modified",
        "dashboard_status_uptodate": "Up-to-date",
        "dashboard_status_error": "Error",
        "dashboard_col_status": "Status",
        "dashboard_col_filename": "Filename",
        "dashboard_col_state": "State",
        "dashboard_col_last_processed": "Last Processed",

        # ---- Processing ----
        "processing_header": "Processing",
        "processing_get_started": "Configure your settings first.",
        "processing_run_btn": "Run Pipeline",
        "processing_dry_run_btn": "Dry Run Only",
        "processing_force_label": "Force reprocess (comma-separated filenames)",
        "processing_force_placeholder": "file1.pptx, file2.pdf",
        "processing_dry_complete": "Dry run complete! {count} file(s) would be processed.",
        "processing_dry_col_filename": "Filename",
        "processing_dry_col_course": "Course",
        "processing_dry_col_week": "Week",
        "processing_dry_col_topic": "Topic",
        "processing_complete": "Complete!",
        "processing_report_title": "Processing Report",
        "processing_col_filename": "Filename",
        "processing_col_status": "Status",
        "processing_col_course": "Course",
        "processing_col_week": "Week",
        "processing_col_output": "Output",
        "processing_last_details": "Last Run Details",
        "processing_pipeline_error": "Pipeline error",
        "processing_status_ok": "Processed",
        "processing_status_err": "Error",
        "processing_scanning": "Scanning input directory...",
        "processing_loading_state": "Loading state & detecting changes...",
        "processing_done_uptodate": "Done – everything is up-to-date.",
        "processing_done_no_files": "Done – no files to process.",
        "processing_saving_state": "Saving state...",
        "processing_done_fmt": "Done – {ok} processed, {err} errors, {skip} skipped in {time:.1f}s.",
        "processing_scanned": "Scanned",
        "processing_new_changed": "New/Changed",
        "processing_ok": "Processed",
        "processing_err": "Errors",
        "processing_time": "Time",

        # ---- Output Browser ----
        "output_header": "Output Browser",
        "output_get_started": "Configure your settings first.",
        "output_no_dir": "No output directory yet. Run the pipeline to generate notes.",
        "output_no_files": "No generated notes found. Process some files first!",
        "output_view_btn": "View",
        "output_close_btn": "Close",
        "output_cannot_read": "Cannot read file",

        "output_files_count": "{count} files",

        # ---- Language ----
        "lang_en": "English",
        "lang_zh": "中文",
        "lang_switch": "Language / 语言",
    },

    "zh-CN": {
        # ---- Landing page ----
        "landing_title": "欢迎使用 Review Agent",
        "landing_subtitle": "AI 驱动的课程笔记生成器",
        "landing_select_lang": "Choose your language / 选择语言",
        "landing_continue": "开始使用",
        "landing_tutorial_title": "快速上手指南",
        "landing_tutorial_step1_title": "1. 放入文件",
        "landing_tutorial_step1_desc": "将课程 PPT 或 PDF 文件放入 `01_Input_PPTs` 文件夹。支持 `.pptx`、`.ppt` 和 `.pdf` 格式。",
        "landing_tutorial_step2_title": "2. 配置 API",
        "landing_tutorial_step2_desc": "在侧边栏输入您的 LLM API 密钥，选择模型预设（`budget` 经济 / `balanced` 均衡 / `maximum` 最强）。点击 **应用配置**。",
        "landing_tutorial_step3_title": "3. 开始处理",
        "landing_tutorial_step3_desc": "进入 **处理中心** 标签页，点击 **运行处理**。Agent 将自动按课程和周次分类每个文件，然后生成结构化的 Markdown 笔记。",
        "landing_tutorial_step4_title": "4. 查看与导出",
        "landing_tutorial_step4_desc": "在 **笔记浏览** 标签页查看生成的笔记。每份笔记包含知识大纲、术语表、关键要点和 AI 扩展详解。运行 `python convert_to_pdf.py` 可将所有笔记导出为 PDF。",
        "landing_feature1_title": "自动分类",
        "landing_feature1_desc": "AI 自动从幻灯片中识别课程名称、周次和主题。",
        "landing_feature2_title": "结构化笔记",
        "landing_feature2_desc": "生成知识大纲、术语表、关键要点和扩展详解。",
        "landing_feature3_title": "实验解答",
        "landing_feature3_desc": "自动检测实验/上机内容，生成答案、避坑指南和环境清单。",
        "landing_feature4_title": "增量同步",
        "landing_feature4_desc": "仅处理新增或修改的文件——节省 API 费用和时间。",
        "landing_features_heading": "核心功能",

        # ---- Sidebar ----
        "sidebar_header": "系统配置",
        "sidebar_api_key": "API 密钥",
        "sidebar_api_key_help": "您的 LLM API 密钥。除非单独设置，否则所有模型共用此密钥。",
        "sidebar_preset": "模型预设",
        "sidebar_preset_help": "预设的模型组合，适用于不同成本/质量需求。",
        "sidebar_advanced": "高级设置",
        "sidebar_classifier_model": "分类模型",
        "sidebar_classifier_model_help": "用于元数据提取的廉价/快速模型。",
        "sidebar_summarizer_model": "总结模型",
        "sidebar_summarizer_model_help": "用于深度内容生成的强大模型。",
        "sidebar_lab_model": "实验解答模型",
        "sidebar_lab_model_help": "用于生成实验解答的代码型模型。",
        "sidebar_input_dir": "输入目录",
        "sidebar_output_dir": "输出目录",
        "sidebar_state_file": "状态文件",
        "sidebar_apply": "应用配置",
        "sidebar_applied": "配置已应用！",
        "sidebar_api_required": "请输入 API 密钥！",
        "sidebar_config_error": "配置错误",

        # ---- Tabs ----
        "tab_dashboard": "仪表盘",
        "tab_processing": "处理中心",
        "tab_output": "笔记浏览",

        # ---- Dashboard ----
        "dashboard_header": "仪表盘",
        "dashboard_files_input": "待处理文件",
        "dashboard_tracked_state": "已追踪文件",
        "dashboard_processed": "已处理",
        "dashboard_file_list": "输入文件列表",
        "dashboard_no_files": "未找到支持的文件。请将 PPT 或 PDF 文件放入输入目录。",
        "dashboard_recent_log": "最近日志",
        "dashboard_get_started": "请在侧边栏配置 API 密钥和设置以开始使用。",
        "dashboard_status_new": "新文件",
        "dashboard_status_modified": "已修改",
        "dashboard_status_uptodate": "最新",
        "dashboard_status_error": "错误",
        "dashboard_col_status": "状态",
        "dashboard_col_filename": "文件名",
        "dashboard_col_state": "状态",
        "dashboard_col_last_processed": "上次处理时间",

        # ---- Processing ----
        "processing_header": "处理中心",
        "processing_get_started": "请先完成系统配置。",
        "processing_run_btn": "运行处理",
        "processing_dry_run_btn": "仅预览分类",
        "processing_force_label": "强制重新处理（逗号分隔文件名）",
        "processing_force_placeholder": "file1.pptx, file2.pdf",
        "processing_dry_complete": "预览完成！共 {count} 个文件待处理。",
        "processing_dry_col_filename": "文件名",
        "processing_dry_col_course": "课程",
        "processing_dry_col_week": "周次",
        "processing_dry_col_topic": "主题",
        "processing_complete": "处理完成！",
        "processing_report_title": "处理报告",
        "processing_col_filename": "文件名",
        "processing_col_status": "状态",
        "processing_col_course": "课程",
        "processing_col_week": "周次",
        "processing_col_output": "输出路径",
        "processing_last_details": "上次运行详情",
        "processing_pipeline_error": "处理出错",
        "processing_status_ok": "已处理",
        "processing_status_err": "错误",
        "processing_scanning": "正在扫描输入目录...",
        "processing_loading_state": "正在加载状态和检测变更...",
        "processing_done_uptodate": "完成——所有文件均为最新。",
        "processing_done_no_files": "完成——没有需要处理的文件。",
        "processing_saving_state": "正在保存状态...",
        "processing_done_fmt": "完成——成功 {ok} 个，失败 {err} 个，跳过 {skip} 个，耗时 {time:.1f} 秒。",
        "processing_scanned": "已扫描",
        "processing_new_changed": "新增/变更",
        "processing_ok": "成功",
        "processing_err": "失败",
        "processing_time": "耗时",

        # ---- Output Browser ----
        "output_header": "笔记浏览",
        "output_get_started": "请先完成系统配置。",
        "output_no_dir": "尚未生成输出目录。请运行处理流程以生成笔记。",
        "output_no_files": "未找到已生成的笔记。请先处理一些文件！",
        "output_view_btn": "查看",
        "output_close_btn": "关闭",
        "output_cannot_read": "无法读取文件",
        "output_files_count": "{count} 个文件",

        # ---- Language ----
        "lang_en": "English",
        "lang_zh": "中文",
        "lang_switch": "Language / 语言",
    },
}
