"""
Pagina de Investimentos — modulo "dinheiro guardado" do App 10M.

Habilitada por household via households.investimentos_ativo (hoje so Admin).
O fluxo financeiro modelado aqui:

  1. O salario CHEIO ja e lancado como Entrada em Lancamentos.
  2. Parte dele vira aporte (conta -> corretora). Aporte NAO e saida nem
     entrada nova — e realocacao interna (valor_real=0), entao a poupanca
     do Dashboard nao muda. O que muda e o "bolo investido" deste modulo.
  3. Dividendos caem na CONTA CORRENTE: sao renda real do mes — entram como
     Entrada (categoria 'Dividendos') no fluxo do Dashboard E aparecem aqui
     como renda passiva. Se forem reinvestidos, registra-se um aporte
     variavel (ai voltam para o bolo).

  Total guardado = Saldo inicial + soma de todos os aportes.

Os aportes fixos mensais (ex.: 'Manu 4k' -> 4166/mes) ficam cadastrados em
config_investimentos e sao registrados em LOTE com 1 clique por mes — com
protecao anti-duplicacao (produto ja aportado no mes e pulado).
"""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import sys
from pathlib import Path
from datetime import date

sys.path.append(str(Path(__file__).parent.parent))
from core.database import (
    get_meses, get_membros_household, get_resumo_mensal, inserir_lancamento,
    delete_lancamentos,
    # Modulo de investimentos:
    get_investimentos_ativo, get_config_investimentos, add_config_investimento,
    update_config_investimento, get_aportes_fixos_registrados_no_mes,
    registrar_aportes_fixos, get_investimentos_mensal, get_total_investido,
    get_investido_por_produto, get_saldo_inicial_investimentos,
    get_registros_investimentos,
    CAT_APORTE_FIXO, CAT_APORTE_VAR, CAT_SALDO_INICIAL, CAT_DIVIDENDOS,
)

# Ano corrente da aplicacao (hardcoded por enquanto, ver project_app10milhoes.md).
ANO_APP = 2026

st.set_page_config(page_title="Investimentos", page_icon="💎", layout="wide")

# ── Gate por household ────────────────────────────────────────────────────
# app.py so registra esta pagina na navegacao quando o modulo esta ativo,
# mas o guard abaixo e defesa em profundidade (mesmo padrao do filtro
# household_id nas queries): se algo registrar a pagina por engano, ela
# nao renderiza dados de quem nao tem o modulo.
ativo = st.session_state.get("investimentos_ativo")
if ativo is None:
    ativo = get_investimentos_ativo()
if not ativo:
    st.info("💎 O módulo de investimentos não está habilitado para o seu household.")
    st.stop()

st.title("💎 Investimentos")

# Paleta do projeto: azul escuro = primario, azul claro = registrar/adicionar,
# verde = entrada/sucesso (dividendos sao renda — verde).
C_FIXO  = "#1565C0"
C_VAR   = "#42A5F5"
C_DIV   = "#2E7D32"
C_TOTAL = "#0D47A1"

MESES_LISTA = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
               "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def fmt(fig, height=340, legend_side=False):
    """Formatacao padrao dos graficos — mesma identidade visual do Dashboard."""
    leg = dict(orientation="v", x=1.02, y=0.5, xanchor="left") if legend_side \
        else dict(orientation="h", y=1.12)
    fig.update_layout(
        height=height, margin=dict(l=0, r=0, t=36, b=0),
        plot_bgcolor="white", paper_bgcolor="white",
        legend=leg, font=dict(family="Segoe UI", size=12),
        hoverlabel=dict(bgcolor="white", font_size=13),
    )
    fig.update_yaxes(gridcolor="#E0E7EF", zeroline=False)
    fig.update_xaxes(gridcolor="rgba(0,0,0,0)")
    return fig


# Feedback persistente entre reruns (registro em lote, avulso, config, delete).
if st.session_state.get("inv_msg"):
    st.success(st.session_state["inv_msg"])
    st.session_state["inv_msg"] = None

# ── Dados base ────────────────────────────────────────────────────────────
meses_df       = get_meses()
membros        = get_membros_household() or ["—"]
# Fixos entram no lote de 1 clique; a lista completa (fixos + variaveis)
# alimenta os selects de destino/origem do aporte avulso, dividendo e saldo
# inicial.
produtos_fixos_df = get_config_investimentos(somente_ativos=True, tipo="fixo")
produtos_todos_df = get_config_investimentos(somente_ativos=True)
df_mensal_inv  = get_investimentos_mensal(ANO_APP)
total_invest   = get_total_investido()
saldo_inicial  = get_saldo_inicial_investimentos()

aportes_ano    = float(df_mensal_inv["aporte_fixo"].sum() + df_mensal_inv["aporte_variavel"].sum()) \
                 if not df_mensal_inv.empty else 0.0
