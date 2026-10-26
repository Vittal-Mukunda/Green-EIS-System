"""Entry point for hosts that run `streamlit_app.py` from the repository root (Streamlit Community Cloud).

It only runs the dashboard; locally, `streamlit run dashboard/app.py` does the same thing.
"""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "dashboard" / "app.py"), run_name="__main__")
