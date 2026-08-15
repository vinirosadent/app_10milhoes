"""
Home do App 10M — cards de navegacao para as paginas principais.

O card de Investimentos so aparece quando o modulo esta habilitado para o
household logado (flag investimentos_ativo cacheada no session_state pelo
app.py antes de montar a navegacao).
"""
import streamlit as st

from core.auth import restrito_a_renda_passiva

st.title("🐯 App dos Milhões 🐯")
st.markdown("---")

# Flag setada pelo app.py (1 query por sessao de login). .get() com default
# False: se a Home rodar fora do fluxo normal, o card simplesmente nao aparece.
tem_investimentos = st.session_state.get("investimentos_ativo", False)

# Os cards precisam espelhar o MENU: st.switch_page so aceita paginas
# registradas no st.navigation(), entao um atalho para pagina fora do menu
# levanta StreamlitAPIException em vez de navegar. O household do Ricardo nao
# tem Patrimonio no menu — no lugar dele entra o atalho de Renda Passiva.
restrito = restrito_a_renda_passiva()

colunas = st.columns(5 if tem_investimentos else 4)

with colunas[0]:
    st.markdown("### 📝 Lancamentos")
    st.write("Registre entradas e saidas do mes")
    if st.button("Acessar", key="btn_lan", use_container_width=True, type="primary"):
        st.switch_page("pages/01_Lancamentos.py")

with colunas[1]:
    st.markdown("### 📊 Dashboard")
    st.write("Graficos, resumos e evolucao")
    if st.button("Acessar", key="btn_dash", use_container_width=True, type="primary"):
        st.switch_page("pages/02_Dashboard.py")

if tem_investimentos:
    with colunas[2]:
        st.markdown("### 💎 Investimentos")
        st.write("Aportes, dividendos e total guardado")
        if st.button("Acessar", key="btn_inv", use_container_width=True, type="primary"):
            st.switch_page("pages/04_Investimentos.py")

with colunas[-2]:
    if restrito:
        st.markdown("### 🌱 Renda Passiva")
        st.write("Proventos e rendimentos por categoria")
        if st.button("Acessar", key="btn_rp", use_container_width=True, type="primary"):
            st.switch_page("pages/06_Ricardo.py")
    else:
        st.markdown("### 📈 Patrimonio")
        st.write("Evolucao do patrimonio total da casa")
        if st.button("Acessar", key="btn_pat", use_container_width=True, type="primary"):
            st.switch_page("pages/05_Patrimonio.py")

with colunas[-1]:
    st.markdown("### 🔧 Configuracoes")
    st.write("Editar lancamentos, usuarios e mais")
    if st.button("Acessar", key="btn_cfg", use_container_width=True, type="primary"):
        st.switch_page("pages/03_Configuracoes.py")

st.markdown("---")
st.caption("Use o menu lateral ou os botoes acima para navegar.")
