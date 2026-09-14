"""DFM Project — 실행 진입점

    streamlit run run_app.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.ui.app import main

if __name__ == "__main__":
    main()
