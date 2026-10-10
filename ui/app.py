"""Streamlit entry point (spec 10): `make ui`. All data comes from the API (spec 09), never from DuckDB.

Pages depend on the persona (`views.page_keys`): Chat for everyone, Claim Dossier for staff, Eval Dashboard
for personas with can_read_eval_reports. Coverage Matrix and Leakage Radar are deferred (3-day scope).
"""

import chat_page
import dossier_page
import eval_page
import sidebar
import state
import streamlit as st
from views import page_keys

st.set_page_config(page_title="Insurance assistant", page_icon="🛡️", layout="wide")
state.api()
ident = sidebar.render()
PAGES = {
    "chat": st.Page(chat_page.render, title="Chat", icon="💬", default=True, url_path="chat"),
    "dossier": st.Page(dossier_page.render, title="Claim Dossier", icon="📋", url_path="dossier"),
    "eval": st.Page(eval_page.render, title="Eval Dashboard", icon="📊", url_path="eval"),
}
st.navigation([PAGES[k] for k in page_keys(ident.persona)]).run()
