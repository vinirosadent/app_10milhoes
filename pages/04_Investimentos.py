"""
Pagina de Investimentos — modulo "dinheiro guardado" do App 10M.

Habilitada por household via households.investimentos_ativo (hoje so Admin).

Modelo financeiro completo (todos os anos, nao so 2026):

  Total aportado (custo)  = saldo inicial + Σ aportes        -> de `lancamentos`
  Rendimento total        = Σ rendimento (valorizacao +/-)   -> de `investimentos_serie`
  PATRIMONIO (valor mkt)  = Total aportado + Rendimento total
  Dividendos recebidos    = Σ dividendo                       -> de `investimentos_serie`

  1. O salario CHEIO ja e lancado como Entrada em Lancamentos.
  2. Parte dele vira aporte (conta -> corretora). Aporte NAO e saida nem entrada
     nova — e realocacao interna (valor_real=0): a poupanca do Dashboard nao muda,
     so cresce o "bolo investido".
  3. Rendimento e a VALORIZACAO da carteira no mes (pode ser + ou -). Nao e caixa:
     mora em `investimentos_serie`, por produto/mes (informado pelo usuario).
  4. Dividendo (renda do investimento) tambem vive em `investimentos_serie` — assim
     NAO entra no fluxo de caixa do Dashboard de 2026. (Se um dia quiser que conte
     como renda real na conta, e uma decisao separada.)

Aportes fixos mensais (ex.: 'Manu 4k' -> 4166/mes) ficam em config_investimentos
e sao registrados em LOTE com 1 clique por mes (anti-duplicacao). O backfill
historico dos aportes e gerado a partir de `data_inicio` de cada produto.
"""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import pandas as pd
import re
import sys
from pathlib import Path
from datetime import date

sys.path.append(str(Path(__file__).parent.parent))
from core.database import (
    get_membros_household, inserir_lancamento, delete_lancamentos,
    # Modulo de investimentos:
    get_investimentos_ativo, get_config_investimentos, add_config_investimento,
    update_config_investimento, get_aportes_fixos_registrados_no_mes,
    registrar_aportes_fixos, get_total_investido,
    get_saldo_inicial_investimentos, get_registros_investimentos,
    # Novos: serie (rendimento/dividendo), totais e evolucao multi-ano:
    get_total_rendimento, get_total_dividendos, get_aportado_no_ano,
    get_investimentos_evolucao, get_investimentos_evolucao_produto,
    upsert_serie, get_serie_df,
    # Entrada por Account Value (extrato): patrimonio anterior + aporte do mes:
    get_patrimonio_produto_antes, get_aporte_produto_mes,
    CAT_APORTE_VAR, CAT_SALDO_INICIAL,
)

# Ano corrente da aplicacao (hardcoded por enquanto, ver project_app10milhoes.md).
ANO_APP = 2026

st.set_page_config(page_title="Investimentos", page_icon="💎", layout="wide")

# ── Gate por household (defesa em profundidade) ────────────────────────────
ativo = st.session_state.get("investimentos_ativo")
if ativo is None:
    ativo = get_investimentos_ativo()
if not ativo:
    st.info("💎 O módulo de investimentos não está habilitado para o seu household.")
    st.stop()

st.title("💎 Investimentos")

# Paleta do projeto.
C_FIXO  = "#1565C0"   # aportes / custo
C_VAR   = "#42A5F5"   # aporte variavel
C_DIV   = "#2E7D32"   # dividendos (verde)
C_TOTAL = "#0D47A1"   # patrimonio / acumulado
C_REND  = "#00897B"   # rendimento (teal)
C_REND_FILL = "rgba(0,137,123,0.16)"  # area do ganho (patrimonio - custo)
C_NEG   = "#C62828"   # rendimento negativo

MESES_LISTA = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
               "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def fmt(fig, height=360, legend_side=False):
    """Formatacao padrao dos graficos — mesma identidade visual do Dashboard."""
    # Legenda embaixo para nao colidir com a barra do Plotly no canto superior
    # direito; assim todos os itens ficam clicaveis no mobile.
    leg = dict(orientation="v", x=1.02, y=0.5, xanchor="left") if legend_side \
        else dict(orientation="h", yanchor="top", y=-0.18, x=0, xanchor="left")
    fig.update_layout(
        height=height, margin=dict(l=0, r=0, t=12, b=8),
        plot_bgcolor="white", paper_bgcolor="white",
        legend=leg, font=dict(family="Segoe UI", size=12),
        hoverlabel=dict(bgcolor="white", font_size=13),
        hovermode="x unified",
    )
    fig.update_yaxes(gridcolor="#E0E7EF", zeroline=False)
    fig.update_xaxes(gridcolor="rgba(0,0,0,0)")
    return fig


# Config padrao do Plotly: sem barra de ferramentas flutuante (no mobile ela
# tapava a legenda e dava pan/zoom sem querer) e sem logo Plotly.
PLOTLY_CFG = {"displayModeBar": False, "displaylogo": False}


# Feedback persistente entre reruns.
if st.session_state.get("inv_msg"):
    st.success(st.session_state["inv_msg"])
    st.session_state["inv_msg"] = None

# ── Dados base ────────────────────────────────────────────────────────────
membros           = get_membros_household() or ["—"]
produtos_fixos_df = get_config_investimentos(somente_ativos=True, tipo="fixo")
produtos_todos_df = get_config_investimentos(somente_ativos=True)

# ── Filtro por produto (le session_state para queries usarem valor correto) ─
nomes_prod = produtos_todos_df["nome"].tolist() if not produtos_todos_df.empty else []
_sel = st.session_state.get("inv_filtro_prod", "Todos os produtos")
pf = None if _sel == "Todos os produtos" else _sel

df_evo            = get_investimentos_evolucao(pf)
df_evo_prod       = get_investimentos_evolucao_produto()

# Totais (respeitam o filtro de produto pf).
total_aportado   = get_total_investido(pf)    # saldo inicial + Σ aportes (= custo)
total_rendimento = get_total_rendimento(pf)
total_dividendos = get_total_dividendos(pf)
patrimonio       = total_aportado + total_rendimento
aportado_ano     = get_aportado_no_ano(ANO_APP, pf)
perc_rend        = (total_rendimento / total_aportado * 100) if total_aportado > 0 else None
saldo_inicial    = get_saldo_inicial_investimentos(pf)

