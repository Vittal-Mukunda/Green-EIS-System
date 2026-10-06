"""Entry point for hosts that run `streamlit_app.py` from the repository root (Streamlit Community
Cloud) and cannot pass `-- --config ...`. It selects the deployment config and runs the dashboard.

Set GAUGE_CONFIG to use a different config, for example config/study_dry.yaml.
"""

import os
import runpy
from pathlib import Path

os.environ.setdefault("GAUGE_CONFIG", "config/study_demo.yaml")
runpy.run_path(str(Path(__file__).resolve().parent / "dashboard" / "app.py"), run_name="__main__")
