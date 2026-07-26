import streamlit as st

# ─────────────────────────────────────────────────────────────────────────
# Identidade visual do App 10M — sistema de design central.
# Tudo aqui e injetado uma vez (chamado no app.py) e vale pro app inteiro:
# tipografia elegante (Fraunces serif nos titulos/numeros + Manrope no corpo),
# paleta por tokens (variaveis CSS), cards, botoes, sidebar, inputs, abas,
# tabelas e alertas. Mexa nos tokens em :root pra reajustar tudo de um lugar so.
# ─────────────────────────────────────────────────────────────────────────

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&family=Manrope:wght@400;500;600;700;800&display=swap');

:root{
  --font-display:'Fraunces', Georgia, 'Times New Roman', serif;
  --font-body:'Manrope', -apple-system, 'Segoe UI', sans-serif;
  --bg:#F6F8FB; --surface:#FFFFFF; --surface-2:#EEF2F9; --border:#E6EBF4;
  --ink:#0F172A; --muted:#64748B;
  --primary:#2563EB; --primary-d:#1D4FD7;
  --primary-10:rgba(37,99,235,.10); --primary-20:rgba(37,99,235,.18);
  --accent:#F59E0B; --positive:#059669; --negative:#DC2626;
  --shadow:0 1px 2px rgba(15,23,42,.04), 0 6px 20px rgba(15,23,42,.06);
  --shadow-h:0 10px 30px rgba(37,99,235,.16);
  --radius:16px; --radius-sm:11px;
}

/* ---- base / tipografia ---- */
html, body, [class*="css"], .stApp, [data-testid="stMarkdownContainer"]{
  font-family:var(--font-body);
}
.stApp{ background:var(--bg); }
.main .block-container{ padding-top:2.2rem; padding-bottom:3rem; max-width:1280px; }

/* titulos no serif elegante */
h1,h2,h3,h4{
  font-family:var(--font-display); color:var(--ink);
  font-optical-sizing:auto; font-weight:600; letter-spacing:-.01em;
}
h1{ font-size:2.15rem; font-weight:700; margin-bottom:.2rem; }
h2{ font-size:1.55rem; } h3{ font-size:1.2rem; }
hr{ border:none; border-top:1px solid var(--border); margin:1.35rem 0; }

/* ---- KPI / metric viram cards (valor no serif) ---- */
[data-testid="stMetric"]{
  background:var(--surface); border:1px solid var(--border);
  border-radius:var(--radius); padding:1.05rem 1.2rem; box-shadow:var(--shadow);
  transition:transform .15s ease, box-shadow .15s ease;
}
[data-testid="stMetric"]:hover{ transform:translateY(-2px); box-shadow:var(--shadow-h); }
[data-testid="stMetricLabel"]{
  color:var(--muted); font-weight:600; font-size:.78rem;
  text-transform:uppercase; letter-spacing:.04em;
}
[data-testid="stMetricValue"]{
  font-family:var(--font-display); color:var(--ink); font-weight:600;
  font-size:1.9rem; font-variant-numeric:tabular-nums; font-optical-sizing:auto;
}
[data-testid="stMetricDelta"]{ font-weight:600; font-variant-numeric:tabular-nums; }

/* ---- botoes ---- */
div[data-testid="stButton"] > button{
  border-radius:var(--radius-sm)!important; font-weight:600!important;
  border:1px solid var(--border)!important; background:var(--surface); color:var(--ink);
  padding:.5rem 1.05rem!important; transition:all .15s ease;
  box-shadow:0 1px 2px rgba(15,23,42,.04);
}
div[data-testid="stButton"] > button:hover{
  border-color:var(--primary)!important; color:var(--primary); background:var(--primary-10);
}
div[data-testid="stButton"] > button[kind="primary"],
div[data-testid="stButton"] > button[data-testid="baseButton-primary"]{
  background:var(--primary)!important; color:#fff!important; border:none!important; box-shadow:var(--shadow);
}
div[data-testid="stButton"] > button[kind="primary"]:hover,
div[data-testid="stButton"] > button[data-testid="baseButton-primary"]:hover{
  background:var(--primary-d)!important; box-shadow:var(--shadow-h); transform:translateY(-1px);
}

