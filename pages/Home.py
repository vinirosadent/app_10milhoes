import streamlit as st

st.title("🐯 App dos Milhões 🐯")
st.markdown("---")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### 📝 Lancamentos")
    st.write("Registre entradas e saidas do mes")
    if st.button("Acessar", key="btn_lan", use_container_width=True, type="primary"):
        st.switch_page("pages/01_Lancamentos.py")

with col2:
    st.markdown("### 📊 Dashboard")
    st.write("Graficos, resumos e evolucao")
    if st.button("Acessar", key="btn_dash", use_container_width=True, type="primary"):
        st.switch_page("pages/02_Dashboard.py")

with col3:
    st.markdown("### 🔧 Configuracoes")
    st.write("Editar lancamentos, usuarios e mais")
    if st.button("Acessar", key="btn_cfg", use_container_width=True, type="primary"):
        st.switch_page("pages/03_Configuracoes.py")

st.markdown("---")
st.caption("Use o menu lateral ou os botoes acima para navegar.")