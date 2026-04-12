import streamlit as st

def login_page():
    st.title("🐯 App dos 10 Milhões")
    st.markdown("---")

    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("### 🔐 Login")
        usuario = st.text_input("Usuário", placeholder="admin")
        senha   = st.text_input("Senha",   placeholder="••••••••", type="password")

        if st.button("Entrar", type="primary", use_container_width=True):
            if usuario == "admin" and senha == "admin123":
                st.session_state["autenticado"] = True
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos.")