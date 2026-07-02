"""
Configuration management for the Review Agent.

Loads settings from .env file and environment variables with layered resolution:
    defaults < .env file < environment variables < CLI arguments
"""

import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model presets for quick switching
# ---------------------------------------------------------------------------

MODEL_PRESETS = {
    "budget": {
        "classifier": "gemini/gemini-2.0-flash",
        "summarizer": "deepseek/deepseek-chat",
        "lab_solver": "deepseek/deepseek-chat",
    },
    "balanced": {
        "classifier": "gemini/gemini-2.0-flash",
        "summarizer": "claude-sonnet-4-20250514",
        "lab_solver": "claude-sonnet-4-20250514",
    },
    "maximum": {
        "classifier": "claude-sonnet-4-20250514",
        "summarizer": "claude-opus-4-20250514",
        "lab_solver": "claude-opus-4-20250514",
    },
}

# Default project root: the directory containing main.py / app.py
# We detect it relative to this file's location: src/config/settings.py -> ../../ = project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class Settings:
    """Immutable settings container.  Use ``Settings.from_env()`` to construct."""

    # ---- Paths ----
    input_dir: Path
    output_dir: Path
    state_file: Path

    # ---- Classifier (cheap / fast model) ----
    classifier_model: str
    classifier_api_key: str
    classifier_api_base: Optional[str]
    classifier_temperature: float
    classifier_max_tokens: int

    # ---- Summarizer (powerful model) ----
    summarizer_model: str
    summarizer_api_key: str
    summarizer_api_base: Optional[str]
    summarizer_temperature: float
    summarizer_max_tokens: int

    # ---- Lab Solver (code-capable model) ----
    lab_solver_model: str
    lab_solver_api_key: str
    lab_solver_api_base: Optional[str]
    lab_solver_temperature: float
    lab_solver_max_tokens: int

    # ---- Processing ----
    classification_slide_count: int
    max_retries: int
    retry_base_delay: float
    supported_extensions: tuple = (".pptx", ".ppt", ".pdf")
    review_mode: str = "basic"  # "off" | "basic" | "deep"

    # ---- Logging ----
    log_level: str = "INFO"

    # ---- Preset ----
    preset: Optional[str] = None

    @classmethod
    def from_env(cls, overrides: Optional[dict] = None) -> "Settings":
        """
        Load configuration from .env file + environment variables.

        Resolution order (last wins):
            1. Hard-coded defaults
            2. .env file
            3. Environment variables
            4. *overrides* dict (from CLI arguments)

        Parameters
        ----------
        overrides : dict | None
            Manual overrides, e.g. ``{"input_dir": "/custom/path"}``.

        Returns
        -------
        Settings
        """
        # Attempt to load .env – it's okay if the file doesn't exist yet
        _try_load_dotenv()

        overrides = overrides or {}

        # ---- API key cascading ----
        master_key = _env("API_KEY", "")
        classifier_key = _env("CLASSIFIER_API_KEY") or master_key
        summarizer_key = _env("SUMMARIZER_API_KEY") or master_key
        lab_key = _env("LAB_SOLVER_API_KEY") or master_key

        # ---- Model cascading ----
        # Apply preset first, then individual env vars override
        preset_name = _env("PRESET", "")
        if preset_name and preset_name in MODEL_PRESETS:
            preset = MODEL_PRESETS[preset_name]
            default_classifier = preset["classifier"]
            default_summarizer = preset["summarizer"]
            default_lab = preset["lab_solver"]
        else:
            default_classifier = "gemini/gemini-2.0-flash"
            default_summarizer = "claude-sonnet-4-20250514"
            default_lab = ""  # empty = fall back to summarizer model

        classifier_model = _env("CLASSIFIER_MODEL") or default_classifier
        summarizer_model = _env("SUMMARIZER_MODEL") or default_summarizer
        lab_solver_model = _env("LAB_SOLVER_MODEL") or default_lab or summarizer_model

        # ---- Paths ----
        raw_input = overrides.get("input_dir") or _env("INPUT_DIR") or str(_PROJECT_ROOT / "01_Input_PPTs")
        raw_output = overrides.get("output_dir") or _env("OUTPUT_DIR") or str(_PROJECT_ROOT / "02_Output_Notes")
        raw_state = overrides.get("state_file") or _env("STATE_FILE") or str(_PROJECT_ROOT / ".sync_state.json")

        input_dir = Path(raw_input)
        if not input_dir.is_absolute():
            input_dir = _PROJECT_ROOT / input_dir

        output_dir = Path(raw_output)
        if not output_dir.is_absolute():
            output_dir = _PROJECT_ROOT / output_dir

        state_file = Path(raw_state)
        if not state_file.is_absolute():
            state_file = _PROJECT_ROOT / state_file

        # ---- Validate required ----
        if not classifier_key and not summarizer_key and not lab_key:
            raise ValueError(
                "No API key configured. Set API_KEY (or model-specific keys) in .env or environment."
            )

        # ---- Construct ----
        return cls(
            input_dir=input_dir,
            output_dir=output_dir,
            state_file=state_file,
            classifier_model=classifier_model,
            classifier_api_key=classifier_key,
            classifier_api_base=_env("CLASSIFIER_API_BASE") or None,
            classifier_temperature=float(_env("CLASSIFIER_TEMPERATURE", "0.1")),
            classifier_max_tokens=int(_env("CLASSIFIER_MAX_TOKENS", "512")),
            summarizer_model=summarizer_model,
            summarizer_api_key=summarizer_key,
            summarizer_api_base=_env("SUMMARIZER_API_BASE") or None,
            summarizer_temperature=float(_env("SUMMARIZER_TEMPERATURE", "0.3")),
            summarizer_max_tokens=int(_env("SUMMARIZER_MAX_TOKENS", "4096")),
            lab_solver_model=lab_solver_model,
            lab_solver_api_key=lab_key,
            lab_solver_api_base=_env("LAB_SOLVER_API_BASE") or None,
            lab_solver_temperature=float(_env("LAB_SOLVER_TEMPERATURE", "0.2")),
            lab_solver_max_tokens=int(_env("LAB_SOLVER_MAX_TOKENS", "4096")),
            classification_slide_count=int(_env("CLASSIFICATION_SLIDE_COUNT", "3")),
            max_retries=int(_env("MAX_RETRIES", "3")),
            retry_base_delay=float(_env("RETRY_BASE_DELAY", "2.0")),
            review_mode=_validate_review_mode(_env("REVIEW_MODE", "basic")),
            log_level=_env("LOG_LEVEL", "INFO").upper(),
            preset=preset_name or None,
        )

    def ensure_directories(self) -> None:
        """Create input and output directories if they don't exist."""
        for d in (self.input_dir, self.output_dir):
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created directory: {d}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _try_load_dotenv() -> None:
    """Load .env from the project root if ``python-dotenv`` is installed."""
    try:
        from dotenv import load_dotenv

        env_path = _PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=str(env_path))
        else:
            # Try loading from cwd as fallback
            load_dotenv()
    except ImportError:
        pass  # python-dotenv not installed – rely on real env vars


def _env(key: str, default: str = "") -> str:
    """Return *key* from ``os.environ``, or *default*."""
    return os.environ.get(key, default)


def _validate_review_mode(mode: str) -> str:
    """Normalize review mode to one of: off, basic, deep."""
    mode = mode.strip().lower()
    if mode in ("off", "basic", "deep"):
        return mode
    return "basic"
