"""
Entry point do App 10M.

Gate de autenticacao: se nao houver st.session_state['autenticado'], mostra
login_page() e bloqueia o resto. Apos login, monta a navegacao Streamlit
nativa (st.Page) e exibe a identificacao do usuario logado + household na
sidebar com um botao de logout.
"""
import streamlit as st
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from login import login_page
from core.auth import logout

st.set_page_config(
    page_title="App dos Milhões",
    page_icon="🐯",
    layout="wide",
    initial_sidebar_state="expanded",
)

if not st.session_state.get("autenticado"):
    login_page()
    st.stop()

# ── Identificacao do usuario logado + logout na sidebar ──────────────────
user = st.session_state.get("user", {})
with st.sidebar:
    st.markdown(
        f"**{user.get('nome', '—')}**  \n"
        f"_{user.get('household_nome', '—')}_"
    )
    if st.button("🚪 Sair", use_container_width=True, key="btn_logout_sidebar"):
        logout()
    st.divider()

home          = st.Page("pages/Home.py",             title="Home",          icon="🏠", default=True)
lancamentos   = st.Page("pages/01_Lancamentos.py",   title="Lancamentos",   icon="📝")
dashboard     = st.Page("pages/02_Dashboard.py",     title="Dashboard",     icon="📊")
configuracoes = st.Page("pages/03_Configuracoes.py", title="Configurações", icon="🔧")

pg = st.navigation([home, lancamentos, dashboard, configuracoes])
pg.run()
