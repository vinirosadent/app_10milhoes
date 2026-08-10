"""
Camada de BI compartilhada do App 10M (graficos + cards de KPI).

Fonte unica de verdade visual do app: cores, lista de meses, formatacao de
dinheiro, um tema Plotly consistente e um punhado de builders de grafico
reutilizaveis. As paginas chamam estas funcoes em vez de montar Plotly inline —
assim todo grafico tem a mesma cara e a gente desenha cada tipo UMA vez.

Organizado em 2 blocos:
  1) PURO (sem Streamlit): constantes, formatacao, tema e builders que recebem
     um DataFrame e devolvem uma figura Plotly (go.Figure). Testaveis isolados.
  2) STREAMLIT: helpers de card de KPI (st.metric) — dependem do runtime do app.
"""
from __future__ import annotations

import plotly.graph_objects as go

# ──────────────────────────────────────────────────────────────────────────
# 1) BLOCO PURO — constantes, formatacao, tema e builders de grafico
# ──────────────────────────────────────────────────────────────────────────

# Cores semanticas (as mesmas ja usadas no Dashboard — aqui viram fonte unica).
COR_ENTRADA      = "#2E7D32"   # verde    — dinheiro que entra
COR_SAIDA        = "#C62828"   # vermelho — dinheiro que sai
COR_SALDO        = "#1565C0"   # azul     — saldo / resultado
COR_INVESTIMENTO = "#F9A825"   # dourado  — aporte (nem entrada nem saida)
COR_NEUTRA       = "#90A4AE"   # cinza    — serie de apoio / referencia

# Paleta categorica (quebras por categoria/pessoa/produto). Ordem fixa = mesma
# categoria sempre na mesma cor ao longo dos graficos.
PALETA = [
    "#1565C0", "#2E7D32", "#E65100", "#6A1B9A", "#00838F",
    "#AD1457", "#F57F17", "#558B2F", "#4527A0", "#00695C",
]

# Meses em PT — fonte unica (estava copiado inline em varias paginas).
MESES_PT = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]
MESES_ABREV = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
               "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

# Moeda do app (tudo em SGD).
SIMBOLO_MOEDA = "S$"


def fmt_moeda(valor, casas: int = 0, simbolo: str = SIMBOLO_MOEDA) -> str:
    """
    Formata numero como dinheiro: fmt_moeda(1234.5) -> 'S$ 1,234'.
    Separador de milhar ',' e decimal '.' (padrao Singapura/ingles, onde o casal
    mora). Pra trocar pro padrao BR (1.234,56) muda-se SO aqui. casas=0 nos
    dashboards (numero limpo); casas=2 em tabela de detalhe.
    """
    try:
        return f"{simbolo} {float(valor):,.{casas}f}"
    except (TypeError, ValueError):
        return f"{simbolo} 0"


def _rgba(cor_hex: str, alpha: float) -> str:
    """Converte '#RRGGBB' em 'rgba(r,g,b,alpha)' pra preenchimento translucido."""
    h = cor_hex.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def aplicar_tema(fig: go.Figure, titulo=None, altura: int = 340,
                 moeda_eixo_y: bool = True) -> go.Figure:
    """
    Aplica o visual padrao do app a QUALQUER figura Plotly e devolve ela mesma.
    Decisoes de design (e o porque):
      - fundo transparente: combina com tema claro OU escuro do Streamlit.
      - sem grade vertical + grade horizontal discreta: menos tinta, foco no
        dado (principio de data-ink ratio).
      - legenda horizontal no topo: nao rouba largura do grafico.
      - hover unificado por x: comparar series no mesmo mes fica facil
        (builders de barra horizontal/rosca trocam pra 'closest').
      - eixo y em dinheiro (S$, milhar) quando moeda_eixo_y=True.
    """
    # `title=None` NAO e' o mesmo que nao mexer no titulo: o Plotly.js recebe o
    # campo explicitamente vazio e algumas versoes desenham a string "undefined"
    # acima da legenda. Por isso o titulo so entra no dict quando existe.
    layout = dict(
        height=altura,
        margin=dict(l=10, r=10, t=48 if titulo else 16, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
                  size=13, color="#1F2933"),
        legend=dict(orientation="h", yanchor="bottom", y=1.0,
                    xanchor="left", x=0.0),
        hovermode="x unified",
    )
    if titulo:
        layout["title"] = dict(text=titulo, x=0.0, xanchor="left",
                               font=dict(size=16, color="#1F2933"))
    fig.update_layout(**layout)
    fig.update_xaxes(showgrid=False, showline=True, linecolor="#CBD5E1",
                     ticks="outside", tickcolor="#CBD5E1")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(148,163,184,0.25)",
                     zeroline=True, zerolinecolor="rgba(148,163,184,0.5)",
                     showline=False)
    if moeda_eixo_y:
        fig.update_yaxes(tickprefix=f"{SIMBOLO_MOEDA} ", separatethousands=True)
    return fig


