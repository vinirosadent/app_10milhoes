import streamlit as st
import plotly.graph_objects as go
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from core.database import (
    get_resumo_mensal, get_gastos_por_categoria, get_saldo_acumulado,
    get_orcamento_vs_realizado, get_gastos_mensais_por_pessoa,
    # Etapa 3 - multi-usuario: lista de pessoas para o filtro vem do household ativo.
    get_membros_household,
)
# Camada de BI compartilhada (cores, meses, formatacao, tema e builders de grafico).
from core import charts as ch

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")
st.title("📊 Dashboard Financeiro")

# ── Sidebar ───────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🔍 Filtros")
    # Lista de pessoas dinamica conforme o household — Admin ve Vin+Jul; Ladroes ve Ricardo+Josi.
    membros_filtro = ["Todos"] + get_membros_household()
    ano_sel  = st.selectbox("Ano",      [2026],                            key="db_ano")
    quem_sel = st.selectbox("Pessoa",   membros_filtro,                    key="db_quem")
    nat_sel  = st.selectbox("Natureza", ["Pessoal", "Profissional", "Todos"], key="db_nat")

quem_param = None if quem_sel == "Todos" else quem_sel
nat_param  = None if nat_sel  == "Todos" else nat_sel

# Modulo de investimentos ativo? (flag por household, cacheada pelo app.py).
# Controla a exibicao da serie/metrica de investimentos — para households sem
# o modulo (Ladroes) o Dashboard fica identico ao que era antes.
tem_inv = st.session_state.get("investimentos_ativo", False)

# ── Dados base ────────────────────────────────────────────────────────────
df_mensal     = get_resumo_mensal(ano_sel, quem_param, nat_param)
df_saldo_ac   = get_saldo_acumulado(ano_sel, nat_param)
df_por_pessoa = get_gastos_mensais_por_pessoa(ano_sel, nat_param)

# Meses ordenados corretamente, sem duplicatas (MESES_PT vem do core.charts).
meses_disp = sorted(
    df_mensal["mes"].unique().tolist(),
    key=lambda m: ch.MESES_PT.index(m) if m in ch.MESES_PT else 99
)

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🏠 Visão Geral", "📅 Mensal", "🏷️ Categorias", "📊 Orçado vs Real", "👥 Por Pessoa"
])

