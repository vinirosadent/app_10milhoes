import streamlit as st
import sys
from pathlib import Path
from datetime import date

sys.path.append(str(Path(__file__).parent.parent))
from core.database import (
    get_meses, get_ultimo_mes, get_config_saidas, get_config_entradas,
    get_formas_pagamento, inserir_lancamento, get_lancamentos,
    get_consulta_saldo, get_total_ano
)

st.set_page_config(page_title="Lancamentos", page_icon="📝", layout="centered")

if "modo" not in st.session_state:
    st.session_state.modo = "form"
if "feedback_msg" not in st.session_state:
    st.session_state.feedback_msg = ""
if "feedback_cor" not in st.session_state:
    st.session_state.feedback_cor = "success"

CATS_COM_OBS = ["Bonus", "Reembolso Sheares", "Congresso", "Reembolso"]

# ── Modo sucesso ──────────────────────────────────────────────────────────
if st.session_state.modo == "sucesso":
    st.title("Lancamento Registrado")
    st.markdown("---")
    if st.session_state.feedback_cor == "warning":
        st.warning(st.session_state.feedback_msg)
    elif st.session_state.feedback_cor == "info":
        st.info(st.session_state.feedback_msg)
    else:
        st.success(st.session_state.feedback_msg)
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Novo Lancamento", use_container_width=True, type="primary"):
            st.session_state.modo = "form"
            st.rerun()
    with col2:
        if st.button("Home", use_container_width=True):
            st.switch_page("pages/Home.py")
    st.stop()

# ── Modo form ─────────────────────────────────────────────────────────────
st.title("Novo Lancamento")

meses_df      = get_meses()
saidas_df     = get_config_saidas()
entradas_df   = get_config_entradas()
pagamentos_df = get_formas_pagamento()

meses_lista = meses_df["nome"].tolist()
pagamentos  = pagamentos_df["nome"].tolist()

ultimo_mes = get_ultimo_mes()
mes_index  = meses_lista.index(ultimo_mes) if ultimo_mes in meses_lista else 0

col1, col2 = st.columns(2)
with col1:
    quem = st.selectbox("Quem esta lancando?", ["Vinicius", "Juliana"])
with col2:
    mes_nome = st.selectbox("Mes", meses_lista, index=mes_index)

nro_mes    = int(meses_df.loc[meses_df["nome"] == mes_nome, "nro"].values[0])
tipo_geral = st.radio("Operacao", ["Saida", "Entrada"], horizontal=True)

st.markdown("---")

if tipo_geral == "Saida":
    naturezas = saidas_df["natureza"].unique().tolist()
    natureza  = st.selectbox("Natureza", naturezas)
    tipos     = saidas_df[saidas_df["natureza"] == natureza]["tipo"].unique().tolist()
    categoria = st.selectbox("Categoria", tipos)
    itens     = saidas_df[
        (saidas_df["natureza"] == natureza) &
        (saidas_df["tipo"] == categoria)
    ]["item"].dropna().tolist()
    item      = st.selectbox("Item", itens) if itens else None
    pagamento = st.selectbox("Forma de pagamento", pagamentos)
else:
    ent_filtrada = entradas_df[entradas_df["quem"] == quem]
    naturezas    = ent_filtrada["natureza"].unique().tolist() or entradas_df["natureza"].unique().tolist()
    natureza     = st.selectbox("Natureza", naturezas)
    tipos        = entradas_df[entradas_df["natureza"] == natureza]["tipo"].unique().tolist()
    categoria    = st.selectbox("Tipo de Entrada", tipos)
    item         = None
    pagamento    = None

valor = st.number_input("Valor (SGD)", min_value=0.0, value=None, step=1.0,
                        format="%.2f", placeholder="Digite o valor...")

requer_obs = categoria in CATS_COM_OBS
if requer_obs:
    st.caption("Esta categoria requer uma observacao.")
    observacao = st.text_area("Observacao (obrigatoria)")
else:
    observacao = st.text_area("Observacao (opcional)") if st.checkbox("Adicionar observacao") else None

st.markdown("---")
col_con, col_reg = st.columns(2)
with col_con:
    consultar = st.button("Consultar Saldo", use_container_width=True)
with col_reg:
    registrar = st.button("Registrar", use_container_width=True, type="primary")