dividendos_ano = float(df_mensal_inv["dividendos"].sum()) if not df_mensal_inv.empty else 0.0

# % das entradas do ano que virou aporte — usa o total de Entradas do
# Dashboard (salarios + bonus + dividendos...) como denominador, em vez de
# filtrar "Salário" por nome (ha registros historicos com e sem acento).
df_resumo  = get_resumo_mensal(ANO_APP)
entradas_ano = float(df_resumo["entradas"].sum()) if not df_resumo.empty else 0.0
perc_invest  = (aportes_ano / entradas_ano * 100) if entradas_ano > 0 else None

# Quem default: Vinicius (e quem investe do proprio salario) — mas o select
# permite Juliana registrar os dela tambem.
quem_default = membros.index("Vinicius") if "Vinicius" in membros else 0
mes_default  = date.today().month - 1  # index 0-based no selectbox

# ── METRICAS ──────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("💰 Total guardado", f"SGD {total_invest:,.0f}",
          help="Saldo inicial + todos os aportes. Dividendos não somam aqui — "
               "eles caem na conta corrente (são renda do mês).")
c2.metric(f"📥 Aportado em {ANO_APP}", f"SGD {aportes_ano:,.0f}")
c3.metric(f"💵 Dividendos em {ANO_APP}", f"SGD {dividendos_ano:,.0f}",
          help="Renda passiva que caiu na conta. Também conta como Entrada no Dashboard.")
c4.metric("📊 % das entradas investido",
          f"{perc_invest:.1f}%" if perc_invest is not None else "—",
          help="Aportes do ano ÷ total de entradas do ano.")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════
# SECAO 1 — APORTES FIXOS DO MES (registro em lote)
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

    # Protecao anti-duplicacao: produto com aporte fixo JA registrado no mes
    # aparece como ✅ e fica fora do lote — evita aportar 2x sem querer
    # (especialmente no backfill, em que se navega mes a mes).
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
                    f"(SGD {total_pend:,.0f}). Total guardado: "
                    f"SGD {total_invest + total_pend:,.0f}."
                )
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao registrar aportes: {e}")
    else:
        st.success(f"Todos os aportes fixos de **{mes_lote}** já estão registrados. ✅")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════
# SECAO 2 — REGISTRO AVULSO (aporte variavel ou dividendo)
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
    # Produto/origem opcional — lista TODOS os produtos (fixos + variaveis):
    # aporte variavel costuma ir para os produtos de tipo variavel, e o
    # dividendo pode vir de qualquer um. "Sem produto" cobre o resto.
    opcoes_prod = ["— (sem produto)"] + (produtos_todos_df["nome"].tolist()
                                         if not produtos_todos_df.empty else [])
    rotulo_prod = "Origem (qual produto pagou)" if tipo_avulso == "Dividendo" \
        else "Produto/destino"
    prod_av = st.selectbox(rotulo_prod, opcoes_prod, key="inv_prod_av")

valor_av = st.number_input("Valor (SGD)", min_value=0.0, value=None, step=1.0,
                           format="%.2f", placeholder="Digite o valor...",
                           key="inv_valor_av")
obs_av = st.text_area("Observação (opcional)", key="inv_obs_av")

if st.button(f"Registrar {tipo_avulso.lower()}", use_container_width=True,
             key="inv_btn_avulso"):
    if not valor_av:
        st.error("Insira um valor válido!")
    else:
        nro_mes_av = MESES_LISTA.index(mes_av) + 1
        item_av = None if prod_av == "— (sem produto)" else prod_av
        if tipo_avulso == "Dividendo":
            # Dividendo cai na conta -> e Entrada de verdade no fluxo mensal
            # (natureza Pessoal, igual salario), alem de rastreado no modulo.
            dados = {"tipo_geral": "Entrada", "natureza": "Pessoal",
                     "categoria": CAT_DIVIDENDOS}
        else:
            dados = {"tipo_geral": "Investimento", "natureza": "Investimento",
                     "categoria": CAT_APORTE_VAR}
        dados.update({
            "data": date.today(), "mes": mes_av, "ano": ANO_APP,
            "quem": quem_av, "item": item_av, "valor": valor_av,
            "pagamento": None, "observacao": obs_av or None,
            "nro_mes": nro_mes_av,
        })
        try:
            inserir_lancamento(dados)
            if tipo_avulso == "Dividendo":
                st.session_state["inv_msg"] = (
                    f"✅ Dividendo de SGD {valor_av:,.2f} em **{mes_av}** registrado! "
                    f"Total de dividendos em {ANO_APP}: SGD {dividendos_ano + valor_av:,.0f}. "
                    f"(Também entrou como Entrada no Dashboard.)"
                )
            else:
                st.session_state["inv_msg"] = (
                    f"✅ Aporte variável de SGD {valor_av:,.2f} em **{mes_av}** registrado! "
                    f"Total guardado: SGD {total_invest + valor_av:,.0f}."
                )
            st.rerun()
        except Exception as e:
            st.error(f"Erro ao registrar: {e}")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════
