import streamlit as st
from pages.Login import login_page

st.set_page_config(
    page_title="App dos 10 Milhoes",
    page_icon="🐯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Verifica autenticacao
if not st.session_state.get("autenticado"):
    login_page()
    st.stop()

# App principal — so aparece apos login
home          = st.Page("pages/Home.py",             title="Home",          icon="🏠", default=True)
lancamentos   = st.Page("pages/01_Lancamentos.py",   title="Lancamentos",   icon="📝")
dashboard     = st.Page("pages/02_Dashboard.py",     title="Dashboard",     icon="📊")
configuracoes = st.Page("pages/03_Configuracoes.py", title="Configurações", icon="🔧")

pg = st.navigation([home, lancamentos, dashboard, configuracoes])
pg.run()