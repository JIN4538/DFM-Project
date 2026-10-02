"""Compatibility entrypoint: streamlit run run_app.py launches AM-DFM 3.0."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
