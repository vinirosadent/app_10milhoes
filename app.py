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
from core.database import get_investimentos_ativo

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

# ── Modulo de investimentos (por household) ───────────────────────────────
# A pagina so entra na navegacao se households.investimentos_ativo = TRUE
# (hoje: Admin sim, Ladroes nao). Cacheado no session_state por sessao de
# login — 1 query por login em vez de 1 por rerun; logout() faz clear() do
# session_state inteiro, entao o proximo login re-consulta o banco.
if "investimentos_ativo" not in st.session_state:
    st.session_state["investimentos_ativo"] = get_investimentos_ativo()

paginas = [home, lancamentos, dashboard]
if st.session_state["investimentos_ativo"]:
    paginas.append(st.Page("pages/04_Investimentos.py", title="Investimentos", icon="💎"))
paginas.append(configuracoes)

pg = st.navigation(paginas)
pg.run()