# mapa nome->id dos produtos (para serie / dividendos).
prod_nome2id = {str(r["nome"]).lower(): int(r["id"])
                for _, r in produtos_todos_df.iterrows()} if not produtos_todos_df.empty else {}

quem_default = membros.index("Vinicius") if "Vinicius" in membros else 0
mes_default  = date.today().month - 1

# ══════════════════════════════════════════════════════════════════════════
# METRICAS
# ══════════════════════════════════════════════════════════════════════════
c1, c2, c3, c4 = st.columns(4)
c1.metric("💰 Patrimônio", f"SGD {patrimonio:,.0f}",
          help="Valor de mercado da carteira = total aportado (custo) + rendimento acumulado.")
c2.metric("📥 Total aportado", f"SGD {total_aportado:,.0f}",
          delta=f"+SGD {aportado_ano:,.0f} em {ANO_APP}",
          help="Quanto você já colocou (saldo inicial + todos os aportes). É o 'custo' da carteira.")
c3.metric("📈 Rendimento total", f"SGD {total_rendimento:,.0f}",
          delta=(f"{perc_rend:.1f}% s/ aportado" if perc_rend is not None else None),
          help="Ganho acumulado = valor de mercado − aportado. Já inclui dividendos "
               "reinvestidos e bônus, líquido de taxas.")
c4.metric("💵 Dividendos gerados", f"SGD {total_dividendos:,.0f}",
          help="Total que os fundos distribuíram. Reinvestidos já estão DENTRO do "
               "patrimônio; pagos em caixa (não reinvestidos) são renda que saiu da "
               "carteira pra você investir noutro lugar. Em ambos os casos é "
               "informativo — não soma de novo ao patrimônio.")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════
# SECAO 1 — EVOLUCAO (graficos multi-ano)
# ══════════════════════════════════════════════════════════════════════════
st.subheader("📊 Evolução" + (f" — {pf}" if pf else " da carteira"))

if df_evo.empty:
    st.info("Sem dados ainda — registre os aportes e os rendimentos para ver a evolução. 🚀")