# ══════════════════════════════════════════════════════════════════════════
# TAB 1 — VISÃO GERAL
# ══════════════════════════════════════════════════════════════════════════
with tab1:
    if df_mensal.empty:
        st.info("Nenhum dado encontrado para os filtros selecionados.")
    else:
        total_ent = int(df_mensal["entradas"].sum())
        total_sai = int(df_mensal["saidas"].sum())
        total_inv = int(df_mensal["investimentos"].sum())
        poupanca  = total_ent - total_sai
        perc_p    = round(poupanca / total_ent * 100, 1) if total_ent > 0 else 0
        mes_caro  = df_mensal.loc[df_mensal["saidas"].idxmax()]
        mes_barat = df_mensal.loc[df_mensal["saidas"].idxmin()]

        # Com o modulo de investimentos ativo entra a 6a metrica (Investido YTD)
        # logo apos a Poupanca — o investimento e um DESTINO da poupanca, entao a
        # leitura natural e "poupei X, guardei Y disso".
        if tem_inv:
            c1, c2, c3, c6, c4, c5 = st.columns(6)
            perc_i = round(total_inv / total_ent * 100, 1) if total_ent > 0 else 0
            c6.metric("💎 Investido YTD", ch.fmt_moeda(total_inv),
                      delta=f"{perc_i}% das entradas")
        else:
            c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("💰 Entradas YTD",    ch.fmt_moeda(total_ent))
        c2.metric("💸 Saídas YTD",      ch.fmt_moeda(total_sai))
        c3.metric("🏦 Poupança YTD",    ch.fmt_moeda(poupanca), delta=f"{perc_p}% das entradas")
        c4.metric("📈 Mês mais caro",   mes_caro["mes"],
                  delta=f"-{ch.fmt_moeda(int(mes_caro['saidas']))}", delta_color="inverse")
        c5.metric("📉 Mês mais barato", mes_barat["mes"],
                  delta=f"-{ch.fmt_moeda(int(mes_barat['saidas']))}", delta_color="off")

        st.markdown("---")
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### Entradas vs Saídas por Mês")
            series = [
                {"col": "entradas", "nome": "Entradas", "cor": ch.COR_ENTRADA},
                {"col": "saidas",   "nome": "Saídas",   "cor": ch.COR_SAIDA},
            ]
            # 3a barra (dourada): quanto da poupanca do mes virou aporte. So
            # aparece para household com o modulo de investimentos.
            if tem_inv and total_inv > 0:
                series.append({"col": "investimentos", "nome": "Investimentos",
                               "cor": ch.COR_INVESTIMENTO})
            st.plotly_chart(ch.barras_mensais(df_mensal, "mes", series, altura=360),
                            use_container_width=True)

        with col2:
            st.markdown("#### Poupança Acumulada no Ano")
            if not df_saldo_ac.empty:
                ultimo = float(df_saldo_ac["saldo_acumulado"].iloc[-1])
                cor = ch.COR_ENTRADA if ultimo >= 0 else ch.COR_SAIDA
                fig2 = ch.linha_temporal(
                    df_saldo_ac, "mes",
                    [{"col": "saldo_acumulado", "nome": "Acumulado", "cor": cor}],
                    area=True, altura=360)
                fig2.add_hline(y=0, line_dash="dash", line_color="#90A4AE")
                st.plotly_chart(fig2, use_container_width=True)

        st.markdown("#### Poupança Mês a Mês")
        df_mensal["poupanca"] = (df_mensal["entradas"] - df_mensal["saidas"]).astype(int)
        cores = [ch.COR_ENTRADA if v >= 0 else ch.COR_SAIDA for v in df_mensal["poupanca"]]
        fig3 = go.Figure(go.Bar(
            x=df_mensal["mes"], y=df_mensal["poupanca"], marker_color=cores,
            hovertemplate="<b>%{x}</b><br>Poupança: %{y:,.0f}<extra></extra>"))
        fig3.add_hline(y=0, line_dash="dash", line_color="#90A4AE")
        ch.aplicar_tema(fig3, altura=260)
        st.plotly_chart(fig3, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════
# TAB 2 — MENSAL
# ══════════════════════════════════════════════════════════════════════════
with tab2:
    if not meses_disp:
        st.info("Nenhum dado disponível.")
    else:
        mes_sel    = st.selectbox("Mês", meses_disp, key="t2_mes")
        nro_mes_t2 = ch.MESES_PT.index(mes_sel) + 1 if mes_sel in ch.MESES_PT else 1
        df_mes     = df_mensal[df_mensal["mes"] == mes_sel]
        df_cats_m  = get_gastos_por_categoria(ano_sel, nro_mes_t2, quem_param, nat_param)

        if not df_mes.empty:
            row    = df_mes.iloc[0]
            ent_m  = int(row["entradas"])
            sai_m  = int(row["saidas"])
            inv_m  = int(row["investimentos"])
            poup_m = ent_m - sai_m

            # Investido do mes como metrica propria quando o modulo esta ativo
            # (mesma logica da Visao Geral: investimento nao e saida).
            if tem_inv:
                c1, c2, c3, c4 = st.columns(4)
                c4.metric("💎 Investido", ch.fmt_moeda(inv_m))
            else:
                c1, c2, c3 = st.columns(3)
            c1.metric("Entradas",  ch.fmt_moeda(ent_m))
            c2.metric("Saídas",    ch.fmt_moeda(sai_m))
            c3.metric("Poupança",  ch.fmt_moeda(poup_m),
                      delta=f"{round(poup_m / ent_m * 100, 1)}%" if ent_m > 0 else "")

            st.markdown("---")
            st.markdown(f"#### Resumo — {mes_sel}")
            barras_x = ["Entradas", "Saídas", "Poupança"]
            barras_y = [ent_m, sai_m, poup_m]
            barras_c = [ch.COR_ENTRADA, ch.COR_SAIDA, ch.COR_ENTRADA if poup_m >= 0 else ch.COR_SAIDA]
            if tem_inv:
                barras_x.append("Investido")
                barras_y.append(inv_m)
                barras_c.append(ch.COR_INVESTIMENTO)
            fig_r = go.Figure(go.Bar(
                x=barras_x, y=barras_y, marker_color=barras_c,
                text=[ch.fmt_moeda(v) for v in barras_y], textposition="outside",
                hovertemplate="<b>%{x}</b><br>%{y:,.0f}<extra></extra>"))
            ch.aplicar_tema(fig_r, altura=300)
            st.plotly_chart(fig_r, use_container_width=True)
            st.markdown("---")

        if not df_cats_m.empty:
            df_cats_m["total"] = df_cats_m["total"].round(0).astype(int)
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"#### Gastos por Categoria — {mes_sel}")
                st.plotly_chart(
                    ch.barras_ranking(df_cats_m, "categoria", "total",
                                      cor=ch.COR_SALDO, altura=380),
                    use_container_width=True)
            with col2:
                st.markdown(f"#### Distribuição — {mes_sel}")
                st.plotly_chart(ch.rosca(df_cats_m, "categoria", "total", altura=380),
                                use_container_width=True)

            st.markdown("#### Detalhamento")
            df_d = df_cats_m[["categoria", "total"]].copy()
            df_d.columns = ["Categoria", "Gasto (S$)"]
            df_d["% do mês"] = (df_d["Gasto (S$)"] / df_d["Gasto (S$)"].sum() * 100).round(1)
            st.dataframe(df_d.sort_values("Gasto (S$)", ascending=False),
                         use_container_width=True, hide_index=True)
        else:
            st.info(f"Nenhum gasto em {mes_sel}.")


