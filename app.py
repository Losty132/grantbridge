"""Federal Funds Matchmaker: Streamlit entry point.  Run:  streamlit run app.py"""
import logging

import streamlit as st

st.set_page_config(page_title="Federal Funds Matchmaker", layout="wide")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from interface.main import run  # noqa: E402

run()