else:
    col_g1, col_g2 = st.columns(2)

    # ── Patrimonio vs Aportado (custo) — a area entre as linhas e o ganho ──
    with col_g1:
        st.markdown("#### Patrimônio × aportado (custo)")
        figp = go.Figure()
        figp.add_trace(go.Scatter(
            x=df_evo["periodo"], y=df_evo["aporte_acum"], name="Aportado (custo)",
            mode="lines", line=dict(color=C_FIXO, width=2.5),
            hovertemplate="%{x|%b/%Y}<br>Aportado: SGD %{y:,.0f}<extra></extra>"))
        figp.add_trace(go.Scatter(
            x=df_evo["periodo"], y=df_evo["patrimonio"], name="Patrimônio (valor)",
            mode="lines", line=dict(color=C_TOTAL, width=2.5),
            fill="tonexty", fillcolor=C_REND_FILL,
            hovertemplate="%{x|%b/%Y}<br>Patrimônio: SGD %{y:,.0f}<extra></extra>"))
        figp.update_yaxes(tickprefix="")
        st.plotly_chart(fmt(figp), use_container_width=True, config=PLOTLY_CFG)
        if total_rendimento == 0:
            st.caption("As duas linhas coincidem porque ainda não há rendimento lançado — "
                       "a área verde (ganho) aparece quando você informar os rendimentos abaixo.")

    # ── Valor por produto (area empilhada) — só na visão consolidada ──────
    with col_g2:
        st.markdown("#### Valor por produto")
        if pf is not None:
            st.info(f"Mostrando **{pf}** isolado. Selecione **Todos os produtos** "
                    "no topo para ver a divisão por produto.")
        elif not df_evo_prod.empty and df_evo_prod["valor"].abs().sum() > 0:
            figv = px.area(df_evo_prod, x="periodo", y="valor", color="produto",
                           color_discrete_sequence=px.colors.qualitative.Set2)
            figv.update_traces(
                hovertemplate="%{x|%b/%Y}<br>%{fullData.name}: SGD %{y:,.0f}<extra></extra>")
            figv.update_yaxes(tickprefix="")
            figv.update_layout(legend_title_text="")
            st.plotly_chart(fmt(figv), use_container_width=True, config=PLOTLY_CFG)
        else:
            st.info("Registre aportes/rendimentos por produto para ver esta área.")

    # ── Rendimento: periodo + granularidade, mensal e acumulado separados ──
    # Por que mudou: o grafico antigo empilhava ~80 barras mensais desde 2019 num
    # eixo so, com a linha do acumulado num eixo secundario. Dois problemas:
    #   (a) barra de ~15px nao se le, e a variacao mensal de mercado e ruido —
    #       oitenta pontos de ruido informam menos que oito pontos anuais;
    #   (b) eixo duplo faz o cruzamento das series parecer significativo quando
    #       ele so depende da escala escolhida (Tufte/Few).
    # Agora: o usuario escolhe o periodo e a granularidade, e as duas series vao
    # em paineis empilhados compartilhando o eixo x (small multiples).
    st.markdown("#### Rendimento")

    cg1, cg2 = st.columns([1.3, 1])
    with cg1:
        periodo_op = st.radio(
            "Período", ["12 meses", "24 meses", "5 anos", "Tudo"],
            index=1, horizontal=True, key="inv_rend_periodo")
    _meses_periodo = {"12 meses": 12, "24 meses": 24, "5 anos": 60, "Tudo": None}
    _n = _meses_periodo[periodo_op]

    df_r = df_evo.sort_values("periodo").copy()
    if _n:
        df_r = df_r.tail(_n)

    # Default de granularidade pela janela: ate 24 meses o mes ainda se le;
    # acima disso, agregar e o que torna o grafico legivel.
    _gran_default = 0 if len(df_r) <= 24 else (1 if len(df_r) <= 60 else 2)
    _opcoes_gran = ["Mês", "Trimestre", "Ano"]
    # ATENCAO: st.radio com `key` ignora o `index` a partir do 2o rerun — assim
    # que a chave existe em session_state, o valor guardado manda. Sem reancorar
    # a chave na mao, quem abrisse em "24 meses" (default "Mês") e trocasse para
    # "Tudo" continuaria em "Mês", ou seja, exatamente as 85 barras ilegiveis que
    # este bloco veio eliminar. Entao: quando o PERIODO muda, reescrevemos a
    # granularidade com o default da janela nova. Escolha manual do usuario e
    # preservada enquanto ele nao trocar de periodo de novo.
    if st.session_state.get("_inv_rend_periodo_ant") != periodo_op:
        st.session_state["_inv_rend_periodo_ant"] = periodo_op
        st.session_state["inv_rend_gran"] = _opcoes_gran[_gran_default]
    with cg2:
        gran = st.radio("Ver por", _opcoes_gran,
                        index=_gran_default, horizontal=True, key="inv_rend_gran")

    if gran == "Mês":
        df_r["_bucket"] = df_r["periodo"]
        _fmt_hover = "%{x|%b/%Y}"
    elif gran == "Trimestre":
        df_r["_bucket"] = df_r["periodo"].dt.to_period("Q").dt.start_time
        _fmt_hover = "%{x|%b/%Y}"
    else:
        df_r["_bucket"] = df_r["periodo"].dt.to_period("Y").dt.start_time
        _fmt_hover = "%{x|%Y}"

    df_g = (df_r.groupby("_bucket", as_index=False)
                .agg(rendimento=("rendimento", "sum")))
    # O acumulado e recalculado DENTRO da janela: mostra o ganho do periodo
    # escolhido, nao um numero herdado de 2019 que nao se relaciona com o que
    # esta na tela.
    df_g["acum"] = df_g["rendimento"].cumsum()

    cores_rend = [C_REND if v >= 0 else C_NEG for v in df_g["rendimento"]]
    figr = make_subplots(rows=2, cols=1, shared_xaxes=True,
                         vertical_spacing=0.07, row_heights=[0.58, 0.42])
    figr.add_trace(go.Bar(
        x=df_g["_bucket"], y=df_g["rendimento"], name="Rendimento",
        marker_color=cores_rend,
        hovertemplate=_fmt_hover + "<br>Rendimento: SGD %{y:,.0f}<extra></extra>"),
        row=1, col=1)
    figr.add_trace(go.Scatter(
        x=df_g["_bucket"], y=df_g["acum"], name="Acumulado no período",
        mode="lines", line=dict(color=C_TOTAL, width=2),
        fill="tozeroy", fillcolor=C_REND_FILL,
        hovertemplate=_fmt_hover + "<br>Acumulado: SGD %{y:,.0f}<extra></extra>"),
        row=2, col=1)
    figr = fmt(figr, height=420)
    figr.update_yaxes(title_text="No período", tickprefix="", row=1, col=1)
    figr.update_yaxes(title_text="Acumulado", tickprefix="", row=2, col=1)
    figr.update_xaxes(showticklabels=False, row=1, col=1)
    st.plotly_chart(figr, use_container_width=True, config=PLOTLY_CFG)

    _rend_periodo = float(df_g["rendimento"].sum())
    st.caption(
        f"Soma do período exibido: SGD {_rend_periodo:,.0f} em "
        f"{len(df_r)} meses. As duas séries dividem o mesmo eixo de tempo — "
        "sem eixo secundário, onde o cruzamento das linhas seria arbitrário."
    )
    if total_rendimento == 0:
        st.caption("Sem rendimentos lançados ainda. Use **📈 Rendimentos e dividendos** abaixo.")

    # ── Dividendos por ano (barras) + acumulado ───────────────────────────
    df_div_ano = (df_evo.groupby("ano", as_index=False)
                        .agg(dividendo=("dividendo", "sum")))
    df_div_ano = df_div_ano[df_div_ano["dividendo"] > 0].reset_index(drop=True)
    if df_div_ano["dividendo"].sum() > 0:
        st.markdown("#### Dividendos por ano")
        df_div_ano["acum"] = df_div_ano["dividendo"].cumsum()
        figd = make_subplots(specs=[[{"secondary_y": True}]])
        figd.add_trace(go.Scatter(
            x=df_div_ano["ano"].astype(str), y=df_div_ano["dividendo"],
            name="Dividendos no ano", mode="lines+markers",
            line=dict(color=C_DIV, width=2),
            hovertemplate="<b>%{x}</b><br>Dividendos: %{y:,.0f}<extra></extra>"),
            secondary_y=False)
        figd.add_trace(go.Scatter(
            x=df_div_ano["ano"].astype(str), y=df_div_ano["acum"],
            name="Acumulado", mode="lines+markers", line=dict(color="#1B5E20", width=2),
            hovertemplate="<b>%{x}</b><br>Acumulado: SGD %{y:,.0f}<extra></extra>"),
            secondary_y=True)
        figd = fmt(figd, height=300)
        figd.update_yaxes(tickprefix="", secondary_y=False)
        figd.update_yaxes(tickprefix="", secondary_y=True, gridcolor="rgba(0,0,0,0)")
        st.plotly_chart(figd, use_container_width=True, config=PLOTLY_CFG)

    # ── Card: dividendos — media, crescimento historico e projecao ────────
    # Consolidado = soma do dividendo de TODOS os produtos por mes (sem groupby
    # por produto, sem filtro pf). O crescimento historico tinha 2 motores:
    # (a) aportes mensais regulares e (b) reinvestimento do proprio dividendo.
    # Desde jun/2026 o motor (b) foi desligado (dividendo virou caixa) mas o (a)
    # continua — por isso a projecao usa uma inclinacao MENOR que a historica.
    df_div_serie = get_serie_df()
    if not df_div_serie.empty:
        df_div_mes = (df_div_serie.groupby(["ano", "nro_mes"], as_index=False)
                                  .agg(dividendo=("dividendo", "sum")))
        df_div_mes = df_div_mes[df_div_mes["dividendo"] > 0].sort_values(["ano", "nro_mes"])
        valores_12m = df_div_mes["dividendo"].astype(float).tolist()[-12:]
        n_meses = len(valores_12m)

        if n_meses >= 3:
            media_12m = sum(valores_12m) / n_meses

            # Crescimento historico via regressao LINEAR simples (SGD/mes) — o
            # padrao nos dados e incremento fixo, nao crescimento composto.
            valores = np.array(valores_12m, dtype=float)
            xs = np.arange(len(valores))
            slope_historico, intercept = np.polyfit(xs, valores, 1)  # com reinvestimento

            # Inclinacao futura = historica menos a fatia que vinha so do
            # reinvestimento (ajustavel conforme dados reais).
            REDUCAO_SEM_REINVESTIMENTO = 3.5  # SGD/mes
            slope_futuro = max(slope_historico - REDUCAO_SEM_REINVESTIMENTO, 0.0)

            ano_atual = date.today().year
            projecao_5anos = [
                {"ano": ano_atual + a,
                 "media_mensal": media_12m + slope_futuro * (a * 12),
                 "total_anual": (media_12m + slope_futuro * (a * 12)) * 12}
                for a in range(1, 6)
            ]

            st.markdown("#### Dividendos — média, crescimento histórico e projeção")
            col_dm1, col_dm2 = st.columns(2)
            with col_dm1:
                st.metric(f"Média mensal (últimos {n_meses}m)", f"{media_12m:,.0f}")
            with col_dm2:
                st.metric("Crescimento (SGD/mês)", f"{slope_historico:+,.1f}")

            st.caption(
                "⚠️ A partir de jun/2026 os dividendos deixaram de ser reinvestidos "
                "automaticamente (viram caixa), mas os aportes mensais nos fundos "
                "continuam normalmente. A projeção abaixo usa uma inclinação menor que "
                "a histórica, descontando a fatia de crescimento que vinha só do "
                "reinvestimento do dividendo — não do aporte regular."
            )

            with st.expander("Projeção para os próximos 5 anos"):
                st.caption(
                    "Projeção linear: soma o crescimento mensal esperado (aportes "
                    "regulares, sem o reinvestimento do dividendo) sobre a média "
                    "atual. Não considera mudança no valor dos aportes nem no yield "
                    "dos fundos."
                )
                for p in projecao_5anos:
                    st.write(
                        f"**{p['ano']}**: média mensal ≈ {p['media_mensal']:,.0f}  "
                        f"·  total no ano ≈ {p['total_anual']:,.0f}"
                    )

    # ── Aportes por ano (comparador anual) ────────────────────────────────
    st.markdown("#### Aportes por ano")
    _sav = df_evo.sort_values("periodo").copy()
    _dav = _sav["aporte_acum"].diff()
    _dav.iloc[0] = _sav["aporte_acum"].iloc[0]
    _sav["_ap_mes"] = _dav.values
    df_ap_ano = _sav.groupby("ano", as_index=False).agg(aporte=("_ap_mes", "sum"))
    df_ap_ano["acum"] = df_ap_ano["aporte"].cumsum()
    if df_ap_ano["aporte"].sum() > 0:
        fig_ap = make_subplots(specs=[[{"secondary_y": True}]])
        fig_ap.add_trace(go.Bar(
            x=df_ap_ano["ano"].astype(str), y=df_ap_ano["aporte"],
            name="Aportado no ano", marker_color=C_FIXO,
            hovertemplate="<b>%{x}</b><br>Aportado: %{y:,.0f}<extra></extra>"),
            secondary_y=False)
        fig_ap.add_trace(go.Scatter(
            x=df_ap_ano["ano"].astype(str), y=df_ap_ano["acum"],
            name="Acumulado", mode="lines+markers",
            line=dict(color=C_TOTAL, width=2),
            hovertemplate="<b>%{x}</b><br>Acumulado: %{y:,.0f}<extra></extra>"),
            secondary_y=True)
        fig_ap = fmt(fig_ap, height=300)
        fig_ap.update_yaxes(tickprefix="", secondary_y=False)
        fig_ap.update_yaxes(tickprefix="", secondary_y=True, gridcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_ap, use_container_width=True, config=PLOTLY_CFG)

