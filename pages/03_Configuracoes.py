import streamlit as st
import sys
import pandas as pd
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from core.database import (
    get_lancamentos, get_meses, update_lancamento,
    delete_lancamentos, get_config_saidas,
    get_orcamento_matrix, set_orcamento_mes,
    set_orcamento_daqui_em_diante, set_orcamento_anual,
    get_categorias_orcamento, get_orcamento_vs_realizado,
    # Etapa 3 (revisao): 2 logins (Admin/Ladron) — so resetar_senha e lista de membros.
    resetar_senha, get_membros_household,
    # Funcoes do novo modelo de quitacao (anual + quitado_ano):
    is_categoria_anual, set_categoria_anual,
    quitar_categoria, desquitar_categoria
)
from core.auth import get_current_user

# Ano corrente da aplicacao (hardcoded por enquanto, ver project_app10milhoes.md).
ANO_APP = 2026

st.set_page_config(page_title="Configuracoes", page_icon="🔧", layout="wide")
st.title("🔧 Configurações")

MESES = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
         "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]

# ══════════════════════════════════════════════════════════════════════════
# SECAO 1 — ORCAMENTO
# ══════════════════════════════════════════════════════════════════════════
with st.expander("💰 Orçamento", expanded=True):

    tab_visao, tab_editar, tab_nova = st.tabs([
        "📊 Visão Geral", "✏️ Editar", "➕ Nova Categoria"
    ])

    # ── TAB 1: Visão Geral ────────────────────────────────────────────────
    with tab_visao:
        # Filtros
        col_ano, col_mes = st.columns([1, 3])
        with col_ano:
            ano_sel = st.selectbox("Ano", [2026], key="orc_ano")
        with col_mes:
            mes_opcoes   = ["Todos os meses"] + MESES
            mes_sel_vr   = st.selectbox("Mês", mes_opcoes, key="orc_mes")

        nro_mes_sel    = None if mes_sel_vr == "Todos os meses" else MESES.index(mes_sel_vr) + 1
        titulo_periodo = mes_sel_vr if mes_sel_vr != "Todos os meses" else f"Ano {ano_sel} (agregado)"

        df_vr = get_orcamento_vs_realizado(ano_sel, nro_mes_sel)

        if df_vr.empty:
            st.info("Nenhum orçamento definido. Importe do Sheets ou adicione uma categoria.")
        else:
            # A funcao agora retorna 7 colunas (natureza, tipo, orcado, gasto, saldo, anual, quitado_ano).
            # Renomeia apenas as duas primeiras para manter compatibilidade com o resto do bloco.
            df_vr = df_vr.rename(columns={"natureza": "Natureza", "tipo": "Categoria"})
            df_vr["orcado"] = df_vr["orcado"].round(0).astype(int)
            df_vr["gasto"]  = df_vr["gasto"].round(0).astype(int)
            df_vr["saldo"]  = df_vr["saldo"].round(0).astype(int)
            df_vr["perc"]   = (df_vr["gasto"] / df_vr["orcado"].replace(0,1) * 100).round(0).astype(int)

            # KPIs
            st.markdown(f"##### {titulo_periodo}")
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Orçado", f"SGD {df_vr['orcado'].sum():,}")
            col2.metric("Total Gasto",  f"SGD {df_vr['gasto'].sum():,}")
            saldo_total = int(df_vr["saldo"].sum())
            col3.metric("Saldo",        f"SGD {saldo_total:,}",
                        delta="sobra" if saldo_total >= 0 else "deficit")

            st.markdown("---")

            # Cards por categoria com barra de progresso
            for _, row in df_vr.iterrows():
                perc  = min(int(row["perc"]), 100)
                cor   = "#2E7D32" if row["perc"] <= 80 else ("#E65100" if row["perc"] <= 100 else "#C62828")
                emoji = "✅" if row["perc"] <= 80 else ("⚠️" if row["perc"] <= 100 else "🔴")

                col_nome, col_bar, col_nums = st.columns([2, 3, 3])
                with col_nome:
                    st.markdown(f"**{row['Categoria']}**")
                    st.caption(row["Natureza"])
                with col_bar:
                    st.markdown(f"""
                        <div style="margin-top:8px">
                            <div style="background:#E0E7EF;border-radius:8px;height:14px;width:100%">
                                <div style="background:{cor};border-radius:8px;height:14px;width:{perc}%"></div>
                            </div>
                            <small style="color:{cor};font-weight:600">{emoji} {row['perc']}% utilizado</small>
                        </div>
                    """, unsafe_allow_html=True)
                with col_nums:
                    st.markdown(
                        f"<div style='margin-top:4px;font-size:13px'>"
                        f"Orçado: <b>SGD {row['orcado']:,}</b> &nbsp;|&nbsp; "
                        f"Gasto: <b>SGD {row['gasto']:,}</b> &nbsp;|&nbsp; "
                        f"Saldo: <b style='color:{cor}'>SGD {row['saldo']:,}</b>"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                st.markdown('<hr style="margin:4px 0;border:none;border-top:1px solid #E0E7EF">', unsafe_allow_html=True)

    # ── TAB 2: Editar ─────────────────────────────────────────────────────
    with tab_editar:
        # Mostra mensagem de sucesso se vier de uma acao anterior
        if st.session_state.get("orc_msg"):
            st.success(st.session_state["orc_msg"])
            st.session_state["orc_msg"] = None
        df_cats = get_categorias_orcamento(2026)

        if df_cats.empty:
            st.info("Nenhuma categoria com orçamento ainda.")
        else:
            cats_lista = [f"{r['natureza']} / {r['tipo']}" for _, r in df_cats.iterrows()]

            col1, col2 = st.columns(2)
            with col1:
                cat_sel  = st.selectbox("Categoria", cats_lista, key="edit_cat")
            with col2:
                mes_sel  = st.selectbox("A partir de qual mês?", MESES, key="edit_mes")

            nat_sel  = cat_sel.split(" / ")[0]
            tipo_sel = cat_sel.split(" / ")[1]
            nro_mes  = MESES.index(mes_sel) + 1

            # ── Toggle "categoria anual" ──
            # Permite marcar/desmarcar a categoria como anual (lump sum) direto na
            # edicao do orcamento. Categorias anuais aparecem com orcado anual
            # completo no BI e podem ser quitadas no form de Lancamentos — depois
            # de quitadas, somem dos meses subsequentes ao pagamento.
            anual_atual = is_categoria_anual(tipo_sel)
            novo_anual = st.checkbox(
                "💡 É despesa anual (paga uma vez por ano em lump sum)",
                value=anual_atual,
                key=f"edit_anual_{tipo_sel}",
                help="Ex.: seguro saúde, imposto Juliana. Marca a categoria como anual."
            )
            if novo_anual != anual_atual:
                set_categoria_anual(tipo_sel, novo_anual)
                # Se desmarcou anual, tambem limpa o estado de quitacao (que so
                # faz sentido para categorias anuais).
                if not novo_anual:
                    desquitar_categoria(tipo_sel)
                rotulo = "anual" if novo_anual else "recorrente mensal"
                st.session_state["orc_msg"] = f"✅ Categoria **{tipo_sel}** marcada como {rotulo}."
                st.rerun()

            df_atual = get_orcamento_matrix(2026)
            df_atual = df_atual[
                (df_atual["natureza"] == nat_sel) &
                (df_atual["tipo"] == tipo_sel) &
                (df_atual["nro_mes"] == nro_mes)
            ]
            val_atual = float(df_atual["valor"].values[0]) if not df_atual.empty else 0.0

            novo_valor = st.number_input(
                f"Novo valor para {mes_sel} (atual: SGD {val_atual:,.0f})",
                min_value=0.0, value=val_atual, step=50.0, format="%.0f",
                key="edit_val"
            )

            aplicar = st.radio("Aplicar a:", [
                "Só este mês",
                "Este mês e todos os seguintes (até Dezembro)"
            ], key="edit_modo")

            if st.button("💾 Salvar Alteração", type="primary", key="btn_salvar_orc"):
                if aplicar == "Só este mês":
                    set_orcamento_mes(nat_sel, tipo_sel, nro_mes, 2026, novo_valor)
                    st.session_state["orc_msg"] = f"✅ Orçamento de **{cat_sel}** em **{mes_sel}** atualizado para SGD {novo_valor:,.0f}."
                else:
                    set_orcamento_daqui_em_diante(nat_sel, tipo_sel, nro_mes, 2026, novo_valor)
                    st.session_state["orc_msg"] = f"✅ Orçamento de **{cat_sel}** de **{mes_sel}** a Dezembro atualizado para SGD {novo_valor:,.0f}/mês."
                st.rerun()

    # ── TAB 3: Nova Categoria ─────────────────────────────────────────────
    with tab_nova:
        saidas_df  = get_config_saidas()
        cats_disp  = saidas_df[["natureza","tipo"]].drop_duplicates()
        cats_lista = [f"{r['natureza']} / {r['tipo']}" for _, r in cats_disp.iterrows()]

        col1, col2 = st.columns(2)
        with col1:
            nova_cat = st.selectbox("Categoria", cats_lista, key="nova_cat")
        with col2:
            valor_anual = st.number_input(
                "Orçamento anual (SGD)", min_value=0.0, step=100.0,
                format="%.0f", value=None, placeholder="Ex: 9600", key="nova_val"
            )

        if valor_anual:
            st.caption(f"SGD {valor_anual/12:,.0f}/mês")

        # Checkbox para ja criar a categoria como anual (lump sum) — pode ser
        # alterado depois na aba Editar.
        marcar_anual = st.checkbox(
            "💡 Esta é uma despesa anual (paga uma vez por ano em lump sum)",
            value=False,
            key="nova_anual",
            help="Ex.: seguro saúde, imposto Juliana. Pode ser quitada no form de Lancamentos."
        )

        if st.button("➕ Criar Orçamento Anual", type="primary", key="btn_nova_orc"):
            if not valor_anual:
                st.error("Insira um valor anual.")
            else:
                nat  = nova_cat.split(" / ")[0]
                tipo = nova_cat.split(" / ")[1]
                set_orcamento_anual(nat, tipo, ANO_APP, valor_anual)
                if marcar_anual:
                    set_categoria_anual(tipo, True)
                rotulo_anual = " (marcada como anual)" if marcar_anual else ""
                st.success(
                    f"SGD {valor_anual:,.0f}/ano criado para {nova_cat}"
                    f" (SGD {valor_anual/12:,.0f}/mês){rotulo_anual}"
                )
                st.rerun()

# ══════════════════════════════════════════════════════════════════════════
# SECAO 2 — CONTAS ANUAIS (gestao de quitacao)
# ══════════════════════════════════════════════════════════════════════════
with st.expander("🎯 Contas Anuais", expanded=False):
    st.markdown(
        "Categorias **anuais** (lump sum) sao pagas uma vez por ano em vez de "
        "mensalmente — ex.: seguro saúde, imposto Juliana, seguro viagem.\n\n"
        "Para marcar uma categoria como anual, vá em **💰 Orçamento → ✏️ Editar** "
        "(checkbox \"💡 É despesa anual\").\n\n"
        "Quando uma categoria anual é **quitada** num determinado ano, ela some do "
        "BI dos meses **posteriores** ao pagamento. No mês do pagamento ela ainda "
        "aparece (mostrando orçado anual vs gasto). Você pode quitar/desquitar aqui, "
        "ou marcar \"quitar\" diretamente no form de Lançamentos ao registrar o pagamento."
    )
    st.markdown("---")

    df_saidas   = get_config_saidas()
    cats_anuais = df_saidas[df_saidas["anual"] == True][
        ["natureza", "tipo", "quitado_ano"]
    ].drop_duplicates("tipo")

    if cats_anuais.empty:
        st.info(
            "Nenhuma categoria marcada como anual ainda. "
            "Vá em **💰 Orçamento → ✏️ Editar** ou **➕ Nova Categoria** e marque "
            "o checkbox \"💡 É despesa anual\"."
        )
    else:
        cols_header = st.columns([3, 2, 2, 2])
        cols_header[0].markdown("**Categoria**")
        cols_header[1].markdown("**Natureza**")
        cols_header[2].markdown(f"**Status {ANO_APP}**")
        cols_header[3].markdown("**Ação**")
        st.divider()

        for _, row in cats_anuais.iterrows():
            col_cat, col_nat, col_status, col_acao = st.columns([3, 2, 2, 2])
            col_cat.markdown(f"**{row['tipo']}**")
            col_nat.caption(row["natureza"])

            # quitado_ano e' INT64 (pandas) ou NaN — converter pra int comparavel
            quitado = row["quitado_ano"]
            quitada_neste_ano = (
                pd.notna(quitado) and int(quitado) == ANO_APP
            )

            if quitada_neste_ano:
                col_status.markdown(f"✅ Quitada em {ANO_APP}")
                if col_acao.button(
                    "↩️ Desquitar",
                    key=f"desquitar_{row['tipo']}",
                    help="Volta a aparecer no BI dos meses pós-pagamento",
                    use_container_width=True,
                ):
                    desquitar_categoria(row["tipo"])
                    st.success(f"Categoria **{row['tipo']}** desquitada.")
                    st.rerun()
            else:
                col_status.markdown("⏳ Aguardando pagamento")
                if col_acao.button(
                    "✅ Quitar agora",
                    key=f"quitar_{row['tipo']}",
                    type="primary",
                    help=f"Marca como quitada em {ANO_APP} (some dos meses pós-pagamento)",
                    use_container_width=True,
                ):
                    quitar_categoria(row["tipo"], ANO_APP)
                    st.success(f"Categoria **{row['tipo']}** marcada como quitada em {ANO_APP}.")
                    st.rerun()
            st.divider()

# ══════════════════════════════════════════════════════════════════════════
# SECAO 3 — MINHA SENHA (Etapa 3 — modelo de 2 logins)
#
# O App 10M tem 2 logins compartilhados: Admin (Vinicius+Juliana usam o mesmo
# login) e Ladron (Ricardo+Josi usam o mesmo). Por isso nao existe cadastro
# de "novo usuario" pela UI — a unica acao util aqui e trocar a propria senha
# do login compartilhado. A coluna `quem` nos lancamentos continua diferenciando
# Vinicius vs Juliana (e Ric vs Josi) — vide households.membros, populado pela
# migration consolidate_users_to_two_logins.
# ══════════════════════════════════════════════════════════════════════════
with st.expander("🔑 Minha senha", expanded=False):

    user_logado = get_current_user()

    st.caption(
        f"Você está logado como **{user_logado['nome']}** "
        f"({user_logado['email']}) no household **{user_logado['household_nome']}** — "
        f"que cobre os lançamentos de: {', '.join(get_membros_household())}."
    )
    st.markdown("---")

    with st.form("form_minha_senha", clear_on_submit=True):
        nova1 = st.text_input("Nova senha", type="password", key="minha_sen_1",
                              help="Mínimo 4 caracteres.")
        nova2 = st.text_input("Confirme a nova senha", type="password", key="minha_sen_2")
        trocar = st.form_submit_button("🔑 Trocar senha do login " + user_logado["nome"],
                                       type="primary", use_container_width=True)

    if trocar:
        if len(nova1) < 4:
            st.error("Senha deve ter ao menos 4 caracteres.")
        elif nova1 != nova2:
            st.error("As senhas não coincidem.")
        else:
            resetar_senha(user_logado["id"], nova1)
            st.success(
                f"✅ Senha do login **{user_logado['nome']}** atualizada. "
                "Use a nova senha no próximo login. Avise o outro membro do household "
                "se ele também usa este login."
            )

# ══════════════════════════════════════════════════════════════════════════
# SECAO 4 — LANCAMENTOS
# ══════════════════════════════════════════════════════════════════════════
with st.expander("📋 Gerenciar Lançamentos", expanded=False):

    meses_df    = get_meses()
    meses_lista = ["Todos"] + meses_df["nome"].tolist()

    # Monta a lista de categorias disponiveis a partir das config tables.
    # Inclui tanto categorias de saida quanto de entrada para o filtro ser util
    # independente do tipo de lancamento selecionado.
    # get_formas_pagamento entra junto porque o form de edicao mais abaixo
    # precisa popular o dropdown de Pagamento com a tabela canonica.
    from core.database import get_config_entradas, get_formas_pagamento, CATS_INVESTIMENTO
    cats_saida   = get_config_saidas()["tipo"].dropna().unique().tolist()
    cats_entrada = get_config_entradas()["tipo"].dropna().unique().tolist()
    # Categorias do modulo de investimentos entram no filtro para os registros
    # (aportes/dividendos/saldo inicial) serem localizaveis aqui tambem —
    # para households sem o modulo nao ha registros, o filtro so nao retorna nada.
    cats_filtro  = ["Todas"] + sorted(set(cats_saida + cats_entrada + CATS_INVESTIMENTO))

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        filtro_mes  = st.selectbox("Mês", meses_lista, key="cfg_mes")
    with col2:
        filtro_tipo = st.selectbox("Tipo", ["Todos","Saida","Entrada","Investimento"], key="cfg_tipo")
    with col3:
        # "Quem" derivado dinamicamente do household ativo (Etapa 3).
        membros_lan = ["Todos"] + get_membros_household()
        filtro_quem = st.selectbox("Quem", membros_lan, key="cfg_quem")
    with col4:
        filtro_nat  = st.selectbox("Natureza", ["Todos","Pessoal","Profissional","Investimento"], key="cfg_nat")
    with col5:
        filtro_cat  = st.selectbox("Categoria", cats_filtro, key="cfg_cat")

    df = get_lancamentos(
        ano=ANO_APP,
        quem=None if filtro_quem == "Todos" else filtro_quem,
        tipo_geral=None if filtro_tipo == "Todos" else filtro_tipo,
        natureza=None if filtro_nat == "Todos" else filtro_nat,
    )
    if filtro_mes != "Todos":
        df = df[df["mes"] == filtro_mes]
    if filtro_cat != "Todas":
        # Filtra direto no DataFrame (mais simples que estender get_lancamentos
        # com mais um parametro — esta seção so visualiza, nao consulta volume grande).
        df = df[df["categoria"] == filtro_cat]

    if df.empty:
        st.info("Nenhum lançamento encontrado.")
    else:
        cols_show = ["id","data","mes","quem","tipo_geral","natureza",
                     "categoria","item","valor","pagamento","observacao"]
        df_show = df[cols_show].copy()
        df_show["valor"] = df_show["valor"].round(0).astype(int)
        df_show.insert(0, "Selecionar", False)

        st.markdown(f"**{len(df_show)} lançamentos encontrados**")

        edited = st.data_editor(
            df_show, use_container_width=True, hide_index=True,
            disabled=["id","data","mes","quem","tipo_geral","natureza",
                      "categoria","item","valor","pagamento","observacao"],
            column_config={
                "Selecionar": st.column_config.CheckboxColumn("✔",        width="small"),
                "id":         st.column_config.NumberColumn("ID",         width="small"),
                "data":       st.column_config.DateColumn("Data",         width="small"),
                "mes":        st.column_config.TextColumn("Mês",          width="small"),
                "quem":       st.column_config.TextColumn("Quem",         width="small"),
                "tipo_geral": st.column_config.TextColumn("Tipo",         width="small"),
                "natureza":   st.column_config.TextColumn("Natureza",     width="small"),
                "categoria":  st.column_config.TextColumn("Categoria"),
                "item":       st.column_config.TextColumn("Item"),
                "valor":      st.column_config.NumberColumn("Valor",      format="SGD %d"),
                "pagamento":  st.column_config.TextColumn("Pagamento"),
                "observacao": st.column_config.TextColumn("Obs"),
            }
        )

        selecionados = edited[edited["Selecionar"] == True]
        ids_sel = selecionados["id"].tolist()
        n_sel   = len(ids_sel)

        st.markdown("---")
        col_del, col_edit, _ = st.columns([1,1,3])

        with col_del:
            st.markdown('<div class="danger-btn">', unsafe_allow_html=True)
            deletar = st.button(f"🗑️ Remover ({n_sel})", disabled=n_sel==0,
                                use_container_width=True, key="btn_del_lan")
            st.markdown('</div>', unsafe_allow_html=True)

        with col_edit:
            editar = st.button("✏️ Editar", disabled=n_sel!=1,
                               use_container_width=True, type="primary", key="btn_edit_lan")

        if deletar:
            st.session_state["confirmar_delete"] = True

        if st.session_state.get("confirmar_delete"):
            st.warning(f"Remover {n_sel} lançamento(s)? Esta ação não pode ser desfeita.")
            cs, cn = st.columns(2)
            with cs:
                st.markdown('<div class="danger-btn">', unsafe_allow_html=True)
                if st.button("Sim, remover", use_container_width=True, key="btn_sim_del"):
                    delete_lancamentos(ids_sel)
                    st.session_state["confirmar_delete"] = False
                    st.success(f"{n_sel} lançamento(s) removido(s).")
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
            with cn:
                if st.button("Cancelar", use_container_width=True, key="btn_nao_del"):
                    st.session_state["confirmar_delete"] = False
                    st.rerun()

        if editar:
            st.session_state["editar_id"] = int(ids_sel[0])

        if st.session_state.get("editar_id"):
            eid = st.session_state["editar_id"]
            row = df[df["id"] == eid].iloc[0]
            st.markdown("---")

            # ── Guard: registros do modulo de investimentos nao se editam aqui.
            # Os dropdowns em cascata abaixo sao alimentados por config_saidas/
            # config_entradas — que nao contem as categorias de investimento.
            # Editar um aporte/dividendo por aqui trocaria a categoria por uma
            # de gasto/renda silenciosamente (alem de recalcular valor_real
            # errado para aportes, que devem ter valor_real=0).
            eh_investimento = (
                row["tipo_geral"] == "Investimento"
                or row["categoria"] == "Dividendos"
            )
            if eh_investimento:
                st.info(
                    "💎 Este é um registro do módulo de **Investimentos**. "
                    "Para corrigir: remova-o (aqui ou na página Investimentos → "
                    "🗂️ Registros do ano) e registre novamente lá."
                )
                if st.button("OK, fechar", key="btn_fechar_edit_inv"):
                    st.session_state["editar_id"] = None
                    st.rerun()
                # Esta secao e a ultima da pagina — interromper aqui nao
                # esconde nenhum conteudo posterior.
                st.stop()

            st.subheader(f"✏️ Editando lançamento #{eid}")

            # Helper: campos NULL no Postgres voltam como NaN no pandas.
            # str(NaN or "") devolve "nan" (string literal), o que vazava como
            # placeholder feio nos inputs. pd.notna() resolve o NULL/NaN corretamente.
            def _safe(val):
                return str(val) if pd.notna(val) else ""

            # ── Carrega as config tables para popular os dropdowns em cascata.
            #    Mesma logica do form de Novo Lancamento (pages/01_Lancamentos.py):
            #    Saida   = natureza → categoria → item + pagamento
            #    Entrada = natureza → categoria (sem item, sem pagamento)
            #    Antes os campos eram text_input livres, o que permitia digitar
            #    categoria inexistente e quebrar a relacao com config_saidas
            #    (gasto sem orcamento, item invalido, etc.).
            edit_saidas_df   = get_config_saidas()
            edit_entradas_df = get_config_entradas()
            edit_pagamentos  = get_formas_pagamento()["nome"].tolist()

            tipo_geral_row = row["tipo_geral"]
            cfg_df = edit_saidas_df if tipo_geral_row == "Saida" else edit_entradas_df

            # Keys com sufixo do eid forcam re-render quando se troca o
            # lancamento sendo editado — sem isso o st.session_state mantem
            # o valor do dropdown da edicao anterior e ignora o `index=`.
            k = lambda nome: f"e_{nome}_{eid}"

            c1, c2, c3 = st.columns(3)
            with c1:
                # Natureza — base da cascata.
                naturezas_disp = cfg_df["natureza"].dropna().unique().tolist()
                nat_atual = _safe(row["natureza"])
                nat_idx = naturezas_disp.index(nat_atual) if nat_atual in naturezas_disp else 0
                nova_nat = st.selectbox(
                    "Natureza", naturezas_disp, index=nat_idx, key=k("nat")
                )

                # Categoria filtrada pela natureza atual do widget.
                cats_disp = cfg_df[cfg_df["natureza"] == nova_nat]["tipo"].dropna().unique().tolist()
                cat_atual = _safe(row["categoria"])
                cat_idx = cats_disp.index(cat_atual) if cat_atual in cats_disp else 0
                nova_cat = st.selectbox(
                    "Categoria", cats_disp, index=cat_idx, key=k("cat")
                ) if cats_disp else None

                # Item so existe para Saidas e quando ha itens cadastrados
                # para essa combinacao natureza/tipo em config_saidas.
                if tipo_geral_row == "Saida" and nova_cat:
                    itens_disp = cfg_df[
                        (cfg_df["natureza"] == nova_nat) &
                        (cfg_df["tipo"] == nova_cat)
                    ]["item"].dropna().tolist()
                else:
                    itens_disp = []

                if itens_disp:
                    item_atual = _safe(row["item"])
                    item_idx = itens_disp.index(item_atual) if item_atual in itens_disp else 0
                    novo_item = st.selectbox(
                        "Item", itens_disp, index=item_idx, key=k("item")
                    )
                else:
                    novo_item = None

            with c2:
                novo_val = st.number_input(
                    "Valor", value=float(row["valor"]),
                    min_value=0.0, format="%.0f", key=k("val")
                )
                # Pagamento so faz sentido para Saida.
                if tipo_geral_row == "Saida":
                    pgto_atual = _safe(row["pagamento"])
                    pgto_idx = edit_pagamentos.index(pgto_atual) if pgto_atual in edit_pagamentos else 0
                    novo_pgto = st.selectbox(
                        "Pagamento", edit_pagamentos, index=pgto_idx, key=k("pgto")
                    )
                else:
                    novo_pgto = None

            with c3:
                nova_obs = st.text_area(
                    "Observação", value=_safe(row["observacao"]), key=k("obs")
                )

            cs, cc = st.columns(2)
            with cs:
                if st.button("💾 Salvar", type="primary", use_container_width=True, key="btn_salvar_lan"):
                    # natureza tambem vai no UPDATE: como agora pode ser
                    # alterada no dropdown, precisa ser persistida — senao
                    # ficaria divergente da categoria escolhida.
                    valor_real = novo_val if tipo_geral_row == "Entrada" else -novo_val
                    update_lancamento(eid, {
                        "natureza":   nova_nat,
                        "categoria":  nova_cat,
                        "item":       novo_item,
                        "valor":      novo_val,
                        "pagamento":  novo_pgto,
                        "observacao": nova_obs or None,
                        "valor_real": valor_real,
                    })
                    st.session_state["editar_id"] = None
                    st.success("Lançamento atualizado!")
                    st.rerun()
            with cc:
                if st.button("Cancelar", use_container_width=True, key="btn_cancel_lan"):
                    st.session_state["editar_id"] = None
                    st.rerun()