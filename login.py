"""
Tela de login do App 10M (Etapa 3 - 2 logins compartilhados Admin/Ladrons).

Aceita usuario (nome curto, ex: 'admin' ou 'ladrons') OU email completo no
campo de login. A funcao autenticar_usuario() em core/database.py faz o lookup
casando contra ambas as colunas. Apos sucesso, popula st.session_state com o
dict do usuario logado — usado por core/database.py para filtrar queries pelo
household_id correto.

Mensagens de erro nao distinguem 'usuario nao existe' de 'senha errada' para
nao virar oraculo de validade de nome.
"""
import streamlit as st
from core.database import autenticar_usuario


def login_page():
    st.title("🐯 App dos 10 Milhões")
    st.markdown("---")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("### 🔐 Login")
        usuario = st.text_input("Usuário", placeholder="admin")
        senha   = st.text_input("Senha", placeholder="••••••••", type="password")

        if st.button("Entrar", type="primary", use_container_width=True):
            if not usuario or not senha:
                st.error("Preencha usuário e senha.")
                return
            user = autenticar_usuario(usuario, senha)
            if user is None:
                st.error("Usuário ou senha inválidos.")
                return
            st.session_state["autenticado"] = True
            st.session_state["user"] = user
            st.rerun()

        st.caption(
            "Esqueceu a senha? Você pode trocar a qualquer momento em "
            "**Configurações → 🔑 Minha senha** (após logar)."
        )
