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
from core.auth import restrito_a_renda_passiva

st.set_page_config(page_title="Ricardo · App 10M", page_icon="👤", layout="wide")
aplicar_estilos()

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
         "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
CATEGORIAS = ["Ações", "FIIs", "Renda Fixa"]
VERDE = "#059669"
AZUL = "#2563EB"
CINZA = "#94A3B8"

# A MESMA pagina serve os dois lados, com cabecalho e abas diferentes:
#   - Vinicius: "👤 Ricardo", modulo do irmao, com as duas abas.
#   - Ricardo:  "🌱 Renda Passiva", sem citar o proprio nome (e a pagina DELE)
#     e sem a aba de Patrimonio, que ele nao usa.
restrito = restrito_a_renda_passiva()

if restrito:
    st.title("🌱 Renda Passiva")
    st.caption("Proventos e rendimentos por categoria, em R$.")
    # Um unico tab sozinho fica estranho na UI, entao aqui o conteudo vai num
    # container simples em vez de st.tabs().
    aba_renda = st.container()
else:
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
                    .agg(renda_passiva=("renda_passiva", "sum"))
                    .sort_values("periodo"))
        df_mes_full = (df.groupby(["periodo"], as_index=False)
                         .agg(t=("t", "max")))
    else:
        df_mes = pd.DataFrame(columns=["periodo", "renda_passiva"])
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
            provento = st.number_input(
                "Provento recebido (FII/Ações)", min_value=0.0, format="%.2f",
                key="rp_provento")
        with c3:
            rendimento = st.number_input(
                "Rendimento gerado (Renda Fixa)", min_value=0.0, format="%.2f",
                key="rp_rendimento")

        if st.form_submit_button("Salvar", use_container_width=True):
            nro_mes = MESES.index(mes_sel) + 1
            # valor_investido NAO e mais escrito por este formulario (esta pagina
            # e de RENDA PASSIVA, nao de aporte/investimento). O ON CONFLICT so
            # atualiza provento/rendimento, entao um valor_investido historico
            # de algum mes antigo fica intocado — nunca mais e zerado por um
            # submit que nem mexia nele (foi exatamente o que aconteceu em
            # jul/2026: registrar o capital investido apagou o rendimento).
            execute(
                "INSERT INTO renda_passiva_irmao "
                "(ano, nro_mes, categoria, provento, rendimento) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (ano, nro_mes, categoria) DO UPDATE SET "
                "provento = EXCLUDED.provento, "
                "rendimento = EXCLUDED.rendimento",
                [ano_sel, nro_mes, cat_sel, provento, rendimento])
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

        col1, col2 = st.columns(2)
        col1.metric("Renda passiva atual (último mês)", f"R$ {renda_atual:,.0f}")
        col2.metric("Tendência (R$/mês)", f"{slope:+,.2f}")
        st.caption("Tendência por regressão linear simples sobre o histórico disponível.")

        # ── Projecao por fonte: patamar + crescimento medido ──────────────────
        # O problema: Acoes e FIIs pagam em CICLO ANUAL. Dez/25 teve Acoes 897 e
        # FIIs 512, contra ~200 e ~350 nos vizinhos; marco paga forte em Acoes
        # (584 em 2025, 672 em 2026). Numa serie assim, regressao direta mede a
        # FASE DO CICLO, nao crescimento: em Acoes a inclinacao da +1/mes em 18
        # meses e -17/mes em 12, so mudando onde a janela corta.
        #
        # A solucao e a MEDIA MOVEL DE 12 MESES. Cada janela cobre um ciclo
        # completo de distribuicao, entao a sazonalidade se cancela dentro dela
        # e o que sobra e so crescimento. Ai basta medir o quanto essa media
        # sobe de janela para janela:
        #
        #   Acoes: 231,0 -> 237,4 -> 244,7 -> 246,1 -> 259,0 -> 253,8 -> 252,4
        #          => +3,98/mes  (mesmo com jul/26 tendo pago so 4,77)
        #   FIIs : 283,6 -> 304,0 -> 317,6 -> 329,7 -> 342,3 -> 353,4 -> 364,5 -> 370,7
        #          => +12,28/mes
        #
        # Assim o crescimento vem do DADO, sem arbitrar yield e sem projetar o
        # aporte: o aporte esta implicito, e ele que fez a media movel subir.
        # Medimos o resultado em vez de estimar a causa.
        #
        # Renda Fixa fica FLAT: so ha 5 meses confiaveis (o resto e o periodo do
        # Banco Master) e dois deles sao a recomposicao pos-evento — a reta
        # bruta daria +28/mes, que extrapolada viraria 616/mes em um ano sem
        # nada que sustente. Com serie curta e sem sazonalidade, o nivel dos
        # ultimos 3 meses ja e a melhor estimativa.
        base_t = int(df_mes_full["t"].max())  # ultimo mes real (ano*12+mes)
        JANELA_ANUAL = 12     # Acoes e FIIs: ciclo completo de distribuicao
        JANELA_CURTA = 3      # Renda Fixa: regime atual, sem sazonalidade
        MIN_JANELAS = 3       # media movel precisa de ao menos 3 pontos p/ reta

        def _serie(cat):
            sub = df[(df["categoria"] == cat) & (df["confiavel"])].sort_values("t")
            return sub["valor"].values.astype(float)

        def _nivel_e_crescimento(cat):
            """
            Devolve (nivel_mensal, crescimento_por_mes, n_meses_da_base).

            Nivel: media dos ultimos 12 meses (ciclo anual) ou dos ultimos 3
            (Renda Fixa, sem ciclo).
            Crescimento: inclinacao da MEDIA MOVEL de 12 meses — zero quando nao
            ha janelas suficientes, ou quando a fonte e Renda Fixa. Crescimento
            negativo e truncado em zero: nao se projeta queda de renda passiva.
            """
            v = _serie(cat)
            if v.size == 0:
                return 0.0, 0.0, 0
            if cat == "Renda Fixa":
                base = v[-JANELA_CURTA:]
                return float(base.mean()), 0.0, len(base)
            base = v[-JANELA_ANUAL:]
            nivel = float(base.mean())
            if v.size < JANELA_ANUAL + MIN_JANELAS - 1:
                return nivel, 0.0, len(base)
            mm = np.array([v[i - JANELA_ANUAL:i].mean()
                           for i in range(JANELA_ANUAL, v.size + 1)])
            sl, _ = np.polyfit(np.arange(mm.size, dtype=float), mm, 1)
            return nivel, max(0.0, float(sl)), len(base)

        n_ac, g_ac, m_ac = _nivel_e_crescimento("Ações")
        n_fi, g_fi, m_fi = _nivel_e_crescimento("FIIs")
        n_rf, g_rf, m_rf = _nivel_e_crescimento("Renda Fixa")
        piso_total = n_ac + n_fi + n_rf
        cresc_mes = g_ac + g_fi + g_rf
        pct_ano = (cresc_mes * 12 / piso_total * 100) if piso_total else 0.0

        st.markdown("#### Para onde a renda passiva está indo")
        st.caption(
            "**Piso** = o que a carteira paga hoje, na média do ciclo anual de "
            "distribuições. **Crescimento** = quanto essa média vem subindo, "
            "medido pela média móvel de 12 meses — cada janela cobre um ciclo "
            "inteiro, então a sazonalidade se cancela e sobra só a tendência "
            "real. Nada de rendimento estimado: o número sai do próprio "
            "histórico. Renda Fixa entra sem crescimento (série curta, e a alta "
            "recente é recomposição pós-Banco Master)."
        )
        cols = st.columns(3)
        for c, (lab, fwd) in zip(cols, [("+3 meses", 3), ("+6 meses", 6),
                                        ("+12 meses", 12)]):
            valor = piso_total + cresc_mes * fwd
            c.metric(f"Renda passiva {lab}", f"R$ {valor:,.0f}",
                     delta=(f"+{valor - piso_total:,.0f}" if cresc_mes > 0 else None),
                     help=f"Piso R$ {piso_total:,.0f} · "
                          f"Ações ~{n_ac:,.0f} · FIIs ~{n_fi:,.0f} · "
                          f"Renda Fixa ~{n_rf:,.0f}")
        st.caption(
            f"Piso **R$ {piso_total:,.0f}/mês** · crescimento medido "
            f"**+R$ {cresc_mes:,.0f}/mês** ({pct_ano:,.0f}% ao ano) — "
            f"Ações +{g_ac:,.0f} · FIIs +{g_fi:,.0f} · Renda Fixa estável. "
            "O piso é maior que alguns meses individuais porque o ciclo anual "
            "concentra pagamentos: julho é fraco em Ações, dezembro é forte."
        )

        # ── Calculadora: quanto tempo ate uma renda passiva alvo ──────────────
        # O prazo sai do crescimento MEDIDO na media movel, nao de um yield
        # arbitrado nem de projecao de aporte. Se o crescimento medido for zero,
        # a calculadora diz isso em vez de inventar um numero que feche a conta.
        st.markdown("#### Quanto tempo até uma renda passiva alvo?")
        meta_rp = st.number_input(
            "Renda passiva mensal alvo (R$)", min_value=0.0, value=2000.0,
            step=100.0, format="%.2f", key="rp_meta_total")

        if meta_rp <= piso_total:
            st.success(
                f"Meta já atingida — o piso atual é R$ {piso_total:,.0f}/mês.")
        elif cresc_mes <= 0:
            st.warning(
                f"Faltam R$ {meta_rp - piso_total:,.0f}/mês, e no momento não há "
                "crescimento mensurável no histórico — sem aporte novo, o "
                "patamar não se move.")
        else:
            falta = meta_rp - piso_total
            meses = falta / cresc_mes
            c_m1, c_m2 = st.columns(2)
            c_m1.metric("No ritmo atual", f"{meses / 12:,.1f} anos",
                        help=f"{meses:,.0f} meses a +R$ {cresc_mes:,.0f}/mês")
            c_m2.metric("Faltam por mês", f"R$ {falta:,.0f}",
                        help=f"Piso hoje R$ {piso_total:,.0f} · "
                             f"alvo R$ {meta_rp:,.0f}")
            st.caption(
                f"No ritmo medido de +R$ {cresc_mes:,.0f}/mês, a meta de "
                f"R$ {meta_rp:,.0f} chega em **{meses / 12:,.1f} anos**. "
                "Esse ritmo é consequência dos aportes: aportar mais acelera, "
                "parar de aportar congela o patamar onde está."
            )

# ══════════════════════════════════════════════════════════════════════════
# ABA 2 — PATRIMONIO (oculta para login restrito, ex.: Ricardo)
# ══════════════════════════════════════════════════════════════════════════
if not restrito:
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