# ── Filtro por produto (abaixo dos graficos) ─────────────────────────────
st.selectbox("🔎 Filtrar produto", ["Todos os produtos"] + nomes_prod,
             key="inv_filtro_prod")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════
# SECAO 2 — APORTES FIXOS DO MES (registro em lote)
# ══════════════════════════════════════════════════════════════════════════
st.subheader("📦 Aportes fixos do mês")

if produtos_fixos_df.empty:
    st.info("Cadastre seus produtos de aporte fixo em **⚙️ Meus produtos de investimento** "
            "(no fim da página) para liberar o registro em lote.")
else:
    col_q, col_m = st.columns(2)
    with col_q:
        quem_lote = st.selectbox("Quem", membros, index=quem_default, key="inv_quem_lote")
    with col_m:
        mes_lote = st.selectbox("Mês", MESES_LISTA, index=mes_default, key="inv_mes_lote")
    nro_mes_lote = MESES_LISTA.index(mes_lote) + 1

    ja_registrados = set(get_aportes_fixos_registrados_no_mes(nro_mes_lote, ANO_APP))
    pendentes = []
    for _, p in produtos_fixos_df.iterrows():
        registrado = p["nome"] in ja_registrados
        col_n, col_v, col_s = st.columns([3, 2, 2])
        col_n.markdown(f"**{p['nome']}**")
        col_v.markdown(f"SGD {float(p['valor_fixo']):,.0f}/mês")
        if registrado:
            col_s.markdown(f"✅ já registrado em {mes_lote}")
        else:
            col_s.markdown("⏳ pendente")
            pendentes.append({"nome": p["nome"], "valor_fixo": float(p["valor_fixo"])})

    total_pend = sum(p["valor_fixo"] for p in pendentes)
    st.markdown("")
    if pendentes:
        if st.button(
            f"💎 Registrar {len(pendentes)} aporte(s) fixo(s) de {mes_lote} — SGD {total_pend:,.0f}",
            type="primary", use_container_width=True, key="inv_btn_lote",
        ):
            try:
                n = registrar_aportes_fixos(quem_lote, mes_lote, nro_mes_lote, ANO_APP, pendentes)
                st.session_state["inv_msg"] = (
                    f"✅ {n} aporte(s) fixo(s) de **{mes_lote}** registrado(s) "
                    f"(SGD {total_pend:,.0f}). Total aportado: "
                    f"SGD {total_aportado + total_pend:,.0f}."
                )
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao registrar aportes: {e}")
    else:
        st.success(f"Todos os aportes fixos de **{mes_lote}** já estão registrados. ✅")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════