# ══════════════════════════════════════════════════════════════════════════
# TAB 3 — CATEGORIAS
# ══════════════════════════════════════════════════════════════════════════
with tab3:
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        periodo_t3 = st.radio("Período", ["Ano todo", "Mês específico"],
                              horizontal=True, key="t3_periodo")
    nro_mes_t3 = None
    if periodo_t3 == "Mês específico":
        with col_f2:
            mes_t3     = st.selectbox("Mês", meses_disp, key="t3_mes")
            nro_mes_t3 = ch.MESES_PT.index(mes_t3) + 1 if mes_t3 in ch.MESES_PT else None

    df_cats_a = get_gastos_por_categoria(ano_sel, nro_mes_t3, quem_param, nat_param)

    if df_cats_a.empty:
        st.info("Nenhum dado para o período.")
    else:
        df_cats_a["total"] = df_cats_a["total"].round(0).astype(int)
        total_g = df_cats_a["total"].sum()
        top     = df_cats_a.iloc[0]

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Gasto",  ch.fmt_moeda(total_g))
        c2.metric("Categorias",   str(len(df_cats_a)))
        c3.metric("Maior Gasto",  top["categoria"],
                  delta=ch.fmt_moeda(top["total"]), delta_color="off")

        st.markdown("---")
        col1, col2 = st.columns([3, 2])
        with col1:
            st.markdown("#### Ranking por Categoria")
            st.plotly_chart(
                ch.barras_ranking(df_cats_a, "categoria", "total",
                                  cor=ch.COR_SALDO, altura=420),
                use_container_width=True)
        with col2:
            st.markdown("#### Distribuição %")
            st.plotly_chart(ch.rosca(df_cats_a, "categoria", "total", altura=420),
                            use_container_width=True)

        st.markdown("#### Tabela Completa")
        df_t = df_cats_a.copy()
        df_t["% do total"] = (df_t["total"] / total_g * 100).round(1)
        df_t.columns = ["Categoria", "Gasto (S$)", "% do Total"]
        st.dataframe(df_t, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════
# TAB 4 — ORÇADO VS REAL  (logica de antecipado/excedente preservada)
# ══════════════════════════════════════════════════════════════════════════
with tab4:
    col_o1, col_o2 = st.columns(2)
    with col_o1:
        per_t4 = st.radio("Período", ["Ano todo", "Mês específico"],
                          horizontal=True, key="t4_periodo")
    nro_mes_t4 = None
    if per_t4 == "Mês específico":
        with col_o2:
            mes_t4     = st.selectbox("Mês", meses_disp, key="t4_mes")
            nro_mes_t4 = ch.MESES_PT.index(mes_t4) + 1 if mes_t4 in ch.MESES_PT else None

    df_orc2 = get_orcamento_vs_realizado(
        ano_sel, nro_mes_t4,
        esconder_quitadas_anteriores=(nro_mes_t4 is not None),
    )

    if df_orc2.empty:
        st.info("Nenhum orçamento definido.")
    else:
        # A funcao retorna 8 colunas: natureza, tipo, orcado, gasto, saldo, anual,
        # quitado_ano, orcado_anual. Renomeia as duas primeiras para o resto do bloco.
        df_orc2 = df_orc2.rename(columns={"natureza": "Natureza", "tipo": "Categoria"})
        df_orc2 = df_orc2[df_orc2["orcado"] > 0].copy()
        for c in ["orcado", "gasto", "saldo", "orcado_anual"]:
            df_orc2[c] = df_orc2[c].round(0).astype(int)
        df_orc2["perc"] = (df_orc2["gasto"] / df_orc2["orcado"] * 100).round(1)

        c1, c2, c3 = st.columns(3)
        # KPI "Total Orçado": quando filtrando por mês, mostra o orçado DAQUELE MÊS
        # isolado (não acumulado). Para categorias mensais: orcado_anual / 12 = 1 mês.
        # Para categorias anuais: orcado inteiro (é um lump sum — cabe no ano todo).
        # Em modo "Ano todo": usa o orcado acumulado normalmente.
        if nro_mes_t4 is not None:
            orcado_kpi = int(df_orc2.apply(
                lambda r: r["orcado"] if r["anual"] else round(r["orcado_anual"] / 12),
                axis=1
            ).sum())
        else:
            orcado_kpi = int(df_orc2["orcado"].sum())
        c1.metric("Total Orçado", ch.fmt_moeda(orcado_kpi))
        c2.metric("Total Gasto",  ch.fmt_moeda(df_orc2["gasto"].sum()))
        c3.metric("Saldo",        ch.fmt_moeda(df_orc2["saldo"].sum()))

        st.markdown("---")
        st.markdown("#### Orçado vs Realizado por Categoria")
        st.caption(
            "🔵 Realizado (dentro do orçado do período) · "
            "🟡 Antecipado (categoria anual paga em lump sum, cabe no orçado anual) · "
            "🔴 Excedente (gastou mais do que o orçado do período) · "
            "░ Orçado disponível"
        )

        # Decompoe o gasto em 3 faixas:
        #   - gasto_dentro:    parte do gasto que cabe no orcado do periodo (azul)
        #   - antecipado:      parte acima do mensal acumulado de uma categoria ANUAL
        #                      (lump sum) que ainda cabe no orcado anual (amarelo).
        #   - excedente_real:  parte que estourou o orcado do periodo (vermelho)
        # No modo "Ano todo", orcado_anual == orcado, entao folga_anual=0 e qualquer
        # excedente vai direto para vermelho (comportamento anterior).
        df_orc2["gasto_dentro"]    = df_orc2[["gasto", "orcado"]].min(axis=1)
        df_orc2["excedente_total"] = (df_orc2["gasto"] - df_orc2["orcado"]).clip(lower=0)
        df_orc2["folga_anual"]     = (df_orc2["orcado_anual"] - df_orc2["orcado"]).clip(lower=0)
        # Antecipado so se aplica a categorias anuais; recorrente mensal vai tudo p/ vermelho.
        df_orc2["antecipado"] = (
            df_orc2[["excedente_total", "folga_anual"]].min(axis=1)
            .where(df_orc2["anual"] == True, other=0)
        )
        df_orc2["excedente_real"] = df_orc2["excedente_total"] - df_orc2["antecipado"]

        fig = go.Figure()
        # Barra de fundo: orcado do periodo (cinza azulado claro).
        fig.add_trace(go.Bar(
            y=df_orc2["Categoria"], x=df_orc2["orcado"],
            name="Orçado", orientation="h", marker_color="#BBDEFB",
            hovertemplate="<b>%{y}</b><br>Orçado: S$ %{x:,}<extra></extra>"))
        # Parte azul: gasto ate o limite do orcado do periodo.
        fig.add_trace(go.Bar(
            y=df_orc2["Categoria"], x=df_orc2["gasto_dentro"],
            name="Realizado", orientation="h", marker_color=ch.COR_SALDO,
            hovertemplate="<b>%{y}</b><br>Realizado: S$ %{x:,}<extra></extra>"))
        # Parte amarela: antecipado (passou do mensal, cabe no anual).
        antecipados = df_orc2[df_orc2["antecipado"] > 0]
        if not antecipados.empty:
            fig.add_trace(go.Bar(
                y=antecipados["Categoria"], x=antecipados["antecipado"],
                name="Antecipado", orientation="h",
                marker_color=ch.COR_INVESTIMENTO, base=antecipados["orcado"],
                hovertemplate=("<b>%{y}</b><br>Antecipado: S$ %{x:,}"
                               "<br><i>cabe no orçado anual</i><extra></extra>")))
        # Parte vermelha: excedente real (estourou o orcado anual).
        excedentes_reais = df_orc2[df_orc2["excedente_real"] > 0]
        if not excedentes_reais.empty:
            fig.add_trace(go.Bar(
                y=excedentes_reais["Categoria"], x=excedentes_reais["excedente_real"],
                name="Excedente real", orientation="h", marker_color=ch.COR_SAIDA,
                base=excedentes_reais["orcado"] + excedentes_reais["antecipado"],
                hovertemplate=("<b>%{y}</b><br>Excedente real: S$ %{x:,}"
                               "<br><i>passou do orçado anual</i><extra></extra>")))

        fig.update_layout(barmode="overlay")
        ch.aplicar_tema(fig, altura=max(360, len(df_orc2) * 38), moeda_eixo_y=False)
        fig.update_xaxes(tickprefix="S$ ", separatethousands=True,
                         showgrid=True, gridcolor="rgba(148,163,184,0.25)")
        fig.update_yaxes(showgrid=False)
        fig.update_layout(hovermode="closest")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### Detalhamento por Categoria")
        df_tab = df_orc2[["Categoria", "orcado", "gasto", "saldo", "perc"]].copy()
        df_tab.columns = ["Categoria", "Orçado", "Gasto", "Saldo", "% Gasto"]
        st.dataframe(df_tab.sort_values("% Gasto", ascending=False),
                     use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════
# TAB 5 — POR PESSOA
# ══════════════════════════════════════════════════════════════════════════
with tab5:
    if df_por_pessoa.empty:
        st.info("Nenhum dado encontrado.")
    else:
        df_por_pessoa["total"] = df_por_pessoa["total"].round(0).astype(int)
        pessoas = sorted(df_por_pessoa["quem"].unique().tolist())
        cores_pessoa = [ch.COR_SALDO, ch.PALETA[2]]  # azul / laranja

        cols_p = st.columns(len(pessoas))
        for i, pessoa in enumerate(pessoas):
            total_p = int(df_por_pessoa[df_por_pessoa["quem"] == pessoa]["total"].sum())
            cols_p[i].metric(f"💸 {pessoa}", ch.fmt_moeda(total_p))

        st.markdown("---")
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### Gastos Mensais por Pessoa")
            fig = go.Figure()
            for i, pessoa in enumerate(pessoas):
                sub = df_por_pessoa[df_por_pessoa["quem"] == pessoa]
                fig.add_trace(go.Bar(
                    x=sub["mes"], y=sub["total"], name=str(pessoa),
                    marker_color=cores_pessoa[i % len(cores_pessoa)],
                    hovertemplate="<b>%{x} — " + str(pessoa) + "</b><br>S$ %{y:,}<extra></extra>"))
            fig.update_layout(barmode="group")
            ch.aplicar_tema(fig, altura=360)
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.markdown("#### Split Total no Ano")
            df_split = df_por_pessoa.groupby("quem")["total"].sum().reset_index()
            st.plotly_chart(
                ch.rosca(df_split, "quem", "total", cores=cores_pessoa, altura=360),
                use_container_width=True)

        st.markdown("#### Comparativo por Categoria")
        # Comparativo dinamico entre os 2 primeiros membros do household.
        membros_comp = get_membros_household()
        if len(membros_comp) >= 2:
            p1, p2 = membros_comp[0], membros_comp[1]
            df_p1 = get_gastos_por_categoria(ano_sel, quem=p1, natureza=nat_param)
            df_p2 = get_gastos_por_categoria(ano_sel, quem=p2, natureza=nat_param)

            if not df_p1.empty or not df_p2.empty:
                df_comp = df_p1.merge(df_p2, on="categoria", how="outer",
                                      suffixes=("_1", "_2")).fillna(0)
                df_comp["total_1"] = df_comp["total_1"].round(0).astype(int)
                df_comp["total_2"] = df_comp["total_2"].round(0).astype(int)
                df_comp["Total"]   = df_comp["total_1"] + df_comp["total_2"]
                df_comp.columns    = ["Categoria", p1, p2, "Total"]
                st.dataframe(df_comp.sort_values("Total", ascending=False),
                             use_container_width=True, hide_index=True)
