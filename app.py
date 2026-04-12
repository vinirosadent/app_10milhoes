import streamlit as st
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))
from login import login_page

st.set_page_config(
    page_title="App dos 10 Milhoes",
    page_icon="🐯",
    layout="wide",
    initial_sidebar_state="expanded",
)

if not st.session_state.get("autenticado"):
    login_page()
    st.stop()

home          = st.Page("pages/Home.py",             title="Home",          icon="🏠", default=True)
lancamentos   = st.Page("pages/01_Lancamentos.py",   title="Lancamentos",   icon="📝")
dashboard     = st.Page("pages/02_Dashboard.py",     title="Dashboard",     icon="📊")
configuracoes = st.Page("pages/03_Configuracoes.py", title="Configurações", icon="🔧")

pg = st.navigation([home, lancamentos, dashboard, configuracoes])
pg.run()