def fmt_moeda_md(valor, casas: int = 0, simbolo: str = SIMBOLO_MOEDA) -> str:
    """
    Igual a fmt_moeda, mas com o cifrao ESCAPADO para uso em markdown/caption.

    Por que isso existe: o Streamlit interpreta `$...$` como LaTeX. Como o
    simbolo daqui e "S$", qualquer texto com DOIS valores monetarios vira
    formula — o miolo aparece em fonte matematica e, se houver HTML no meio, ele
    vaza cru na tela. Em st.metric nao ha esse risco (o valor nao passa por
    markdown); em st.markdown, st.caption e st.write, use esta funcao.
    """
    return fmt_moeda(valor, casas, simbolo).replace("$", "\\$")


def linha_temporal(df, x, series, titulo=None, area=False, altura: int = 340,
                   moeda: bool = True) -> go.Figure:
    """
    Linhas (ou areas) ao longo de um eixo x — tendencias no tempo.
    series: lista de dicts {'col','nome','cor'} — uma linha por serie.
    area=True preenche embaixo (bom pra 1 serie, ex.: net worth no tempo).
    Use em: saldo acumulado, patrimonio no tempo, performance, dividendos.
    """
    fig = go.Figure()
    for s in series:
        cor = s.get("cor", COR_SALDO)
        fig.add_trace(go.Scatter(
            x=df[x], y=df[s["col"]], name=s.get("nome", s["col"]),
            mode="lines+markers", line=dict(color=cor, width=2.5),
            fill="tozeroy" if area else None,
            fillcolor=_rgba(cor, 0.12) if area else None,
            hovertemplate="%{y:,.0f}<extra>" + str(s.get("nome", s["col"])) + "</extra>",
        ))
    return aplicar_tema(fig, titulo, altura, moeda_eixo_y=moeda)


def barras_mensais(df, x, series, titulo=None, modo: str = "group",
                   altura: int = 340, moeda: bool = True) -> go.Figure:
    """
    Barras por mes com uma ou mais series — comparacao mes a mes.
    modo='group' (lado a lado) ou 'stack' (empilhado).
    Use em: entradas vs saidas vs saldo por mes; gasto por pessoa por mes.
    """
    fig = go.Figure()
    for s in series:
        fig.add_trace(go.Bar(
            x=df[x], y=df[s["col"]], name=s.get("nome", s["col"]),
            marker_color=s.get("cor", COR_SALDO),
            hovertemplate="%{y:,.0f}<extra>" + str(s.get("nome", s["col"])) + "</extra>",
        ))
    fig.update_layout(barmode=modo)
    return aplicar_tema(fig, titulo, altura, moeda_eixo_y=moeda)


def barras_ranking(df, categoria, valor, titulo=None, cor=None, top=None,
                   altura=None, moeda: bool = True) -> go.Figure:
    """
    Ranking horizontal (maior em cima) — quebra por categoria/pessoa/produto.
    top=N mostra so os N maiores. cor=None usa a paleta (1 cor por barra);
    passar uma cor unica deixa todas iguais. Horizontal porque rotulo de
    categoria longo le melhor na vertical.
    """
    d = df[[categoria, valor]].copy().sort_values(valor, ascending=False)
    if top:
        d = d.head(top)
    d = d.sort_values(valor, ascending=True)  # plotly desenha de baixo p/ cima
    cores = cor if cor else [PALETA[i % len(PALETA)] for i in range(len(d))]
    fig = go.Figure(go.Bar(
        x=d[valor], y=d[categoria], orientation="h", marker_color=cores,
        hovertemplate="%{x:,.0f}<extra>%{y}</extra>",
    ))
    altura = altura or max(220, 28 * len(d) + 80)
    aplicar_tema(fig, titulo, altura, moeda_eixo_y=False)
    fig.update_xaxes(showgrid=True, gridcolor="rgba(148,163,184,0.25)")
    if moeda:
        fig.update_xaxes(tickprefix=f"{SIMBOLO_MOEDA} ", separatethousands=True)
    fig.update_yaxes(showgrid=False)
    fig.update_layout(hovermode="closest")
    return fig


