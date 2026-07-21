"""
Ricardo (irmao do Vinicius) — modulo isolado do App 10M.

Duas abas:
  1. Renda Passiva — proventos (FII/Acoes) + rendimento (Renda Fixa) mes a mes.
  2. Patrimonio    — net worth real mes a mes + projecao ate R$ 1.000.000.

IMPORTANTE: este modulo NAO usa household_id e NAO entra em nenhum calculo
de patrimonio/net worth/meta 10M do Vinicius. E 100% isolado — dados de uma
pessoa diferente (o irmao), so compartilhando o mesmo app. Moeda: BRL.

Tabelas:
  - renda_passiva_irmao (ano, nro_mes, categoria, valor_investido, provento, rendimento)
  - patrimonio_irmao    (ano, nro_mes, aporte, patrimonio_final, inflacao_mensal)

O juro/rendimento do patrimonio e DERIVADO (nao armazenado):
  juro = patrimonio_final - patrimonio_final_anterior - aporte
(mesmo padrao TAV usado no resto do app).
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.db import query_df, execute
from core.styles import aplicar_estilos

st.set_page_config(page_title="Ricardo · App 10M", page_icon="👤", layout="wide")
aplicar_estilos()

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
         "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
CATEGORIAS = ["Ações", "FIIs", "Renda Fixa"]
VERDE = "#059669"
AZUL = "#2563EB"
CINZA = "#94A3B8"

st.title("👤 Ricardo")
st.caption(
    "Módulo isolado (irmão) — renda passiva e patrimônio. Em R$. "
    "Não entra no patrimônio nem na meta dos 10M."
)

aba_renda, aba_patrimonio = st.tabs(["🌱 Renda Passiva", "📈 Patrimônio"])

# ══════════════════════════════════════════════════════════════════════════
# ABA 1 — RENDA PASSIVA
# ══════════════════════════════════════════════════════════════════════════
with aba_renda:
    df = query_df(
        "SELECT ano, nro_mes, categoria, valor_investido, provento, rendimento, "
        "COALESCE(confiavel, true) AS confiavel "
        "FROM renda_passiva_irmao ORDER BY ano, nro_mes, categoria"
    )

    if not df.empty:
        df["periodo"] = pd.to_datetime(
            df["ano"].astype(str) + "-" + df["nro_mes"].astype(str) + "-01"
        )
        df["valor"] = df["provento"].fillna(0) + df["rendimento"].fillna(0)
        df["renda_passiva"] = df["valor"]
        df["t"] = df["ano"] * 12 + df["nro_mes"]
        df_mes = (df.groupby("periodo", as_index=False)
                    .agg(renda_passiva=("renda_passiva", "sum"),
                         capital_investido=("valor_investido", "sum"))
                    .sort_values("periodo"))
        df_mes_full = (df.groupby(["periodo"], as_index=False)
                         .agg(t=("t", "max")))
    else:
        df_mes = pd.DataFrame(columns=["periodo", "renda_passiva", "capital_investido"])
        df_mes_full = pd.DataFrame(columns=["periodo", "t"])

    st.markdown("#### Registrar mês")
    with st.form("form_renda_passiva", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            ano_sel = st.number_input("Ano", min_value=2020, max_value=2100,
                                       value=2026, step=1, key="rp_ano")
            mes_sel = st.selectbox("Mês", MESES, key="rp_mes")
        with c2:
            cat_sel = st.selectbox("Categoria", CATEGORIAS, key="rp_cat")
            valor_investido = st.number_input(
                "Capital investido no mês", min_value=0.0, format="%.2f",
                key="rp_valor_investido")
        with c3:
            provento = st.number_input(
                "Provento recebido (FII/Ações)", min_value=0.0, format="%.2f",
                key="rp_provento")
            rendimento = st.number_input(
                "Rendimento gerado (Renda Fixa)", min_value=0.0, format="%.2f",
                key="rp_rendimento")

        if st.form_submit_button("Salvar", use_container_width=True):
            nro_mes = MESES.index(mes_sel) + 1
            execute(
                "INSERT INTO renda_passiva_irmao "
                "(ano, nro_mes, categoria, valor_investido, provento, rendimento) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (ano, nro_mes, categoria) DO UPDATE SET "
                "valor_investido = EXCLUDED.valor_investido, "
                "provento = EXCLUDED.provento, "
                "rendimento = EXCLUDED.rendimento",
                [ano_sel, nro_mes, cat_sel, valor_investido, provento, rendimento])
            st.success(f"Salvo: {mes_sel}/{ano_sel} — {cat_sel}")
            st.rerun()

    st.markdown("---")

    if df_mes.empty:
        st.info("Ainda não há dados de renda passiva. Use o formulário acima.")
    else:
        st.markdown("#### Evolução da renda passiva")
        # Empilhado por categoria (Acoes, FIIs, Renda Fixa) para ver cada fonte.
        cores_cat = {"Ações": "#2563EB", "FIIs": VERDE, "Renda Fixa": "#F59E0B"}
        df["renda_cat"] = df["provento"].fillna(0) + df["rendimento"].fillna(0)
        fig = go.Figure()
        for cat in ["Ações", "FIIs", "Renda Fixa"]:
            sub = (df[df["categoria"] == cat]
                   .groupby("periodo", as_index=False)["renda_cat"].sum())
            if not sub.empty and sub["renda_cat"].sum() > 0:
                fig.add_trace(go.Bar(
                    x=sub["periodo"], y=sub["renda_cat"], name=cat,
                    marker_color=cores_cat.get(cat, CINZA),
                    hovertemplate=f"<b>%{{x|%b/%Y}}</b><br>{cat}: %{{y:,.0f}}<extra></extra>"))
        fig.update_layout(barmode="stack", height=340,
                          margin=dict(l=0, r=0, t=12, b=8),
                          plot_bgcolor="white", paper_bgcolor="white",
                          font=dict(family="Segoe UI", size=12), hovermode="x unified",
                          legend=dict(orientation="h", y=-0.2))
        fig.update_yaxes(gridcolor="#E0E7EF", zeroline=False)
        fig.update_xaxes(gridcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True,
                        config={"displayModeBar": False, "displaylogo": False})

        valores = df_mes["renda_passiva"].values.astype(float)
        n = len(valores)
        if n >= 3:
            slope, intercept = np.polyfit(np.arange(n), valores, 1)
        else:
            slope, intercept = 0.0, (valores[-1] if n > 0 else 0.0)
        renda_atual = valores[-1] if n > 0 else 0.0
        capital_atual = df_mes["capital_investido"].iloc[-1] if n > 0 else 0.0

        col1, col2, col3 = st.columns(3)
        col1.metric("Renda passiva atual (último mês)", f"R$ {renda_atual:,.0f}")
        col2.metric("Tendência (R$/mês)", f"{slope:+,.2f}")
        col3.metric("Capital investido (último mês)", f"R$ {capital_atual:,.0f}")
        st.caption("Tendência por regressão linear simples sobre o histórico disponível.")

        # ── Projecao por categoria (cada fonte tem natureza diferente) ────────
        # FIIs: pilar estavel/crescente -> tendencia sobre historico recente.
        # Acoes: esporadico -> media recorrente (sem outlier), projecao flat.
        # Renda Fixa: teve ruptura do Banco Master -> usa so meses confiaveis,
        #   e a projecao forward parte do regime ATUAL (ultimos confiaveis).
        # A flag "confiavel" (do banco) exclui a janela do Master dos calculos,
        # mas o grafico acima continua mostrando todos os valores reais.
        def _sem_outlier(v):
            if len(v) < 4:
                return v
            med = np.median(v)
            mad = np.median(np.abs(v - med))
            if mad == 0:
                return v
            return v[v <= med + 3 * 1.4826 * mad]

        base_t = int(df_mes_full["t"].max())  # ultimo mes real (ano*12+mes)

        def _proj_categoria(cat):
            sub = df[(df["categoria"] == cat) & (df["confiavel"])].sort_values("t")
            if sub.empty:
                return (lambda t: 0.0), 0.0
            v = sub["valor"].values.astype(float)
            t = sub["t"].values.astype(float)
            if cat == "Ações":
                m = float(_sem_outlier(v).mean())
                return (lambda tt: m), 0.0
            if cat == "Renda Fixa":
                # regime atual: ultimos 4 meses confiaveis
                vr = v[-4:]
                tr = t[-4:]
            else:  # FIIs: historico de 2026 (regime atual, estavel)
                mask2026 = t >= 2026 * 12 + 1
                vr = v[mask2026] if mask2026.sum() >= 2 else v
                tr = t[mask2026] if mask2026.sum() >= 2 else t
            if len(vr) >= 2:
                sl, it = np.polyfit(tr, vr, 1)
            else:
                sl, it = 0.0, (vr[-1] if len(vr) else 0.0)
            return (lambda tt: it + sl * tt), float(sl)

        f_ac, _ = _proj_categoria("Ações")
        f_fi, sl_fi = _proj_categoria("FIIs")
        f_rf, sl_rf = _proj_categoria("Renda Fixa")

        st.markdown("#### Projeção de renda passiva (por fonte)")
        st.caption(
            "Cada fonte é projetada conforme sua natureza: FIIs (estável), "
            "Ações (média recorrente, sem picos) e Renda Fixa (regime atual "
            "pós-Banco Master). Meses atípicos marcados como não-confiáveis "
            "ficam fora dos cálculos, mas seguem no gráfico acima."
        )
        linhas_proj = []
        for lab, fwd in [("+3 meses", 3), ("+6 meses", 6), ("+12 meses", 12)]:
            t = base_t + fwd
            ac, fi, rf_ = f_ac(t), f_fi(t), f_rf(t)
            linhas_proj.append((lab, ac, fi, rf_, ac + fi + rf_))

        cols = st.columns(3)
        for c, (lab, ac, fi, rf_, tot) in zip(cols, linhas_proj):
            c.metric(f"Renda passiva {lab}", f"R$ {tot:,.0f}",
                     help=f"Ações ~{ac:,.0f} · FIIs ~{fi:,.0f} · Renda Fixa ~{rf_:,.0f}")
        st.caption(
            f"Tendências atuais: FIIs {sl_fi:+.0f}/mês · Renda Fixa "
            f"{sl_rf:+.0f}/mês (reconstruindo pós-Master) · Ações estável "
            "(média recorrente)."
        )

# ══════════════════════════════════════════════════════════════════════════
# ABA 2 — PATRIMONIO
# ══════════════════════════════════════════════════════════════════════════
with aba_patrimonio:
    dfp = query_df(
        "SELECT ano, nro_mes, aporte, patrimonio_final, inflacao_mensal "
        "FROM patrimonio_irmao ORDER BY ano, nro_mes"
    )

    st.markdown("#### Registrar mês (dados reais medidos)")
    with st.form("form_patrimonio", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            ano_p = st.number_input("Ano", min_value=2020, max_value=2100,
                                    value=2026, step=1, key="pat_ano")
            mes_p = st.selectbox("Mês", MESES, key="pat_mes")
            aporte_p = st.number_input(
                "Aporte do mês (pode ser negativo se retirou)",
                value=0.0, format="%.2f", key="pat_aporte")
        with c2:
            patf_p = st.number_input(
                "Patrimônio final medido (saldo real no fim do mês)",
                min_value=0.0, format="%.2f", key="pat_final")
            infl_p = st.number_input(
                "Inflação do mês (%) — ex.: 0.375 para 0,375%",
                min_value=0.0, format="%.4f", key="pat_infl")

        if st.form_submit_button("Salvar", use_container_width=True):
            nro_mes = MESES.index(mes_p) + 1
            execute(
                "INSERT INTO patrimonio_irmao "
                "(ano, nro_mes, aporte, patrimonio_final, inflacao_mensal) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (ano, nro_mes) DO UPDATE SET "
                "aporte = EXCLUDED.aporte, "
                "patrimonio_final = EXCLUDED.patrimonio_final, "
                "inflacao_mensal = EXCLUDED.inflacao_mensal",
                [ano_p, nro_mes, aporte_p, patf_p, infl_p / 100.0])
            st.success(f"Salvo: {mes_p}/{ano_p} — patrimônio R$ {patf_p:,.0f}")
            st.rerun()

    st.markdown("---")

    if dfp.empty or len(dfp) < 2:
        st.info("Registre pelo menos 2 meses para ver evolução e projeção.")
        st.stop()

    dfp = dfp.sort_values(["ano", "nro_mes"]).reset_index(drop=True)
    dfp["periodo"] = pd.to_datetime(
        dfp["ano"].astype(str) + "-" + dfp["nro_mes"].astype(str) + "-01")
    # Juro derivado (padrao TAV): patrimonio_final - anterior - aporte
    dfp["pat_anterior"] = dfp["patrimonio_final"].shift(1)
    dfp["juro"] = dfp["patrimonio_final"] - dfp["pat_anterior"] - dfp["aporte"]
    dfp.loc[0, "juro"] = 0.0

    # Valor ajustado pela inflacao (metodo composto, rigoroso): divide pelo fator
    dfp["fator_infl"] = (1 + dfp["inflacao_mensal"].fillna(0)).cumprod()
    dfp["ajustado_composto"] = dfp["patrimonio_final"] / dfp["fator_infl"]

    ultimo = dfp.iloc[-1]
    pat_atual = float(ultimo["patrimonio_final"])
    ajustado_atual = float(ultimo["ajustado_composto"])

    st.markdown("#### Evolução do patrimônio")
    figp = go.Figure()
    figp.add_trace(go.Scatter(
        x=dfp["periodo"], y=dfp["patrimonio_final"], name="Patrimônio (nominal)",
        mode="lines+markers", line=dict(color=AZUL, width=2),
        hovertemplate="<b>%{x|%b/%Y}</b><br>Nominal: R$ %{y:,.0f}<extra></extra>"))
    figp.add_trace(go.Scatter(
        x=dfp["periodo"], y=dfp["ajustado_composto"],
        name="Ajustado pela inflação", mode="lines+markers",
        line=dict(color=CINZA, width=2, dash="dot"),
        hovertemplate="<b>%{x|%b/%Y}</b><br>Real: R$ %{y:,.0f}<extra></extra>"))
    figp.update_layout(height=340, margin=dict(l=0, r=0, t=12, b=8),
                       plot_bgcolor="white", paper_bgcolor="white",
                       font=dict(family="Segoe UI", size=12), hovermode="x unified",
                       legend=dict(orientation="h", y=-0.2))
    figp.update_yaxes(gridcolor="#E0E7EF", zeroline=False)
    figp.update_xaxes(gridcolor="rgba(0,0,0,0)")
    st.plotly_chart(figp, use_container_width=True,
                    config={"displayModeBar": False, "displaylogo": False})

    # Premissas re-ancoradas nos dados reais
    taxas = (dfp["juro"] / dfp["pat_anterior"]).replace([np.inf, -np.inf], np.nan).dropna()
    taxa_media = float(taxas.mean()) if not taxas.empty else 0.0
    infls = dfp[dfp["inflacao_mensal"] > 0]["inflacao_mensal"]
    infl_media = float(infls.mean()) if not infls.empty else 0.0
    aportes_norm = dfp["aporte"].iloc[1:]
    aportes_norm = aportes_norm[aportes_norm.abs() < 15000]
    aporte_ref = float(np.median(aportes_norm)) if not aportes_norm.empty else 0.0

    col1, col2, col3 = st.columns(3)
    col1.metric("Patrimônio atual (nominal)", f"R$ {pat_atual:,.0f}")
    col2.metric("Valor real (ajust. inflação)", f"R$ {ajustado_atual:,.0f}")
    col3.metric("Retorno médio mensal", f"{taxa_media*100:.2f}%")

    st.markdown("#### Projeção até R$ 1.000.000")
    st.caption(
        "Ancora no último mês real e projeta para frente com as médias "
        "observadas (retorno e inflação) e um aporte de referência. À medida "
        "que você registra novos meses reais, as premissas se atualizam e a "
        "data se recalcula."
    )

    alvo = st.number_input("Valor-alvo (R$)", min_value=100000.0, value=1_000_000.0,
                           step=50000.0, format="%.0f", key="pat_alvo")
    aporte_proj = st.number_input(
        "Aporte mensal assumido na projeção (R$)", value=round(aporte_ref, 2),
        step=100.0, format="%.2f", key="pat_aporte_proj")

    def projeta(pat0, aporte, juro_m, infl_m, metodo, alvo, gap0=0.0, limite=800):
        ano, mes = int(ultimo["ano"]), int(ultimo["nro_mes"])
        pat = pat0
        fator = 1.0
        soma = gap0
        for _ in range(limite):
            mes += 1
            if mes > 12:
                mes = 1
                ano += 1
            pat = (pat + aporte) * (1 + juro_m)
            if metodo == "linear":
                soma += pat * infl_m
                aj = pat - soma
            else:
                fator *= (1 + infl_m)
                aj = pat / fator
            if aj >= alvo:
                return f"{MESES[mes-1][:3]}/{ano}", ano + mes / 12.0
        return "não atinge em 60+ anos", None

    if taxa_media <= 0:
        st.warning("Retorno médio observado não é positivo — não é possível "
                   "projetar. Registre mais meses de dados reais.")
    else:
        gap_inicial = pat_atual - ajustado_atual  # desconto de inflacao ja acumulado
        data_comp, _ = projeta(pat_atual, aporte_proj, taxa_media, infl_media,
                                "composto", alvo)
        data_lin, _ = projeta(pat_atual, aporte_proj, taxa_media, infl_media,
                               "linear", alvo, gap0=gap_inicial)

        cA, cB = st.columns(2)
        cA.metric("Chega ao alvo (composto, rigoroso)", data_comp)
        cB.metric("Chega ao alvo (linear, planilha)", data_lin)
        st.caption(
            f"Premissas atuais: retorno **{taxa_media*100:.2f}%/mês** "
            f"(~{((1+taxa_media)**12-1)*100:.1f}%/ano), inflação "
            f"**{infl_media*100:.3f}%/mês**, aporte **R$ {aporte_proj:,.0f}/mês**. "
            "O método composto (dividir pelo fator de inflação acumulado) é o "
            "financeiramente correto; o linear reproduz o método da sua planilha, "
            "que subestima a inflação a longo prazo."
        )
