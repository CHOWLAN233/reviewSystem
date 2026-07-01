"""
Streamlit web interface for the Review Agent.

Features:
    1. Landing page with language selection & tutorial (first visit only)
    2. Chinese / English bilingual UI
    3. Three tabs: Dashboard | Processing | Output Browser
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

import streamlit as st

# Ensure the project root is importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config.settings import Settings, MODEL_PRESETS
from src.pipeline import Pipeline, ProcessingReport
from src.scanner.file_scanner import FileScanner
from src.scanner.state_manager import StateManager
from src.ui.i18n import t, set_lang, init_lang, LANG

logger = logging.getLogger(__name__)


# ======================================================================
# Landing Page (first visit)
# ======================================================================

def render_landing_page() -> None:
    """Render the language selection & tutorial landing page."""

    # -- Custom CSS for landing --
    st.markdown("""
    <style>
    .landing-container { max-width: 800px; margin: 0 auto; padding-top: 2rem; }
    .lang-card {
        display: inline-block; padding: 1.5rem 2.5rem; margin: 0.5rem;
        border: 2px solid #d0d8e0; border-radius: 12px; cursor: pointer;
        text-align: center; transition: all 0.2s; min-width: 140px;
    }
    .lang-card:hover { border-color: #2b5797; background: #f0f4f8; }
    .lang-card.selected { border-color: #2b5797; background: #e0e8f0; font-weight: bold; }
    .lang-card h2 { margin: 0; font-size: 2rem; }
    .lang-card p { margin: 4px 0 0; color: #666; font-size: 0.9rem; }
    .feature-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin: 1.5rem 0; }
    .feature-card {
        padding: 1.2rem; border-radius: 8px; background: #f7f9fb;
        border: 1px solid #e0e4e8;
    }
    .feature-card h4 { margin: 0 0 4px; color: #2b5797; }
    .feature-card p { margin: 0; font-size: 0.9rem; color: #555; }
    .step-row { display: flex; align-items: flex-start; gap: 1rem; margin-bottom: 1rem; }
    .step-number {
        background: #2b5797; color: white; border-radius: 50%;
        width: 32px; height: 32px; display: flex; align-items: center;
        justify-content: center; font-weight: bold; flex-shrink: 0; font-size: 14px;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="landing-container">', unsafe_allow_html=True)

    # -- Logo & Title --
    st.markdown(f"# 📚 {t('landing_title')}")
    st.markdown(f"#### {t('landing_subtitle')}")

    # -- Language Selection --
    st.markdown("---")
    st.markdown(f"### 🌐 {t('landing_select_lang')}")
    col_en, col_zh, _ = st.columns([1, 1, 3])

    with col_en:
        en_selected = st.session_state.get("landing_lang", "en") == "en"
        if st.button(
            f"🇺🇸 **English**",
            key="lang_en_btn",
            use_container_width=True,
            type="primary" if en_selected else "secondary",
        ):
            st.session_state["landing_lang"] = "en"
            set_lang("en")
            st.rerun()

    with col_zh:
        zh_selected = st.session_state.get("landing_lang", "en") == "zh-CN"
        if st.button(
            f"🇨🇳 **中文**",
            key="lang_zh_btn",
            use_container_width=True,
            type="primary" if zh_selected else "secondary",
        ):
            st.session_state["landing_lang"] = "zh-CN"
            set_lang("zh-CN")
            st.rerun()

    st.markdown("---")

    # -- Features --
    st.markdown(f"### ✨ {t('landing_feature1_title').split(chr(10))[0] if False else 'Core Features' if LANG == 'en' else '核心功能'}")

    cols = st.columns(2)
    features = [
        ("landing_feature1_title", "landing_feature1_desc", "🤖"),
        ("landing_feature2_title", "landing_feature2_desc", "📝"),
        ("landing_feature3_title", "landing_feature3_desc", "🧪"),
        ("landing_feature4_title", "landing_feature4_desc", "⚡"),
    ]
    for i, (title_key, desc_key, icon) in enumerate(features):
        with cols[i % 2]:
            st.markdown(f"""
            <div class="feature-card">
                <h4>{icon} {t(title_key)}</h4>
                <p>{t(desc_key)}</p>
            </div>
            """, unsafe_allow_html=True)

    # -- Tutorial --
    st.markdown("---")
    st.markdown(f"### 📖 {t('landing_tutorial_title')}")

    steps = [
        ("landing_tutorial_step1_title", "landing_tutorial_step1_desc"),
        ("landing_tutorial_step2_title", "landing_tutorial_step2_desc"),
        ("landing_tutorial_step3_title", "landing_tutorial_step3_desc"),
        ("landing_tutorial_step4_title", "landing_tutorial_step4_desc"),
    ]
    for i, (title_key, desc_key) in enumerate(steps, 1):
        st.markdown(f"""
        <div class="step-row">
            <div class="step-number">{i}</div>
            <div>
                <strong>{t(title_key)}</strong><br>
                <span style="color:#555;">{t(desc_key)}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # -- Enter button --
    st.markdown("---")
    if st.button(f"🚀 {t('landing_continue')}", type="primary", use_container_width=True):
        st.session_state["has_visited"] = True
        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


# ======================================================================
# Sidebar
# ======================================================================

def render_sidebar() -> Optional[Settings]:
    """Render the configuration sidebar with i18n."""
    st.sidebar.header(f"⚙ {t('sidebar_header')}")

    # Language switcher
    lang_options = ["en", "zh-CN"]
    lang_labels = [t("lang_en"), t("lang_zh")]
    current_lang = st.session_state.get("lang", "en")
    current_idx = lang_options.index(current_lang) if current_lang in lang_options else 0

    selected_label = st.sidebar.selectbox(
        t("lang_switch"),
        options=lang_labels,
        index=current_idx,
    )
    selected_lang = lang_options[lang_labels.index(selected_label)]
    if selected_lang != current_lang:
        set_lang(selected_lang)
        st.rerun()

    st.sidebar.markdown("---")

    # API Key
    api_key = st.sidebar.text_input(
        t("sidebar_api_key"),
        type="password",
        value=os.environ.get("API_KEY", ""),
        help=t("sidebar_api_key_help"),
    )

    # Model Preset
    preset_names = list(MODEL_PRESETS.keys())
    preset_labels = {
        "budget": "💰 Budget" if LANG == "en" else "💰 经济型",
        "balanced": "⚖ Balanced" if LANG == "en" else "⚖ 均衡型",
        "maximum": "🚀 Maximum" if LANG == "en" else "🚀 最强型",
    }
    preset = st.sidebar.selectbox(
        t("sidebar_preset"),
        options=preset_names,
        format_func=lambda p: preset_labels.get(p, p),
        help=t("sidebar_preset_help"),
    )

    if preset in MODEL_PRESETS:
        p = MODEL_PRESETS[preset]
        st.sidebar.caption(
            f"🔍 {p['classifier']}\n"
            f"📝 {p['summarizer']}\n"
            f"🧪 {p['lab_solver']}"
        )

    # Advanced
    with st.sidebar.expander(t("sidebar_advanced")):
        classifier_model = st.text_input(
            t("sidebar_classifier_model"),
            value=MODEL_PRESETS[preset]["classifier"],
            help=t("sidebar_classifier_model_help"),
        )
        summarizer_model = st.text_input(
            t("sidebar_summarizer_model"),
            value=MODEL_PRESETS[preset]["summarizer"],
            help=t("sidebar_summarizer_model_help"),
        )
        lab_model = st.text_input(
            t("sidebar_lab_model"),
            value=MODEL_PRESETS[preset]["lab_solver"],
            help=t("sidebar_lab_model_help"),
        )
        input_dir = st.text_input(t("sidebar_input_dir"), value="01_Input_PPTs")
        output_dir = st.text_input(t("sidebar_output_dir"), value="02_Output_Notes")
        state_file = st.text_input(t("sidebar_state_file"), value=".sync_state.json")

    # Apply
    if st.sidebar.button(f"✅ {t('sidebar_apply')}", type="primary", use_container_width=True):
        if not api_key:
            st.sidebar.error(t("sidebar_api_required"))
            return None

        os.environ["API_KEY"] = api_key
        os.environ["CLASSIFIER_MODEL"] = classifier_model
        os.environ["SUMMARIZER_MODEL"] = summarizer_model
        os.environ["LAB_SOLVER_MODEL"] = lab_model
        os.environ["INPUT_DIR"] = input_dir
        os.environ["OUTPUT_DIR"] = output_dir
        os.environ["STATE_FILE"] = state_file

        try:
            settings = Settings.from_env()
            st.session_state.settings = settings
            st.session_state.pipeline = Pipeline(settings)
            st.sidebar.success(t("sidebar_applied"))
            return settings
        except ValueError as exc:
            st.sidebar.error(f"{t('sidebar_config_error')}: {exc}")
            return None

    return None


# ======================================================================
# Tab 1: Dashboard
# ======================================================================

def render_dashboard(settings: Optional[Settings]) -> None:
    st.header(f"📊 {t('dashboard_header')}")

    if settings is None:
        st.info(f"👈 {t('dashboard_get_started')}")
        return

    col1, col2, col3 = st.columns(3)

    scanner = FileScanner(settings.input_dir, settings.supported_extensions)
    try:
        files = scanner.scan()
    except Exception:
        files = []

    with col1:
        st.metric(t("dashboard_files_input"), len(files))

    state_mgr = StateManager(settings.state_file)
    try:
        state = state_mgr.load_state()
    except Exception:
        state = {}

    with col2:
        st.metric(t("dashboard_tracked_state"), len(state))

    processed = sum(1 for r in state.values() if r.status == "processed")
    with col3:
        st.metric(t("dashboard_processed"), processed)

    st.subheader(f"📁 {t('dashboard_file_list')}")
    if files:
        rows = []
        for fp in files:
            record = state.get(fp.name)
            if record is None:
                icon, status_text = "🆕", t("dashboard_status_new")
            elif record.status == "error":
                icon, status_text = "⚠️", t("dashboard_status_error")
            else:
                current_md5 = state_mgr.compute_md5(fp)
                if current_md5 != record.md5:
                    icon, status_text = "🔄", t("dashboard_status_modified")
                else:
                    icon, status_text = "✅", t("dashboard_status_uptodate")

            rows.append({
                t("dashboard_col_status"): icon,
                t("dashboard_col_filename"): fp.name,
                t("dashboard_col_state"): status_text,
                t("dashboard_col_last_processed"): record.last_processed[:19] if record else "—",
            })

        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info(t("dashboard_no_files"))


# ======================================================================
# Tab 2: Processing
# ======================================================================

def render_processing(settings: Optional[Settings]) -> None:
    st.header(f"⚡ {t('processing_header')}")

    if settings is None:
        st.info(f"👈 {t('processing_get_started')}")
        return

    pipeline = st.session_state.get("pipeline")
    if pipeline is None:
        pipeline = Pipeline(settings)
        st.session_state.pipeline = pipeline

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button(f"🚀 {t('processing_run_btn')}", type="primary", use_container_width=True):
            st.session_state.processing = True
            st.session_state.progress_messages = []
            st.rerun()

    with col2:
        if st.button(f"🔍 {t('processing_dry_run_btn')}", use_container_width=True):
            with st.spinner(t('processing_scanning')):
                report = pipeline.dry_run()
                st.session_state.report = report
            st.success(t("processing_dry_complete").format(count=len(report.details)))
            if report.details:
                rows = [
                    {
                        t("processing_dry_col_filename"): d.filename,
                        t("processing_dry_col_course"): d.course,
                        t("processing_dry_col_week"): d.week,
                        t("processing_dry_col_topic"): d.topic,
                    }
                    for d in report.details
                ]
                st.dataframe(rows, use_container_width=True)

    with col3:
        force_files = st.text_input(
            t("processing_force_label"),
            placeholder=t("processing_force_placeholder"),
        )

    # Progress display
    progress_placeholder = st.empty()

    if st.session_state.get("processing"):
        force_list = (
            [f.strip() for f in force_files.split(",") if f.strip()]
            if force_files else None
        )

        progress_bar = progress_placeholder.progress(0)
        status_text = st.empty()

        def ui_progress(message: str, fraction: float) -> None:
            progress_bar.progress(fraction)
            status_text.text(message)

        try:
            report = pipeline.run(
                progress_callback=ui_progress,
                force_files=force_list,
            )
            st.session_state.report = report
            st.session_state.processing = False
            progress_bar.progress(100)
            status_text.text(f"✅ {t('processing_complete')}")

            st.subheader(f"📋 {t('processing_report_title')}")
            ca, cb, cc, cd, ce = st.columns(5)
            ca.metric(t("processing_scanned"), report.total_scanned)
            cb.metric(t("processing_new_changed"), report.new_or_changed)
            cc.metric(f"✅ {t('processing_ok')}", report.processed)
            cd.metric(f"❌ {t('processing_err')}", report.errors)
            ce.metric(t("processing_time"), f"{report.elapsed_seconds:.1f}s")

            if report.details:
                rows = [
                    {
                        t("processing_col_filename"): d.filename,
                        t("processing_col_status"): "✅" if d.status == "processed" else "❌",
                        t("processing_col_course"): d.course,
                        t("processing_col_week"): d.week,
                        t("processing_col_output"): d.output_path or d.error,
                    }
                    for d in report.details
                ]
                st.dataframe(rows, use_container_width=True)

        except Exception as exc:
            st.session_state.processing = False
            st.error(f"{t('processing_pipeline_error')}: {exc}")
            logger.exception("Pipeline failed")

    # Last report
    if st.session_state.get("report") and not st.session_state.get("processing"):
        with st.expander(t("processing_last_details")):
            report = st.session_state.report
            st.json({
                "total_scanned": report.total_scanned,
                "new_or_changed": report.new_or_changed,
                "processed": report.processed,
                "errors": report.errors,
                "skipped": report.skipped,
                "elapsed_seconds": report.elapsed_seconds,
            })


# ======================================================================
# Tab 3: Output Browser
# ======================================================================

def render_output_browser(settings: Optional[Settings]) -> None:
    st.header(f"📝 {t('output_header')}")

    if settings is None:
        st.info(f"👈 {t('output_get_started')}")
        return

    output_dir = settings.output_dir

    if not output_dir.exists():
        st.info(t("output_no_dir"))
        return

    md_files = sorted(output_dir.rglob("*.md"))
    if not md_files:
        st.info(t("output_no_files"))
        return

    st.subheader(f"📂 {output_dir.name}")

    courses: dict[str, list[Path]] = {}
    for f in md_files:
        try:
            rel = f.relative_to(output_dir)
            course = rel.parts[0] if rel.parts else "Root"
        except ValueError:
            course = "Other"
        courses.setdefault(course, []).append(f)

    for course, files in sorted(courses.items()):
        label = f"📁 {course}" + (f" ({len(files)} files)" if LANG == "en" else f" ({len(files)} 个文件)")
        with st.expander(label, expanded=True):
            for f_path in sorted(files):
                try:
                    rel_path = str(f_path.relative_to(output_dir))
                except ValueError:
                    rel_path = str(f_path)

                c1, c2 = st.columns([4, 1])
                with c1:
                    st.markdown(f"📄 **{rel_path}**")
                with c2:
                    if st.button(t("output_view_btn"), key=f"view_{rel_path}"):
                        try:
                            content = f_path.read_text(encoding="utf-8")
                            st.session_state[f"content_{rel_path}"] = content
                        except Exception as exc:
                            st.error(f"{t('output_cannot_read')}: {exc}")

                content_key = f"content_{rel_path}"
                if st.session_state.get(content_key):
                    with st.container():
                        st.markdown("---")
                        st.markdown(st.session_state[content_key])
                        if st.button(t("output_close_btn"), key=f"close_{rel_path}"):
                            del st.session_state[content_key]
                            st.rerun()
                        st.markdown("---")


# ======================================================================
# Main entry
# ======================================================================

def render_app() -> None:
    st.set_page_config(
        page_title="Review Agent",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Initialize session state
    if "lang" not in st.session_state:
        st.session_state["lang"] = "en"
    if "has_visited" not in st.session_state:
        st.session_state["has_visited"] = False
    if "settings" not in st.session_state:
        st.session_state["settings"] = None
    if "pipeline" not in st.session_state:
        st.session_state["pipeline"] = None
    if "report" not in st.session_state:
        st.session_state["report"] = None
    if "processing" not in st.session_state:
        st.session_state["processing"] = False
    if "landing_lang" not in st.session_state:
        st.session_state["landing_lang"] = "en"

    init_lang()

    # ---- Landing page (first visit only) ----
    if not st.session_state["has_visited"]:
        render_landing_page()
        return

    # ---- Main app ----
    st.title("📚 Review Agent")
    st.caption(t("landing_subtitle"))

    settings = render_sidebar()

    tab1, tab2, tab3 = st.tabs([
        f"📊 {t('tab_dashboard')}",
        f"⚡ {t('tab_processing')}",
        f"📝 {t('tab_output')}",
    ])

    with tab1:
        render_dashboard(settings)

    with tab2:
        render_processing(settings)

    with tab3:
        render_output_browser(settings)


if __name__ == "__main__":
    render_app()
