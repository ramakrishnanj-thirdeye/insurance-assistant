"""Streamlit entry point (spec 10): `make ui`. All data comes from the API (spec 09), never from DuckDB.

M4 ships the Chat page; Claim Dossier, Coverage Matrix, Leakage Radar and Eval Dashboard are M8.
"""

import chat_page
import sidebar
import state
import streamlit as st

st.set_page_config(page_title="Insurance assistant", page_icon="🛡️", layout="wide")
state.api()
sidebar.render()
page = st.navigation([st.Page(chat_page.render, title="Chat", icon="💬", default=True)])
page.run()
