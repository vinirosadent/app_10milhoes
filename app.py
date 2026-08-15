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
from core.auth import logout, restrito_a_renda_passiva
from core.database import get_investimentos_ativo
from core.styles import aplicar_estilos

st.set_page_config(
    page_title="App dos Milhões",
    page_icon="🐯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Identidade visual (CSS global) — aplicada cedo, antes do login.
aplicar_estilos()

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
patrimonio    = st.Page("pages/05_Patrimonio.py",    title="Patrimônio",    icon="📈")
ricardo       = st.Page("pages/06_Ricardo.py",       title="Ricardo",       icon="👤")
configuracoes = st.Page("pages/03_Configuracoes.py", title="Configurações", icon="🔧")

# ── Modulo de investimentos (por household) ───────────────────────────────
# A pagina so entra na navegacao se households.investimentos_ativo = TRUE
# (hoje: Admin sim, Ladroes nao). Cacheado no session_state por sessao de
# login — 1 query por login em vez de 1 por rerun; logout() faz clear() do
# session_state inteiro, entao o proximo login re-consulta o banco.
if "investimentos_ativo" not in st.session_state:
    st.session_state["investimentos_ativo"] = get_investimentos_ativo()

# Cada login ve as paginas do PROPRIO household (o filtro household_id em cada
# query e o que isola os dados; o menu so decide o que faz sentido mostrar).
#
# Household do Ricardo: ele usa o app para as financas dele (lancamentos e
# orcamento proprios) e para acompanhar a renda passiva. Nao usa Patrimonio nem
# Projecoes, entao essas duas saem do menu dele. A pagina 06 aparece com o nome
# "Renda Passiva" — chamar de "Ricardo" so faz sentido do lado do Vinicius.
if restrito_a_renda_passiva():
    paginas = [
        home,
        lancamentos,
        dashboard,
        st.Page("pages/06_Ricardo.py", title="Renda Passiva", icon="🌱"),
        configuracoes,
    ]
else:
    paginas = [home, lancamentos, dashboard]
    if st.session_state["investimentos_ativo"]:
        paginas.append(st.Page("pages/04_Investimentos.py", title="Investimentos", icon="💎"))
        paginas.append(st.Page("pages/07_Dividendos_Fundos.py", title="Dividendos", icon="💰"))
    paginas.append(patrimonio)
    paginas.append(st.Page("pages/08_Projecoes.py", title="Projeções", icon="🔭"))
    paginas.append(ricardo)
    paginas.append(configuracoes)

pg = st.navigation(paginas)
pg.run()