def rosca(df, categoria, valor, titulo=None, cores=None,
          altura: int = 320) -> go.Figure:
    """
    Rosca (donut) — composicao/participacao de um todo (share por categoria,
    alocacao da carteira). Use com POUCAS fatias (ate ~6); com muitas
    categorias, prefira barras_ranking (le melhor).
    """
    fig = go.Figure(go.Pie(
        labels=df[categoria], values=df[valor], hole=0.55,
        marker=dict(colors=cores or PALETA), textinfo="percent",
        hovertemplate="%{label}: %{value:,.0f} (%{percent})<extra></extra>",
        sort=True, direction="clockwise",
    ))
    aplicar_tema(fig, titulo, altura, moeda_eixo_y=False)
    fig.update_layout(hovermode="closest")
    return fig


def orcado_vs_real(df, categoria, col_orcado, col_gasto, titulo=None,
                   altura=None) -> go.Figure:
    """
    Orcado vs Realizado por categoria — duas barras por categoria. Estouro
    (gasto > orcado) deixa a barra de gasto vermelha pra saltar aos olhos.
    Horizontal pra caber o rotulo da categoria.
    """
    d = df[[categoria, col_orcado, col_gasto]].copy().sort_values(col_gasto, ascending=True)
    cor_gasto = [COR_SAIDA if g > o else COR_SALDO
                 for o, g in zip(d[col_orcado], d[col_gasto])]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=d[categoria], x=d[col_orcado], orientation="h", name="Orçado",
        marker_color=COR_NEUTRA, opacity=0.55,
        hovertemplate="Orçado: %{x:,.0f}<extra>%{y}</extra>",
    ))
    fig.add_trace(go.Bar(
        y=d[categoria], x=d[col_gasto], orientation="h", name="Gasto",
        marker_color=cor_gasto,
        hovertemplate="Gasto: %{x:,.0f}<extra>%{y}</extra>",
    ))
    fig.update_layout(barmode="group")
    altura = altura or max(260, 34 * len(d) + 90)
    aplicar_tema(fig, titulo, altura, moeda_eixo_y=False)
    fig.update_xaxes(tickprefix=f"{SIMBOLO_MOEDA} ", separatethousands=True,
                     showgrid=True, gridcolor="rgba(148,163,184,0.25)")
    fig.update_yaxes(showgrid=False)
    fig.update_layout(hovermode="closest")
    return fig


def area_empilhada(df, x, categoria, valor, titulo=None, cores=None,
                   altura: int = 360, moeda: bool = True) -> go.Figure:
    """
    Area empilhada ao longo do tempo, uma faixa por categoria — composicao que
    evolui (valor da carteira por produto mes a mes; gasto por categoria no
    ano). df em formato LONGO (colunas x, categoria, valor).
    """
    cats = list(dict.fromkeys(df[categoria].tolist()))  # ordem de aparicao
    paleta = cores or PALETA
    fig = go.Figure()
    for i, c in enumerate(cats):
        sub = df[df[categoria] == c]
        cor = paleta[i % len(paleta)]
        fig.add_trace(go.Scatter(
            x=sub[x], y=sub[valor], name=str(c), mode="lines",
            stackgroup="um", line=dict(width=0.5, color=cor),
            fillcolor=_rgba(cor, 0.6),
            hovertemplate="%{y:,.0f}<extra>" + str(c) + "</extra>",
        ))
    return aplicar_tema(fig, titulo, altura, moeda_eixo_y=moeda)


# ──────────────────────────────────────────────────────────────────────────
# 2) BLOCO STREAMLIT — cards de KPI (dependem do runtime do app)
# Import do streamlit fica AQUI de proposito: separa visualmente o bloco puro
# (testavel sem Streamlit) do bloco que so roda dentro do app.
# ──────────────────────────────────────────────────────────────────────────
import streamlit as st


def card_kpi(rotulo, valor, delta=None, ajuda=None, eh_moeda: bool = True):
    """
    Um card de indicador (st.metric). Chame dentro de uma coluna:
        c1, c2, c3 = st.columns(3)
        with c1: charts.card_kpi("Entradas", 12000, delta=300)
    valor/delta viram dinheiro quando eh_moeda=True. A cor verde/vermelha do
    delta e automatica pelo sinal (padrao do st.metric).
    """
    v = fmt_moeda(valor) if eh_moeda else valor
    d = (fmt_moeda(delta) if eh_moeda else delta) if delta is not None else None
    st.metric(label=rotulo, value=v, delta=d, help=ajuda)


def linha_kpis(itens):
    """
    Atalho: monta uma linha de cards a partir de uma lista de dicts.
    itens = [{'rotulo','valor','delta'(opc),'ajuda'(opc),'eh_moeda'(opc)}, ...]
    """
    cols = st.columns(len(itens))
    for col, it in zip(cols, itens):
        with col:
            card_kpi(it["rotulo"], it["valor"], it.get("delta"),
                     it.get("ajuda"), it.get("eh_moeda", True))