# SECAO 3 — GRAFICOS
# ══════════════════════════════════════════════════════════════════════════
if df_mensal_inv.empty and total_invest == 0:
    st.info("Sem dados ainda — registre o saldo inicial e os aportes de "
            "Janeiro a Junho para ver a evolução. 🚀")
else:
    col_g1, col_g2 = st.columns(2)

    with col_g1:
        st.markdown("#### Aportes e dividendos por mês")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_mensal_inv["mes"], y=df_mensal_inv["aporte_fixo"],
            name="Aporte fixo", marker_color=C_FIXO,
            hovertemplate="<b>%{x}</b><br>Aporte fixo: SGD %{y:,}<extra></extra>"))
        fig.add_trace(go.Bar(x=df_mensal_inv["mes"], y=df_mensal_inv["aporte_variavel"],
            name="Aporte variável", marker_color=C_VAR,
            hovertemplate="<b>%{x}</b><br>Aporte variável: SGD %{y:,}<extra></extra>"))
        fig.add_trace(go.Scatter(x=df_mensal_inv["mes"], y=df_mensal_inv["dividendos"],
            name="Dividendos", mode="lines+markers",
            line=dict(color=C_DIV, width=3),
            hovertemplate="<b>%{x}</b><br>Dividendos: SGD %{y:,}<extra></extra>"))
        # Barras empilhadas: o total da barra = aporte do mes; linha verde
        # por cima mostra a renda passiva crescendo conforme o bolo cresce.
        fig.update_layout(barmode="stack")
        fig.update_yaxes(tickprefix="SGD ")
        st.plotly_chart(fmt(fig), use_container_width=True)

    with col_g2:
        st.markdown("#### Total guardado acumulado")
        df_ac = df_mensal_inv.copy()
        if not df_ac.empty:
            df_ac["aportes"] = df_ac["aporte_fixo"] + df_ac["aporte_variavel"]
            # Acumulado parte do saldo inicial (patrimonio pre-app) e soma os
            # aportes mes a mes — e a curva rumo aos 10 milhoes.
            df_ac["acumulado"] = saldo_inicial + df_ac["aportes"].cumsum()
            fig2 = px.area(df_ac, x="mes", y="acumulado",
                           color_discrete_sequence=[C_TOTAL])
            fig2.update_traces(
                hovertemplate="<b>%{x}</b><br>Guardado: SGD %{y:,}<extra></extra>")
            if saldo_inicial > 0:
                fig2.add_hline(y=saldo_inicial, line_dash="dash", line_color="#90A4AE",
                               annotation_text="Saldo inicial")
            fig2.update_yaxes(tickprefix="SGD ")
            st.plotly_chart(fmt(fig2), use_container_width=True)
        else:
            st.info("Registre aportes para ver o acumulado.")

    df_prod = get_investido_por_produto()
    if not df_prod.empty:
        st.markdown("#### Guardado por produto")
        df_prod["total"] = df_prod["total"].astype(float).round(0).astype(int)
        fig3 = px.bar(df_prod.sort_values("total"), x="total", y="produto",
                      orientation="h", color_discrete_sequence=[C_FIXO])
        fig3.update_traces(hovertemplate="<b>%{y}</b><br>SGD %{x:,}<extra></extra>")
        fig3.update_xaxes(tickprefix="SGD ")
        st.plotly_chart(fmt(fig3, height=max(220, len(df_prod) * 48)),
                        use_container_width=True)

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════
# SECAO 4 — SALDO INICIAL
# ══════════════════════════════════════════════════════════════════════════
# Aberto enquanto nao houver saldo inicial (onboarding do modulo); depois
# vira expander fechado para adicionar saldos por produto se quiser detalhar.
with st.expander("🏁 Saldo inicial (quanto você já tinha investido antes do app)",
                 expanded=(saldo_inicial == 0)):
    if saldo_inicial > 0:
        st.caption(f"Saldo inicial registrado: **SGD {saldo_inicial:,.0f}**. "
                   "Você pode adicionar mais registros (ex.: detalhar por produto) — "
                   "ou excluir em 🗂️ Registros do ano e refazer.")
    else:
        st.caption("Registre 1x o que você já tinha guardado em 01/Janeiro/2026. "
                   "Pode ser um valor único ou um registro por produto.")

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
                # Saldo inicial ancora em Janeiro/ANO_APP: e o ponto de partida
                # do acumulado (nro_mes=1), independente do dia em que foi
                # digitado — coerente com a regra "nro_mes e a referencia
                # autoritativa de mes" do projeto.
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
                    f"Total guardado: SGD {total_invest + valor_si:,.0f}."
                )
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao registrar saldo inicial: {e}")

