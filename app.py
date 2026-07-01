#!/usr/bin/env python3
"""
Review Agent – Streamlit Entry Point
=====================================
Launch with::

    streamlit run app.py

This is a thin wrapper that delegates to the full UI module.
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.ui.streamlit_app import render_app

if __name__ == "__main__":
    render_app()
