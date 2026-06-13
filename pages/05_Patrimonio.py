"""
Pagina de Patrimonio (Networth) — acompanhamento do patrimonio TOTAL do
household ao longo dos meses/anos, tudo em SGD.

Como funciona:
  - Voce informa, por categoria e por mes, o valor em SGD (valor de fim de mes).
  - O formulario ja vem PRE-PREENCHIDO com o ultimo mes registrado: voce so
    ajusta o que mudou e salva. Reenviar o mesmo mes sobrescreve (1 registro
    por categoria por mes).
  - Contas SRS tem fator 0.71: voce digita o valor BRUTO e o app conta o
    LIQUIDO (bruto * 0.71, ja descontada a multa de saque antecipado do SRS).
    O fator vive na categoria, entao nao ha numero chumbado aqui.
  - O grafico principal mostra so o TOTAL (soma de todas as categorias, ja com
    o fator aplicado) mes a mes. As categorias servem de forma de entrada.

A camada de banco esta em core/patrimonio.py. O isolamento por household e
automatico (as funcoes resolvem o household do login).
"""
import streamlit as st
import plotly.graph_objects as go
import sys
from pathlib import Path
from datetime import date

sys.path.append(str(Path(__file__).parent.parent))
from core.patrimonio import (
    get_categorias, add_categoria, update_categoria,
    encerrar_categoria, reativar_categoria,
    get_valores_mes, get_valores_mes_anterior, salvar_mes,
    get_patrimonio_serie, get_detalhe_mes,
)

st.set_page_config(page_title="Patrimônio", page_icon="📈", layout="wide")

st.title("📈 Patrimônio")
st.caption("Evolução do patrimônio total da casa, mês a mês, em SGD. "
           "Contas SRS são informadas em bruto; o app conta o líquido (×0.71).")

# Paleta do projeto (mesma identidade do Dashboard / Investimentos).
C_TOTAL = "#0D47A1"             # linha do patrimonio
C_FILL  = "rgba(13,71,161,0.14)"  # area sob a linha

MESES_LISTA = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
               "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def fmt(fig, height=360):
    """Formatacao padrao do grafico — mesma identidade visual do resto do app."""
    fig.update_layout(
        height=height, margin=dict(l=0, r=0, t=36, b=0),
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", y=1.12),
        font=dict(family="Segoe UI", size=12),
        hoverlabel=dict(bgcolor="white", font_size=13),
    )
    fig.update_yaxes(gridcolor="#E0E7EF", zeroline=False)
    fig.update_xaxes(gridcolor="rgba(0,0,0,0)")
    return fig


# Feedback persistente entre reruns.
if st.session_state.get("pat_msg"):
    st.success(st.session_state["pat_msg"])
    st.session_state["pat_msg"] = None

# ══════════════════════════════════════════════════════════════════════════
# VISAO GERAL — patrimonio total ao longo do tempo (so o total)
# ══════════════════════════════════════════════════════════════════════════
serie = get_patrimonio_serie()

if serie.empty:
    st.info("Ainda não há patrimônio registrado. Preencha o primeiro mês "
            "no formulário abaixo para começar a curva. 🚀")
else:
    atual  = float(serie["patrimonio"].iloc[-1])
    inicio = float(serie["patrimonio"].iloc[0])
    delta  = atual - float(serie["patrimonio"].iloc[-2]) if len(serie) >= 2 else None
    ultimo_label = f"{serie['mes'].iloc[-1]}/{int(serie['ano'].iloc[-1])}"

    serie_ord = serie.sort_values("periodo").reset_index(drop=True)
    val_col = "patrimonio"
    patrimonio_atual = float(serie_ord[val_col].iloc[-1])
    tem_12m = len(serie_ord) >= 13
    if tem_12m:
        base_12m = float(serie_ord[val_col].iloc[-13])
        var_12m_abs = patrimonio_atual - base_12m
        var_12m_pct = (var_12m_abs / base_12m * 100.0) if base_12m else 0.0
        media_mensal = var_12m_abs / 12.0

    c1, c2, c3 = st.columns(3)
    c1.metric("💰 Patrimônio atual", f"SGD {atual:,.0f}",
              delta=(f"{delta:+,.0f} vs mês ant." if delta is not None else None),
              help=f"Último mês registrado: {ultimo_label}.")
    if tem_12m:
        c2.metric("Ultimos 12 meses", f"SGD {var_12m_abs:,.0f}", f"{var_12m_pct:+.1f}%")
    else:
        c2.metric("Ultimos 12 meses", "—")
    c3.metric("🗓️ Meses registrados", f"{len(serie)}")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=serie["periodo"], y=serie["patrimonio"], name="Patrimônio",
        mode="lines+markers", line=dict(color=C_TOTAL, width=2.5),
        fill="tozeroy", fillcolor=C_FILL,
        hovertemplate="%{x|%b/%Y}<br>Patrimônio: SGD %{y:,.0f}<extra></extra>"))
    fig.update_yaxes(tickprefix="SGD ")
    st.plotly_chart(fmt(fig), use_container_width=True)

    if tem_12m and media_mensal != 0:
        proj_12m = patrimonio_atual + var_12m_abs
        proj_5anos = patrimonio_atual + media_mensal * 60
        meta = 2_000_000
        if patrimonio_atual >= meta:
            tempo_meta = "meta ja atingida 🎉"
        elif media_mensal > 0:
            meses_meta = (meta - patrimonio_atual) / media_mensal
            tempo_meta = f"~{int(meses_meta // 12)} anos e {int(round(meses_meta % 12))} meses"
        else:
            tempo_meta = "ritmo atual nao chega a meta"
        st.markdown("#### 🔮 Projecao (ritmo dos ultimos 12 meses)")
        st.caption(f"Media de SGD {media_mensal:,.0f}/mes nos ultimos 12 meses.")
        pc = st.columns(3)
        pc[0].metric("Em 12 meses", f"SGD {proj_12m:,.0f}")
        pc[1].metric("Em 5 anos", f"SGD {proj_5anos:,.0f}")
        pc[2].metric("Para SGD 2 mi", tempo_meta)
        st.caption("Projecao linear (nao considera juros compostos nem mudanca no ritmo de aporte).")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════
