import streamlit as st

def aplicar_estilos():
    st.markdown("""
    <style>
    div[data-testid="stButton"] > button {
        border-radius: 8px !important;
        font-weight: 600 !important;
    }
    .danger-btn > div[data-testid="stButton"] > button {
        background-color: #C62828 !important;
        color: white !important;
        border: none !important;
    }
    .danger-btn > div[data-testid="stButton"] > button:hover {
        background-color: #B71C1C !important;
    }
    .secondary-btn > div[data-testid="stButton"] > button {
        background-color: #42A5F5 !important;
        color: white !important;
        border: none !important;
    }
    </style>
    """, unsafe_allow_html=True)

def danger_button(label, key=None, **kwargs):
    """Botao vermelho para acoes destrutivas."""
    st.markdown('<div class="danger-btn">', unsafe_allow_html=True)
    clicked = st.button(label, key=key, **kwargs)
    st.markdown('</div>', unsafe_allow_html=True)
    return clicked

def secondary_button(label, key=None, **kwargs):
    """Botao azul claro para acoes secundarias."""
    st.markdown('<div class="secondary-btn">', unsafe_allow_html=True)
    clicked = st.button(label, key=key, **kwargs)
    st.markdown('</div>', unsafe_allow_html=True)
    return clicked