/* botoes auxiliares (helpers abaixo) — restilizados pra paleta nova */
.danger-btn > div[data-testid="stButton"] > button{
  background:var(--negative)!important; color:#fff!important; border:none!important;
}
.danger-btn > div[data-testid="stButton"] > button:hover{ filter:brightness(.92); }
.secondary-btn > div[data-testid="stButton"] > button{
  background:var(--surface-2)!important; color:var(--primary)!important; border:1px solid var(--border)!important;
}
.secondary-btn > div[data-testid="stButton"] > button:hover{ background:var(--primary-10)!important; }

/* ---- sidebar ---- */
[data-testid="stSidebar"]{ background:var(--surface); border-right:1px solid var(--border); }
[data-testid="stSidebar"] .block-container{ padding-top:1.4rem; }
[data-testid="stSidebarNav"] a{ border-radius:10px; font-weight:600; }
[data-testid="stSidebarNav"] a:hover{ background:var(--primary-10); }

/* ---- inputs / selects ---- */
.stTextInput input, .stNumberInput input, .stDateInput input,
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"]{
  border-radius:10px!important;
}
.stTextInput input:focus, .stNumberInput input:focus, .stDateInput input:focus{
  border-color:var(--primary)!important; box-shadow:0 0 0 3px var(--primary-10)!important;
}
[data-testid="stWidgetLabel"] p{ font-weight:600; color:var(--ink); }

/* ---- abas ---- */
.stTabs [data-baseweb="tab-list"]{ gap:.3rem; border-bottom:1px solid var(--border); }
.stTabs [data-baseweb="tab"]{ font-weight:600; color:var(--muted); border-radius:10px 10px 0 0; }
.stTabs [aria-selected="true"]{ color:var(--primary)!important; }

/* ---- cards genericos (st.container(border=True)) ---- */
[data-testid="stVerticalBlockBorderWrapper"]{
  border:1px solid var(--border)!important; border-radius:var(--radius-sm)!important;
  background:var(--surface); box-shadow:var(--shadow);
}

/* ---- rotulo/valor dentro de um cartao de categoria (Patrimonio) ---- */
.pat-label{
  color:var(--muted); font-weight:600; font-size:.74rem;
  text-transform:uppercase; letter-spacing:.04em;
}
.pat-tag{
  display:inline-block; margin-left:.4rem; padding:.06rem .5rem;
  border-radius:999px; background:var(--primary-10); color:var(--primary-d);
  font-size:.66rem; font-weight:700; text-transform:none; letter-spacing:0;
  vertical-align:middle;
}
.pat-liquido{
  font-family:var(--font-body); color:var(--ink); font-weight:700;
  font-size:1.05rem; font-variant-numeric:tabular-nums; margin-top:.35rem;
}

/* ---- expander / dataframe / alertas ---- */
[data-testid="stExpander"]{
  border:1px solid var(--border)!important; border-radius:var(--radius-sm)!important;
  background:var(--surface); box-shadow:var(--shadow);
}
[data-testid="stDataFrame"], [data-testid="stTable"]{
  border:1px solid var(--border); border-radius:var(--radius-sm); overflow:hidden;
}
[data-testid="stAlert"]{ border-radius:var(--radius-sm); border:1px solid var(--border); }
[data-testid="stCaptionContainer"]{ color:var(--muted); }
</style>
"""


def aplicar_estilos():
    """Injeta a identidade visual do app. Chamar 1x, cedo, no app.py."""
    st.markdown(_CSS, unsafe_allow_html=True)


def danger_button(label, key=None, **kwargs):
    """Botao vermelho para acoes destrutivas."""
    st.markdown('<div class="danger-btn">', unsafe_allow_html=True)
    clicked = st.button(label, key=key, **kwargs)
    st.markdown('</div>', unsafe_allow_html=True)
    return clicked


def secondary_button(label, key=None, **kwargs):
    """Botao secundario (paleta suave)."""
    st.markdown('<div class="secondary-btn">', unsafe_allow_html=True)
    clicked = st.button(label, key=key, **kwargs)
    st.markdown('</div>', unsafe_allow_html=True)
    return clicked