# REGISTRAR / ATUALIZAR UM MES
# ══════════════════════════════════════════════════════════════════════════
st.subheader("✍️ Registrar / atualizar mês")

col_ano, col_mes = st.columns(2)
ano_sel = col_ano.number_input("Ano", min_value=2010, max_value=2100,
                               value=date.today().year, step=1, key="pat_ano")
mes_sel = col_mes.selectbox("Mês", MESES_LISTA, index=date.today().month - 1,
                            key="pat_mes")
ano_sel = int(ano_sel)
nro_mes_sel = MESES_LISTA.index(mes_sel) + 1

cats = get_categorias(somente_ativas=True)

if cats.empty:
    st.info("Cadastre suas categorias de patrimônio em **⚙️ Minhas categorias** "
            "(no fim da página) para liberar o preenchimento.")
else:
    # Pre-preenchimento: se o mes ja tem dados, usa eles; senao, repete o
    # ultimo mes com dados (voce so ajusta o que mudou).
    existentes = get_valores_mes(ano_sel, nro_mes_sel)
    if existentes:
        prefill = existentes
        st.caption(f"Editando **{mes_sel}/{ano_sel}** (já tem dados salvos). "
                   "Ajuste e salve para sobrescrever.")
    else:
        prefill = get_valores_mes_anterior(ano_sel, nro_mes_sel)
        if prefill:
            st.caption("Campos pré-preenchidos com o último mês registrado. "
                       f"Ajuste o que mudou e salve como **{mes_sel}/{ano_sel}**.")
        else:
            st.caption(f"Primeiro registro — preencha os valores de **{mes_sel}/{ano_sel}**.")

    valores_form = {}
    total_preview = 0.0

    # Cabecalho da "tabela" de entrada.
    h1, h2, h3 = st.columns([3, 2, 2])
    h1.markdown("**Categoria**")
    h2.markdown("**Valor bruto (SGD)**")
    h3.markdown("**Conta no patrimônio**")

    for _, c in cats.iterrows():
        cid = int(c["id"])
        fator = float(c["fator_liquido"])
        eh_srs = abs(fator - 1.0) > 1e-9
        default_val = float(prefill.get(cid, 0.0))

        col_n, col_v, col_liq = st.columns([3, 2, 2])

        nome_disp = f"**{c['nome']}**"
        if eh_srs:
            nome_disp += f"  \n_SRS · conta ×{fator:.2f}_"
        col_n.markdown(nome_disp)

        # Chave inclui ano+mes: trocar de mes recarrega o pre-preenchimento
        # (evita o number_input "grudar" no valor do mes anterior).
        val = col_v.number_input(
            c["nome"], min_value=0.0, value=default_val, step=100.0,
            format="%.2f", key=f"pat_val_{cid}_{ano_sel}_{nro_mes_sel}",
            label_visibility="collapsed")

        liquido = val * fator
        if eh_srs:
            col_liq.markdown(f"**SGD {liquido:,.0f}**  \n_bruto SGD {val:,.0f}_")
        else:
            col_liq.markdown(f"SGD {liquido:,.0f}")

        valores_form[cid] = val
        total_preview += liquido

    st.markdown("")
    cm1, cm2 = st.columns([2, 1])
    cm1.metric("Patrimônio do mês (prévia)", f"SGD {total_preview:,.0f}",
               help="Soma de todas as categorias já com o fator aplicado "
                    "(SRS ×0.71). É o valor que vai para o gráfico.")
    with cm2:
        st.markdown("")
        st.markdown("")
        if st.button("💾 Salvar mês", type="primary", use_container_width=True,
                     key="pat_btn_salvar"):
            try:
                n = salvar_mes(ano_sel, nro_mes_sel, valores_form)
                st.session_state["pat_msg"] = (
                    f"✅ {mes_sel}/{ano_sel} salvo ({n} categorias). "
                    f"Patrimônio do mês: SGD {total_preview:,.0f}."
                )
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao salvar: {e}")

    # Conferencia do mes (mostra o fator aplicado por categoria).
    with st.expander("🔎 Conferir o mês salvo (bruto × fator = líquido)", expanded=False):
        det = get_detalhe_mes(ano_sel, nro_mes_sel)
        if det.empty:
            st.info("Este mês ainda não foi salvo.")
        else:
            det_sh = det.copy()
            det_sh["valor_bruto"] = det_sh["valor_bruto"].astype(float).round(0)
            det_sh["fator_liquido"] = det_sh["fator_liquido"].astype(float)
            det_sh["valor_liquido"] = det_sh["valor_liquido"].astype(float).round(0)
            st.dataframe(
                det_sh, use_container_width=True, hide_index=True,
                column_config={
                    "nome": "Categoria",
                    "valor_bruto": st.column_config.NumberColumn("Bruto", format="SGD %d"),
                    "fator_liquido": st.column_config.NumberColumn("Fator", format="%.2f"),
                    "valor_liquido": st.column_config.NumberColumn("Líquido", format="SGD %d"),
                },
            )
            total_mes = float(det_sh["valor_liquido"].sum())
            st.caption(f"Total líquido de {mes_sel}/{ano_sel}: **SGD {total_mes:,.0f}**.")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════