# ── CONSULTAR ─────────────────────────────────────────────────────────────
if consultar:
    if tipo_geral == "Entrada":
        st.info("Consulta de saldo e apenas para Saidas.")
    elif natureza == "Profissional":
        st.info("Categoria Profissional - sem limite de orcamento.")
    else:
        s     = get_consulta_saldo(categoria, item, nro_mes, 2026)
        chave = f"{categoria} / {item}" if item else categoria

        if s["disponivel_mes"] == 0 and s["orc_mes"] == 0:
            st.warning(f"Sem orcamento para **{chave}**. Gasto atual: SGD {s['gasto_mes']:,.0f}.")
        else:
            v         = valor or 0
            resta_mes = s["disponivel_mes"] - s["gasto_mes"] - v
            saldo_ano = s["saldo_ano"] - v
            perc      = ((s["gasto_mes"] + v) / s["disponivel_mes"] * 100) if s["disponivel_mes"] > 0 else 0

            gasto_total = s["gasto_mes"] + v
            if gasto_total <= s["rollover"]:
                contexto = f"Usando rollover de meses anteriores (SGD {s['rollover']:,.0f} acumulado)."
            elif gasto_total <= s["disponivel_mes"]:
                contexto = f"Usando rollover + orcamento de {mes_nome}."
            else:
                antecipado = gasto_total - s["disponivel_mes"]
                contexto = f"Antecipando SGD {antecipado:,.0f} do orcamento de meses futuros."

            if v > 0:
                msg = (
                    f"**{chave} - {mes_nome}**\n\n"
                    f"Com o gasto de SGD {v:,.0f}, voce tera **SGD {max(resta_mes,0):,.0f}** "
                    f"para gastar esse mes ({100-perc:.1f}% do disponivel de SGD {s['disponivel_mes']:,.0f}) "
                    f"e **SGD {max(saldo_ano,0):,.0f}** esse ano.\n\n"
                    f"{contexto}"
                )
            else:
                msg = (
                    f"**{chave} - {mes_nome}**\n\n"
                    f"- Disponivel este mes: SGD {s['disponivel_mes']-s['gasto_mes']:,.0f} "
                    f"(orcado SGD {s['orc_mes']:,.0f} + rollover SGD {s['rollover']:,.0f})\n"
                    f"- Ja gasto este mes: SGD {s['gasto_mes']:,.0f}\n"
                    f"- Disponivel ate Dezembro: SGD {s['saldo_ano']:,.0f}\n\n"
                    f"{contexto}"
                )

            if resta_mes < 0:
                st.warning(msg)
            elif perc > 80:
                st.info(msg)
            else:
                st.success(msg)

# ── REGISTRAR ─────────────────────────────────────────────────────────────
if registrar:
    if not valor:
        st.error("Insira um valor valido!")
    elif requer_obs and not observacao:
        st.error("Esta categoria requer uma observacao!")
    else:
        dados = {
            "data": date.today(), "mes": mes_nome, "ano": 2026,
            "quem": quem, "tipo_geral": tipo_geral, "natureza": natureza,
            "categoria": categoria, "item": item, "valor": valor,
            "pagamento": pagamento, "observacao": observacao, "nro_mes": nro_mes,
        }
        try:
            inserir_lancamento(dados)
            chave = f"{categoria} / {item}" if item else categoria

            if tipo_geral == "Entrada":
                total_ano = get_total_ano(categoria, item, 2026)
                st.session_state.feedback_msg = (
                    f"Entrada de SGD {valor:,.0f} em {chave} registrada!\n\n"
                    f"Total acumulado no ano: SGD {total_ano:,.0f}."
                )
                st.session_state.feedback_cor = "success"

            elif natureza == "Profissional":
                st.session_state.feedback_msg = (
                    f"Gasto Profissional de SGD {valor:,.0f} em {chave} registrado.\n\n"
                    f"A aguardar reembolso."
                )
                st.session_state.feedback_cor = "success"

            else:
                s         = get_consulta_saldo(categoria, item, nro_mes, 2026)
                resta_mes = s["disponivel_mes"] - s["gasto_mes"]
                saldo_ano = s["saldo_ano"]
                perc      = (s["gasto_mes"] / s["disponivel_mes"] * 100) if s["disponivel_mes"] > 0 else 0

                gasto_total = s["gasto_mes"]
                if gasto_total <= s["rollover"]:
                    contexto = f"Usando rollover acumulado (SGD {s['rollover']:,.0f})."
                elif gasto_total <= s["disponivel_mes"]:
                    contexto = f"Usando rollover + orcamento de {mes_nome}."
                else:
                    antecipado = gasto_total - s["disponivel_mes"]
                    contexto = f"Antecipando SGD {antecipado:,.0f} de meses futuros."

                msg = (
                    f"SGD {valor:,.0f} em **{chave}** registrado!\n\n"
                    f"Com o gasto de SGD {valor:,.0f}, voce tera **SGD {max(resta_mes,0):,.0f}** "
                    f"para gastar esse mes e **SGD {max(saldo_ano,0):,.0f}** esse ano.\n\n"
                    f"{contexto}"
                )
                st.session_state.feedback_msg = msg
                st.session_state.feedback_cor = "warning" if resta_mes < 0 else ("info" if perc > 80 else "success")

            st.session_state.modo = "sucesso"
            st.rerun()

        except Exception as e:
            st.error(f"Erro ao registrar: {e}")

# ── Ultimos lancamentos ───────────────────────────────────────────────────
st.markdown("---")
st.subheader("Ultimos 10 lancamentos")
df = get_lancamentos(ano=2026)
if not df.empty:
    df_show = df[["data","mes","quem","tipo_geral","natureza",
                  "categoria","item","valor","pagamento"]].head(10)
    df_show.columns = ["Data","Mes","Quem","Tipo","Natureza",
                       "Categoria","Item","Valor","Pagamento"]
    st.dataframe(df_show, use_container_width=True, hide_index=True)
else:
    st.info("Nenhum lancamento encontrado.")