# SECAO 3 — RENDIMENTOS E DIVIDENDOS (serie por produto/mes)
# ══════════════════════════════════════════════════════════════════════════
st.subheader("📈 Rendimentos e dividendos")
st.caption("Rendimento = quanto o produto **ganhou/perdeu** no mês (pode ser negativo). "
           "Dividendo = renda recebida no mês. Os dois alimentam os gráficos de evolução.")

if produtos_todos_df.empty:
    st.info("Cadastre um produto primeiro (em ⚙️ Meus produtos de investimento).")
else:
    tab_tav, tab_um, tab_lote = st.tabs([
        "📄 Pelo Account Value (extrato)",
        "✍️ Lançar rendimento direto",
        "📋 Importar em lote (colar)",
    ])

    # ── Pelo Account Value do extrato (jeito mais facil) ──────────────────
    # O usuario informa o Account Value do statement; o app registra o aporte
    # fixo do mes (se ainda nao houver) e calcula o rendimento por diferenca:
    #   rendimento = account_value - patrimonio_anterior - aporte
    # de modo que o patrimonio reconstruido fique igual ao Account Value.
    with tab_tav:
        st.caption("Informe o **Account Value** do extrato Manulife. O app registra o "
                   "aporte fixo do mês (se ainda não houver) e calcula sozinho o "
                   "rendimento, deixando o patrimônio igual ao extrato.")

        # Confirmacao local: aparece AQUI na aba (nao so no topo da pagina).
        if st.session_state.get("inv_tav_ok"):
            st.success(st.session_state.pop("inv_tav_ok"))

        ct1, ct2, ct3 = st.columns(3)
        with ct1:
            prod_tav = st.selectbox("Apólice / produto",
                                    produtos_todos_df["nome"].tolist(), key="inv_prod_tav")
        with ct2:
            ano_tav = st.number_input("Ano", min_value=2010, max_value=2100,
                                      value=ANO_APP, step=1, key="inv_ano_tav")
        with ct3:
            mes_tav = st.selectbox("Mês", MESES_LISTA, index=mes_default, key="inv_mes_tav")

        tav_val = st.number_input("Account Value do extrato (SGD)", min_value=0.0,
                                  value=None, step=100.0, format="%.2f",
                                  placeholder="ex: 258536.92", key="inv_tav_val")

        quem_tav = st.selectbox(
            "Quem (usado só se o aporte do mês ainda não estiver lançado)",
            membros, index=quem_default, key="inv_quem_tav")

        # valor_fixo do produto selecionado (0 se for produto variavel).
        def _valor_fixo_de(nome):
            if (not produtos_fixos_df.empty
                    and nome in produtos_fixos_df["nome"].values):
                return float(produtos_fixos_df
                             .loc[produtos_fixos_df["nome"] == nome, "valor_fixo"].iloc[0])
            return 0.0

        # Previa: mostra a conta ANTES de salvar (transparencia).
        if tav_val is not None and prod_tav:
            _nro = MESES_LISTA.index(mes_tav) + 1
            _patr_antes = get_patrimonio_produto_antes(prod_tav, int(ano_tav), _nro)
            _ap_exist = get_aporte_produto_mes(prod_tav, int(ano_tav), _nro)
            _aporte = _ap_exist if _ap_exist > 0 else _valor_fixo_de(prod_tav)
            _rend = float(tav_val) - _patr_antes - _aporte
            _origem_ap = (f"aporte já lançado SGD {_ap_exist:,.0f}" if _ap_exist > 0
                          else f"vai lançar aporte fixo SGD {_aporte:,.0f}")
            st.info(
                f"**Prévia — {prod_tav} · {mes_tav}/{int(ano_tav)}**  \n"
                f"Patrimônio anterior: SGD {_patr_antes:,.0f} · {_origem_ap} · "
                f"**rendimento calculado: SGD {_rend:,.0f}**  \n"
                f"→ patrimônio do produto fica **SGD {float(tav_val):,.0f}** (= extrato)."
            )

        if st.button("💾 Salvar pelo Account Value", type="primary",
                     use_container_width=True, key="inv_btn_tav"):
            if tav_val is None:
                st.error("Informe o Account Value do extrato.")
            else:
                try:
                    nro_tav = MESES_LISTA.index(mes_tav) + 1
                    pid_tav = prod_nome2id[prod_tav.lower()]

                    # 1) Aporte do mes: reaproveita se ja existe; senao lanca o fixo.
                    ap_exist = get_aporte_produto_mes(prod_tav, int(ano_tav), nro_tav)
                    if ap_exist > 0:
                        aporte_use = ap_exist
                    else:
                        aporte_use = _valor_fixo_de(prod_tav)
                        if aporte_use > 0:
                            registrar_aportes_fixos(
                                quem_tav, mes_tav, nro_tav, int(ano_tav),
                                [{"nome": prod_tav, "valor_fixo": aporte_use}])

                    # 2) Patrimonio anterior -> rendimento por diferenca.
                    patr_antes = get_patrimonio_produto_antes(prod_tav, int(ano_tav), nro_tav)
                    rend_calc = float(tav_val) - patr_antes - aporte_use

                    # 3) Grava rendimento (e dividendo em caixa, se informado).
                    upsert_serie(
                        pid_tav, int(ano_tav), nro_tav,
                        rendimento=rend_calc,
                    )

                    # Confirmacao na propria aba + limpa o campo de valor pro proximo mes.
                    st.session_state["inv_tav_ok"] = (
                        f"✅ {prod_tav} — {mes_tav}/{int(ano_tav)}: Account Value "
                        f"SGD {float(tav_val):,.2f} salvo "
                        f"(aporte SGD {aporte_use:,.0f} + rendimento SGD {rend_calc:,.0f}). "
                        f"Patrimônio bate com o extrato."
                    )
                    st.session_state.pop("inv_tav_val", None)
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")

    # ── Lançar um único mês ───────────────────────────────────────────────
    with tab_um:
        cs1, cs2, cs3 = st.columns(3)
        with cs1:
            prod_s = st.selectbox("Produto", produtos_todos_df["nome"].tolist(),
                                  key="inv_prod_serie")
        with cs2:
            ano_s = st.number_input("Ano", min_value=2010, max_value=2100,
                                    value=ANO_APP, step=1, key="inv_ano_serie")
        with cs3:
            mes_s = st.selectbox("Mês", MESES_LISTA, index=mes_default, key="inv_mes_serie")
        cr1, cr2 = st.columns(2)
        with cr1:
            rend_s = st.number_input("Rendimento do mês (SGD, pode ser negativo)",
                                     value=None, step=10.0, format="%.2f",
                                     placeholder="ex: 320 ou -150", key="inv_rend_serie")
        with cr2:
            div_s = st.number_input("Dividendo do mês (SGD)", min_value=0.0,
                                    value=None, step=10.0, format="%.2f",
                                    placeholder="opcional", key="inv_div_serie")

        if st.button("Salvar rendimento/dividendo", use_container_width=True,
                     key="inv_btn_serie"):
            if rend_s is None and div_s is None:
                st.error("Informe o rendimento e/ou o dividendo.")
            else:
                try:
                    upsert_serie(
                        prod_nome2id[prod_s.lower()], int(ano_s),
                        MESES_LISTA.index(mes_s) + 1,
                        rendimento=rend_s, dividendo=div_s,
                    )
                    partes = []
                    if rend_s is not None:
                        partes.append(f"rendimento SGD {rend_s:,.2f}")
                    if div_s is not None:
                        partes.append(f"dividendo SGD {div_s:,.2f}")
                    st.session_state["inv_msg"] = (
                        f"✅ {prod_s} — {mes_s}/{int(ano_s)}: " + " e ".join(partes) + " salvo."
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")

    # ── Importar em lote (colar tabela) ───────────────────────────────────
    with tab_lote:
        st.caption("Cole uma linha por mês no formato: "
                   "`produto ; ano ; mês ; rendimento ; dividendo` — "
                   "mês pode ser número (1-12) ou nome; **dividendo é opcional**. "
                   "Separe por TAB (colando de planilha), `;` ou `,`. Use ponto no decimal.")
        st.code("Manu 4k ; 2025 ; 1 ; 320 ; 901\nManu 2k ; 2025 ; 1 ; 110 ; 213",
                language="text")
        txt = st.text_area("Cole aqui", height=150, key="inv_bulk_txt",
                           placeholder="Manu 4k ; 2025 ; Janeiro ; 320 ; 901")

        def _parse_mes(tok):
            tok = tok.strip()
            if tok.isdigit():
                n = int(tok)
                return n if 1 <= n <= 12 else None
            achados = [i + 1 for i, m in enumerate(MESES_LISTA)
                       if m.lower().startswith(tok.lower()[:3])]
            return achados[0] if achados else None

        if st.button("📥 Importar linhas", use_container_width=True, key="inv_btn_bulk"):
            ok, erros = 0, []
            for i, ln in enumerate(txt.splitlines(), start=1):
                ln = ln.strip()
                if not ln:
                    continue
                parts = re.split(r"[;\t]", ln)
                if len(parts) < 4:
                    parts = [p for p in ln.split(",")]
                parts = [p.strip() for p in parts]
                if len(parts) < 4:
                    erros.append(f"linha {i}: poucos campos")
                    continue
                nome, ano_t, mes_t, rend_t = parts[0], parts[1], parts[2], parts[3]
                div_t = parts[4] if len(parts) >= 5 and parts[4] != "" else None
                pid = prod_nome2id.get(nome.lower())
                nro = _parse_mes(mes_t)
                if pid is None:
                    erros.append(f"linha {i}: produto '{nome}' não cadastrado")
                    continue
                if nro is None or not ano_t.isdigit():
                    erros.append(f"linha {i}: ano/mês inválido")
                    continue
                try:
                    rend_v = float(rend_t) if rend_t != "" else None
                    div_v = float(div_t) if div_t is not None else None
                    upsert_serie(pid, int(ano_t), nro, rendimento=rend_v, dividendo=div_v)
                    ok += 1
                except Exception as e:
                    erros.append(f"linha {i}: {e}")
            msg = f"✅ {ok} linha(s) importada(s)."
            if erros:
                msg += " ⚠️ " + str(len(erros)) + " com problema:\n- " + "\n- ".join(erros[:10])
            if ok:
                st.session_state["inv_msg"] = f"✅ {ok} linha(s) de rendimento/dividendo importada(s)."
                if erros:
                    st.warning("Algumas linhas não entraram:\n- " + "\n- ".join(erros[:10]))
                st.rerun()
            else:
                st.error(msg)

    # ── Conferencia: serie ja gravada ─────────────────────────────────────
    with st.expander("🔎 Conferir rendimentos/dividendos lançados", expanded=False):
        df_serie = get_serie_df()
        if df_serie.empty:
            st.info("Nada lançado ainda.")
        else:
            df_sh = df_serie[["produto", "ano", "mes", "rendimento", "dividendo"]].copy()
            df_sh["rendimento"] = df_sh["rendimento"].astype(float).round(0)
            df_sh["dividendo"] = df_sh["dividendo"].astype(float).round(0)
            st.dataframe(
                df_sh, use_container_width=True, hide_index=True,
                column_config={
                    "produto": "Produto", "ano": "Ano", "mes": "Mês",
                    "rendimento": st.column_config.NumberColumn("Rendimento", format="SGD %d"),
                    "dividendo": st.column_config.NumberColumn("Dividendo", format="SGD %d"),
                },
            )
            st.caption("Para corrigir um valor, re-importe a mesma linha (produto/ano/mês) "
                       "com o valor certo — ele sobrescreve.")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════
# SECAO 4 — REGISTRO AVULSO (aporte variavel ou dividendo)
# ══════════════════════════════════════════════════════════════════════════
st.subheader("✍️ Registro avulso")

tipo_avulso = st.radio("O que registrar?", ["Aporte variável", "Dividendo"],
                       horizontal=True, key="inv_tipo_avulso")

col_a, col_b, col_c = st.columns(3)
with col_a:
    quem_av = st.selectbox("Quem", membros, index=quem_default, key="inv_quem_av")
with col_b:
    mes_av = st.selectbox("Mês", MESES_LISTA, index=mes_default, key="inv_mes_av")
with col_c:
    if tipo_avulso == "Dividendo":
        # Dividendo agora vive na serie -> exige produto (de onde veio).
        prod_av = st.selectbox("Produto que pagou", produtos_todos_df["nome"].tolist()
                               if not produtos_todos_df.empty else ["—"], key="inv_prod_av_div")
    else:
        opcoes_prod = ["— (sem produto)"] + (produtos_todos_df["nome"].tolist()
                                             if not produtos_todos_df.empty else [])
        prod_av = st.selectbox("Produto/destino", opcoes_prod, key="inv_prod_av")

valor_av = st.number_input("Valor (SGD)", min_value=0.0, value=None, step=1.0,
                           format="%.2f", placeholder="Digite o valor...",
                           key="inv_valor_av")
obs_av = st.text_area("Observação (opcional)", key="inv_obs_av")

if st.button(f"Registrar {tipo_avulso.lower()}", use_container_width=True,
             key="inv_btn_avulso"):
    if not valor_av:
        st.error("Insira um valor válido!")
    elif tipo_avulso == "Dividendo" and produtos_todos_df.empty:
        st.error("Cadastre um produto antes de lançar dividendo.")
    else:
        nro_mes_av = MESES_LISTA.index(mes_av) + 1
        try:
            if tipo_avulso == "Dividendo":
                # Dividendo -> serie (modulo), NAO entra no Dashboard.
                upsert_serie(prod_nome2id[prod_av.lower()], ANO_APP, nro_mes_av,
                             dividendo=valor_av)
                st.session_state["inv_msg"] = (
                    f"✅ Dividendo de SGD {valor_av:,.2f} ({prod_av}) em **{mes_av}** registrado! "
                    f"Total de dividendos: SGD {total_dividendos + valor_av:,.0f}."
                )
            else:
                # Aporte variavel -> lancamento (entra no custo/bolo).
                item_av = None if prod_av == "— (sem produto)" else prod_av
                inserir_lancamento({
                    "data": date.today(), "mes": mes_av, "ano": ANO_APP,
                    "quem": quem_av, "tipo_geral": "Investimento",
                    "natureza": "Investimento", "categoria": CAT_APORTE_VAR,
                    "item": item_av, "valor": valor_av, "pagamento": None,
                    "observacao": obs_av or None, "nro_mes": nro_mes_av,
                })
                st.session_state["inv_msg"] = (
                    f"✅ Aporte variável de SGD {valor_av:,.2f} em **{mes_av}** registrado! "
                    f"Total aportado: SGD {total_aportado + valor_av:,.0f}."
                )
            st.rerun()
        except Exception as e:
            st.error(f"Erro ao registrar: {e}")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════
# SECAO 5 — SALDO INICIAL
# ══════════════════════════════════════════════════════════════════════════
with st.expander("🏁 Saldo inicial (quanto você já tinha investido antes do app)",
                 expanded=(saldo_inicial == 0 and total_aportado == 0)):
    if saldo_inicial > 0:
        st.caption(f"Saldo inicial registrado: **SGD {saldo_inicial:,.0f}**. "
                   "Você pode adicionar mais registros (ex.: detalhar por produto) — "
                   "ou excluir em 🗂️ Registros do ano e refazer.")
    else:
        st.caption("Se algum produto já tinha valor ANTES da data de início dos aportes, "
                   "registre aqui esse ponto de partida (ancorado em Janeiro/2026). "
                   "Para os planos Manu (aportes desde o começo), normalmente não precisa.")

    col_si1, col_si2, col_si3 = st.columns(3)
    with col_si1:
        quem_si = st.selectbox("Quem", membros, index=quem_default, key="inv_quem_si")
    with col_si2:
        opcoes_si = ["— (geral)"] + (produtos_todos_df["nome"].tolist()
                                     if not produtos_todos_df.empty else [])
        prod_si = st.selectbox("Produto (opcional)", opcoes_si, key="inv_prod_si")
    with col_si3:
        valor_si = st.number_input("Valor (SGD)", min_value=0.0, value=None,
                                   step=100.0, format="%.2f",
                                   placeholder="Ex: 50000", key="inv_valor_si")

    if st.button("🏁 Registrar saldo inicial", key="inv_btn_si",
                 use_container_width=True):
        if not valor_si:
            st.error("Insira um valor válido!")
        else:
            try:
                inserir_lancamento({
                    "data": date.today(), "mes": "Janeiro", "ano": ANO_APP,
                    "quem": quem_si, "tipo_geral": "Investimento",
                    "natureza": "Investimento", "categoria": CAT_SALDO_INICIAL,
                    "item": None if prod_si == "— (geral)" else prod_si,
                    "valor": valor_si, "pagamento": None,
                    "observacao": "Patrimônio investido antes do app",
                    "nro_mes": 1,
                })
                st.session_state["inv_msg"] = (
                    f"✅ Saldo inicial de SGD {valor_si:,.2f} registrado! "
                    f"Total aportado: SGD {total_aportado + valor_si:,.0f}."
                )
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao registrar saldo inicial: {e}")

# ══════════════════════════════════════════════════════════════════════════
# SECAO 6 — MEUS PRODUTOS DE INVESTIMENTO (config)
# ══════════════════════════════════════════════════════════════════════════
with st.expander("⚙️ Meus produtos de investimento", expanded=produtos_todos_df.empty):
    st.caption("**Fixo** = valor mensal que não muda, entra no botão de lote "
               "(ex.: Manu 4k → 4.166/mês). **Variável** = você cadastra só o "
               "nome e informa o valor quando manda dinheiro. **Início** = mês em que "
               "o plano começou a aportar (usado no histórico). Mudanças aqui só "
               "afetam os PRÓXIMOS registros — aportes lançados guardam o valor histórico.")

    df_prod_all = get_config_investimentos(somente_ativos=False)
    if not df_prod_all.empty:
        for _, p in df_prod_all.iterrows():
            pid = int(p["id"])
            eh_fixo = p["tipo"] == "fixo"
            col_n, col_t, col_v, col_d, col_at = st.columns([3, 1, 2, 2, 2])
            col_n.markdown(f"**{p['nome']}**" + ("" if p["ativo"] else " _(inativo)_"))
            col_t.caption("📌 fixo" if eh_fixo else "🌊 variável")
            if eh_fixo:
                novo_vf = col_v.number_input(
                    "Valor fixo/mês", min_value=0.0, value=float(p["valor_fixo"]),
                    step=50.0, format="%.2f", key=f"inv_vf_{pid}",
                    label_visibility="collapsed")
            else:
                col_v.caption("valor livre")
                novo_vf = None
            # Data de inicio (editavel).
            di_atual = p["data_inicio"] if pd.notna(p["data_inicio"]) else None
            nova_di = col_d.date_input(
                "Início", value=di_atual, format="DD/MM/YYYY",
                key=f"inv_di_{pid}", label_visibility="collapsed")
            with col_at:
                c_save, c_tog = st.columns(2)
                if c_save.button("💾", key=f"inv_save_{pid}", help="Salvar valor/início"):
                    campos = {"data_inicio": nova_di}
                    if eh_fixo:
                        campos["valor_fixo"] = novo_vf
                    update_config_investimento(pid, campos)
                    st.session_state["inv_msg"] = f"✅ **{p['nome']}** atualizado."
                    st.rerun()
                rotulo_tog = "🚫" if p["ativo"] else "♻️"
                ajuda_tog = ("Desativar (sai das listas, histórico preservado)"
                             if p["ativo"] else "Reativar produto")
                if c_tog.button(rotulo_tog, key=f"inv_tog_{pid}", help=ajuda_tog):
                    update_config_investimento(pid, {"ativo": not bool(p["ativo"])})
                    st.session_state["inv_msg"] = (
                        f"✅ **{p['nome']}** {'desativado' if p['ativo'] else 'reativado'}."
                    )
                    st.rerun()
        st.divider()

    st.markdown("**➕ Novo produto**")
    tipo_novo = st.radio("Tipo do produto", ["Fixo (valor mensal)", "Variável (valor livre)"],
                         horizontal=True, key="inv_tipo_novo")
    eh_fixo_novo = tipo_novo.startswith("Fixo")
    col_nn, col_nv, col_nd, col_nb = st.columns([3, 2, 2, 2])
    nome_novo = col_nn.text_input("Nome", placeholder="Ex: Manu 4k",
                                  key="inv_nome_novo", label_visibility="collapsed")
    if eh_fixo_novo:
        valor_novo = col_nv.number_input(
            "Valor fixo mensal", min_value=0.0, value=None, step=50.0,
            format="%.2f", placeholder="4166.00",
            key="inv_valor_novo", label_visibility="collapsed")
    else:
        col_nv.caption("sem valor fixo")
        valor_novo = None
    di_novo = col_nd.date_input("Início", value=None, format="DD/MM/YYYY",
                                key="inv_di_novo", label_visibility="collapsed")
    if col_nb.button("➕ Adicionar", key="inv_btn_add_prod", use_container_width=True):
        nomes_existentes = df_prod_all["nome"].str.lower().tolist() \
            if not df_prod_all.empty else []
        if not nome_novo or not nome_novo.strip():
            st.error("Dê um nome ao produto.")
        elif eh_fixo_novo and valor_novo is None:
            st.error("Insira o valor fixo mensal.")
        elif nome_novo.strip().lower() in nomes_existentes:
            st.error(f"Já existe um produto chamado **{nome_novo.strip()}**.")
        else:
            try:
                add_config_investimento(
                    nome_novo, valor_novo,
                    tipo="fixo" if eh_fixo_novo else "variavel",
                    data_inicio=di_novo,
                )
                detalhe = (f" (SGD {valor_novo:,.2f}/mês)" if eh_fixo_novo else " (variável)")
                st.session_state["inv_msg"] = \
                    f"✅ Produto **{nome_novo.strip()}** criado{detalhe}."
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao criar produto: {e}")

# ══════════════════════════════════════════════════════════════════════════
# SECAO 7 — REGISTROS DO ANO (aportes / saldo inicial — visualizar / excluir)
# ══════════════════════════════════════════════════════════════════════════
with st.expander("🗂️ Registros do ano (aportes e saldo inicial)", expanded=False):
    df_reg = get_registros_investimentos(ANO_APP)
    if df_reg.empty:
        st.info("Nenhum aporte/saldo inicial registrado neste ano.")
    else:
        st.caption("Errou um aporte? Selecione, exclua e registre de novo. "
                   "(Rendimentos e dividendos se corrigem na seção 📈 acima.)")
        df_show = df_reg[["id", "mes", "quem", "categoria", "item",
                          "valor", "observacao"]].copy()
        df_show["valor"] = df_show["valor"].astype(float).round(0).astype(int)
        df_show.insert(0, "Selecionar", False)

        edited = st.data_editor(
            df_show, use_container_width=True, hide_index=True,
            disabled=["id", "mes", "quem", "categoria", "item", "valor", "observacao"],
            column_config={
                "Selecionar": st.column_config.CheckboxColumn("✔", width="small"),
                "id":         st.column_config.NumberColumn("ID", width="small"),
                "mes":        st.column_config.TextColumn("Mês", width="small"),
                "quem":       st.column_config.TextColumn("Quem", width="small"),
                "categoria":  st.column_config.TextColumn("Categoria"),
                "item":       st.column_config.TextColumn("Produto"),
                "valor":      st.column_config.NumberColumn("Valor", format="SGD %d"),
                "observacao": st.column_config.TextColumn("Obs"),
            },
            key="inv_editor_reg",
        )
        ids_sel = edited[edited["Selecionar"] == True]["id"].tolist()
        n_sel = len(ids_sel)

        if st.button(f"🗑️ Remover ({n_sel})", disabled=n_sel == 0, key="inv_btn_del"):
            st.session_state["inv_confirma_del"] = True

        if st.session_state.get("inv_confirma_del") and n_sel > 0:
            st.warning(f"Remover {n_sel} registro(s)? Esta ação não pode ser desfeita.")
            c_sim, c_nao = st.columns(2)
            if c_sim.button("Sim, remover", key="inv_btn_del_sim", use_container_width=True):
                delete_lancamentos(ids_sel)
                st.session_state["inv_confirma_del"] = False
                st.session_state["inv_msg"] = f"✅ {n_sel} registro(s) removido(s)."
                st.rerun()
            if c_nao.button("Cancelar", key="inv_btn_del_nao", use_container_width=True):
                st.session_state["inv_confirma_del"] = False
                st.rerun()
