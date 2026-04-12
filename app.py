import streamlit as st

st.set_page_config(
    page_title="App dos 10 Milhoes",
    page_icon="🐯",
    layout="wide",
    initial_sidebar_state="expanded",
)

pages = [
    st.Page("pages/Home.py",          title="Home",          icon="🏠"),
    st.Page("pages/01_Lancamentos.py",   title="Lancamentos",   icon="📝"),
    st.Page("pages/02_Dashboard.py",     title="Dashboard",     icon="📊"),
    st.Page("pages/03_Configuracoes.py", title="Configurações", icon="🔧"),
]

pg = st.navigation(pages)
pg.run()