# MINHAS CATEGORIAS (config)
# ══════════════════════════════════════════════════════════════════════════
with st.expander("⚙️ Minhas categorias de patrimônio", expanded=cats.empty):
    st.caption("Cada categoria é uma 'caixinha' de patrimônio (ex.: XP Vinicius, "
               "Cash, Crypto). O **fator** é quanto da categoria conta no "
               "patrimônio: deixe **1.00** para contas normais e **0.71** para "
               "contas **SRS** (você informa o bruto, conta o líquido). "
               "**Desativar** tira a categoria do formulário mas mantém o "
               "histórico já registrado.")

    cats_all = get_categorias(somente_ativas=False)
    if not cats_all.empty:
        for _, c in cats_all.iterrows():
            cid = int(c["id"])
            ativa = bool(c["ativa"])
            col_n, col_f, col_o, col_ac = st.columns([3, 2, 2, 2])
            novo_nome = col_n.text_input(
                "Nome", value=str(c["nome"]), key=f"pat_nome_{cid}",
                label_visibility="collapsed")
            if not ativa:
                col_n.caption("_(inativa)_")
            novo_fator = col_f.number_input(
                "Fator", min_value=0.0, max_value=1.0, value=float(c["fator_liquido"]),
                step=0.01, format="%.2f", key=f"pat_fator_{cid}",
                label_visibility="collapsed")
            nova_ordem = col_o.number_input(
                "Ordem", min_value=0, value=int(c["ordem"]), step=1,
                key=f"pat_ordem_{cid}", label_visibility="collapsed")
            with col_ac:
                c_save, c_tog = st.columns(2)
                if c_save.button("💾", key=f"pat_save_{cid}", help="Salvar nome/fator/ordem"):
                    update_categoria(cid, {
                        "nome": novo_nome.strip(),
                        "fator_liquido": float(novo_fator),
                        "ordem": int(nova_ordem),
                    })
                    st.session_state["pat_msg"] = f"✅ Categoria **{novo_nome.strip()}** atualizada."
                    st.rerun()
                rotulo = "🚫" if ativa else "♻️"
                ajuda = ("Desativar (sai do formulário, histórico preservado)"
                         if ativa else "Reativar categoria")
                if c_tog.button(rotulo, key=f"pat_tog_{cid}", help=ajuda):
                    if ativa:
                        encerrar_categoria(cid)
                    else:
                        reativar_categoria(cid)
                    st.session_state["pat_msg"] = (
                        f"✅ Categoria **{c['nome']}** "
                        f"{'desativada' if ativa else 'reativada'}."
                    )
                    st.rerun()
        st.divider()

    st.markdown("**➕ Nova categoria**")
    col_nn, col_nf, col_nb = st.columns([3, 2, 2])
    nome_novo = col_nn.text_input("Nome", placeholder="Ex: XP Vinicius",
                                  key="pat_nome_novo", label_visibility="collapsed")
    fator_novo = col_nf.number_input("Fator", min_value=0.0, max_value=1.0,
                                     value=1.00, step=0.01, format="%.2f",
                                     key="pat_fator_novo", label_visibility="collapsed")
    if col_nb.button("➕ Adicionar", key="pat_btn_add", use_container_width=True):
        nomes_existentes = (cats_all["nome"].str.lower().tolist()
                            if not cats_all.empty else [])
        if not nome_novo or not nome_novo.strip():
            st.error("Dê um nome à categoria.")
        elif nome_novo.strip().lower() in nomes_existentes:
            st.error(f"Já existe uma categoria chamada **{nome_novo.strip()}**.")
        else:
            try:
                add_categoria(nome_novo.strip(), fator_liquido=float(fator_novo))
                st.session_state["pat_msg"] = (
                    f"✅ Categoria **{nome_novo.strip()}** criada "
                    f"(fator {float(fator_novo):.2f})."
                )
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao criar categoria: {e}")