# ══════════════════════════════════════════════════════════════════════════
# SECAO 5 — MEUS PRODUTOS DE INVESTIMENTO (config)
# ══════════════════════════════════════════════════════════════════════════
# Dois tipos: 'fixo' (valor mensal imutavel -> entra no lote de 1 clique) e
# 'variavel' (so cadastra o nome; o valor e digitado a cada aporte avulso).
with st.expander("⚙️ Meus produtos de investimento", expanded=produtos_todos_df.empty):
    st.caption("**Fixo** = valor mensal que não muda, entra no botão de lote "
               "(ex.: Manu 4k → 4.166/mês). **Variável** = você cadastra só o "
               "nome e informa o valor quando manda dinheiro. Mudanças aqui só "
               "afetam os PRÓXIMOS registros — aportes lançados guardam o valor "
               "histórico.")

    df_prod_all = get_config_investimentos(somente_ativos=False)
    if not df_prod_all.empty:
        for _, p in df_prod_all.iterrows():
            pid = int(p["id"])
            eh_fixo = p["tipo"] == "fixo"
            col_n, col_t, col_v, col_at = st.columns([3, 1, 2, 2])
            col_n.markdown(f"**{p['nome']}**" + ("" if p["ativo"] else " _(inativo)_"))
            col_t.caption("📌 fixo" if eh_fixo else "🌊 variável")
            if eh_fixo:
                novo_vf = col_v.number_input(
                    "Valor fixo/mês", min_value=0.0, value=float(p["valor_fixo"]),
                    step=50.0, format="%.2f", key=f"inv_vf_{pid}",
                    label_visibility="collapsed",
                )
            else:
                col_v.caption("valor livre a cada aporte")
                novo_vf = None
            with col_at:
                c_save, c_tog = st.columns(2)
                if eh_fixo and c_save.button("💾", key=f"inv_save_{pid}",
                                             help="Salvar novo valor fixo"):
                    update_config_investimento(pid, {"valor_fixo": novo_vf})
                    st.session_state["inv_msg"] = \
                        f"✅ **{p['nome']}** atualizado para SGD {novo_vf:,.2f}/mês."
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
    col_nn, col_nv, col_nb = st.columns([3, 2, 2])
    nome_novo = col_nn.text_input("Nome", placeholder="Ex: Manu 4k",
                                  key="inv_nome_novo", label_visibility="collapsed")
    if eh_fixo_novo:
        valor_novo = col_nv.number_input(
            "Valor fixo mensal", min_value=0.0, value=None, step=50.0,
            format="%.2f", placeholder="4166.00",
            key="inv_valor_novo", label_visibility="collapsed")
    else:
        col_nv.caption("sem valor fixo — informado a cada aporte")
        valor_novo = None
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
                )
                detalhe = (f" (SGD {valor_novo:,.2f}/mês)" if eh_fixo_novo
                           else " (variável)")
                st.session_state["inv_msg"] = \
                    f"✅ Produto **{nome_novo.strip()}** criado{detalhe}."
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao criar produto: {e}")

# ══════════════════════════════════════════════════════════════════════════
# SECAO 6 — REGISTROS DO ANO (visualizar / excluir)
# ══════════════════════════════════════════════════════════════════════════
with st.expander("🗂️ Registros do ano", expanded=False):
    df_reg = get_registros_investimentos(ANO_APP)
    if df_reg.empty:
        st.info("Nenhum registro de investimento ainda.")
    else:
        st.caption("Errou um valor? Selecione, exclua e registre de novo — "
                   "mais simples (e mais seguro) que editar no lugar.")
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

        if st.button(f"🗑️ Remover ({n_sel})", disabled=n_sel == 0,
                     key="inv_btn_del"):
            st.session_state["inv_confirma_del"] = True

        if st.session_state.get("inv_confirma_del") and n_sel > 0:
            st.warning(f"Remover {n_sel} registro(s)? Esta ação não pode ser desfeita. "
                       "(Dividendos removidos somem também das Entradas do Dashboard.)")
            c_sim, c_nao = st.columns(2)
            if c_sim.button("Sim, remover", key="inv_btn_del_sim",
                            use_container_width=True):
                delete_lancamentos(ids_sel)
                st.session_state["inv_confirma_del"] = False
                st.session_state["inv_msg"] = f"✅ {n_sel} registro(s) removido(s)."
                st.rerun()
            if c_nao.button("Cancelar", key="inv_btn_del_nao",
                            use_container_width=True):
                st.session_state["inv_confirma_del"] = False
                st.rerun()
