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
    get_usuarios, inserir_usuario, update_usuario, toggle_usuario_ativo,
    set_quitado,
)

CATEGORIAS_QUITAVEIS = {"Seguro Saúde", "Seguro Viagem", "Imposto Juliana"}

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
            df_vr.columns = ["Natureza","Categoria","orcado","gasto","saldo"]
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
                st.divider()

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

            if tipo_sel in CATEGORIAS_QUITAVEIS:
                cfg_saidas = get_config_saidas()
                row_cfg    = cfg_saidas[
                    (cfg_saidas["natureza"] == nat_sel) &
                    (cfg_saidas["tipo"] == tipo_sel)
                ]
                estado_atual = bool(row_cfg["quitado"].any()) if not row_cfg.empty else False
                novo_estado  = st.checkbox(
                    "✅ Conta quitada (paga à vista) — oculta a categoria nos meses posteriores ao pagamento",
                    value=estado_atual,
                    key=f"quitado_{nat_sel}_{tipo_sel}",
                )
                if novo_estado != estado_atual:
                    set_quitado(nat_sel, tipo_sel, novo_estado)
                    st.session_state["orc_msg"] = (
                        f"✅ **{tipo_sel}** marcada como quitada."
                        if novo_estado else
                        f"↩️ **{tipo_sel}** desmarcada como quitada."
                    )
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

        if st.button("➕ Criar Orçamento Anual", type="primary", key="btn_nova_orc"):
            if not valor_anual:
                st.error("Insira um valor anual.")
            else:
                nat  = nova_cat.split(" / ")[0]
                tipo = nova_cat.split(" / ")[1]
                set_orcamento_anual(nat, tipo, 2026, valor_anual)
                st.success(f"SGD {valor_anual:,.0f}/ano criado para {nova_cat} (SGD {valor_anual/12:,.0f}/mês)")
                st.rerun()

# ══════════════════════════════════════════════════════════════════════════
# SECAO 2 — USUARIOS
# ══════════════════════════════════════════════════════════════════════════
with st.expander("👥 Usuários", expanded=False):

    tab_lista, tab_novo = st.tabs(["👥 Lista", "➕ Novo Usuário"])

    # ── TAB 1: Lista de usuários ──────────────────────────────────────────
    with tab_lista:
        df_users = get_usuarios()

        if df_users.empty:
            st.info("Nenhum usuário cadastrado.")
        else:
            for _, u in df_users.iterrows():
                col_info, col_tipo, col_papel, col_status, col_acao = st.columns([2,1,1,1,2])

                with col_info:
                    st.markdown(f"**{u['nome']}**")
                with col_tipo:
                    tipo_label = "🏠 Permanente" if u["tipo"] == "permanente" else "🧳 Temporário"
                    st.caption(tipo_label)
                with col_papel:
                    papel_label = "⭐ Admin" if u["papel"] == "admin" else "👤 Membro"
                    st.caption(papel_label)
                with col_status:
                    if u["ativo"]:
                        st.markdown("🟢 Ativo")
                    else:
                        st.markdown("🔴 Inativo")
                with col_acao:
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if u["ativo"]:
                            if st.button("Inativar", key=f"inativar_{u['id']}", use_container_width=True):
                                toggle_usuario_ativo(u["id"], False)
                                st.rerun()
                        else:
                            if st.button("Reativar", key=f"reativar_{u['id']}", type="primary", use_container_width=True):
                                toggle_usuario_ativo(u["id"], True)
                                st.rerun()
                    with col_b:
                        if st.button("Editar", key=f"editar_u_{u['id']}", use_container_width=True):
                            st.session_state["editar_usuario_id"] = int(u["id"])

                # Formulário de edição inline
                if st.session_state.get("editar_usuario_id") == u["id"]:
                    with st.container():
                        st.markdown("---")
                        ec1, ec2, ec3 = st.columns(3)
                        with ec1:
                            novo_nome  = st.text_input("Nome",  value=u["nome"],  key=f"u_nome_{u['id']}")
                        with ec2:
                            novo_papel = st.selectbox("Papel", ["admin","membro"],
                                index=0 if u["papel"]=="admin" else 1, key=f"u_papel_{u['id']}")
                        with ec3:
                            novo_tipo  = st.selectbox("Tipo", ["permanente","temporario"],
                                index=0 if u["tipo"]=="permanente" else 1, key=f"u_tipo_{u['id']}")

                        cs, cc = st.columns(2)
                        with cs:
                            if st.button("💾 Salvar", type="primary", key=f"u_salvar_{u['id']}", use_container_width=True):
                                update_usuario(u["id"], {"nome": novo_nome, "papel": novo_papel, "tipo": novo_tipo})
                                st.session_state["editar_usuario_id"] = None
                                st.success("Usuário atualizado!")
                                st.rerun()
                        with cc:
                            if st.button("Cancelar", key=f"u_cancel_{u['id']}", use_container_width=True):
                                st.session_state["editar_usuario_id"] = None
                                st.rerun()
                        st.markdown("---")

                st.divider()

    # ── TAB 2: Novo usuário ───────────────────────────────────────────────
    with tab_novo:
        with st.form("form_novo_usuario", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            with col1:
                novo_nome  = st.text_input("Nome", placeholder="Ex: Maria")
            with col2:
                novo_papel = st.selectbox("Papel", ["membro","admin"])
            with col3:
                novo_tipo  = st.selectbox("Tipo", ["permanente","temporario"],
                    help="Temporário: visita ou morador por período limitado")
            submitted = st.form_submit_button("➕ Adicionar Usuário", type="primary", use_container_width=True)

        if submitted:
            if not novo_nome.strip():
                st.error("Digite um nome.")
            else:
                try:
                    inserir_usuario(novo_nome.strip(), novo_papel, novo_tipo)
                    st.success(f"✅ Usuário **{novo_nome}** cadastrado com sucesso!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")

# ══════════════════════════════════════════════════════════════════════════
# SECAO 3 — LANCAMENTOS
# ══════════════════════════════════════════════════════════════════════════
with st.expander("📋 Gerenciar Lançamentos", expanded=False):

    meses_df    = get_meses()
    meses_lista = ["Todos"] + meses_df["nome"].tolist()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        filtro_mes  = st.selectbox("Mês", meses_lista, key="cfg_mes")
    with col2:
        filtro_tipo = st.selectbox("Tipo", ["Todos","Saida","Entrada"], key="cfg_tipo")
    with col3:
        filtro_quem = st.selectbox("Quem", ["Todos","Vinicius","Juliana"], key="cfg_quem")
    with col4:
        filtro_nat  = st.selectbox("Natureza", ["Todos","Pessoal","Profissional","Investimento"], key="cfg_nat")

    df = get_lancamentos(
        ano=2026,
        quem=None if filtro_quem == "Todos" else filtro_quem,
        tipo_geral=None if filtro_tipo == "Todos" else filtro_tipo,
        natureza=None if filtro_nat == "Todos" else filtro_nat,
    )
    if filtro_mes != "Todos":
        df = df[df["mes"] == filtro_mes]

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
            st.subheader(f"✏️ Editando lançamento #{eid}")
            c1, c2, c3 = st.columns(3)
            with c1:
                nova_cat  = st.text_input("Categoria", value=str(row["categoria"] or ""), key="e_cat")
                novo_item = st.text_input("Item",       value=str(row["item"] or ""),      key="e_item")
            with c2:
                novo_val  = st.number_input("Valor", value=float(row["valor"]),
                                            min_value=0.0, format="%.0f", key="e_val")
                novo_pgto = st.text_input("Pagamento", value=str(row["pagamento"] or ""), key="e_pgto")
            with c3:
                nova_obs  = st.text_area("Observação", value=str(row["observacao"] or ""), key="e_obs")

            cs, cc = st.columns(2)
            with cs:
                if st.button("💾 Salvar", type="primary", use_container_width=True, key="btn_salvar_lan"):
                    valor_real = novo_val if row["tipo_geral"] == "Entrada" else -novo_val
                    update_lancamento(eid, {
                        "categoria": nova_cat, "item": novo_item or None,
                        "valor": novo_val, "pagamento": novo_pgto or None,
                        "observacao": nova_obs or None, "valor_real": valor_real,
                    })
                    st.session_state["editar_id"] = None
                    st.success("Lançamento atualizado!")
                    st.rerun()
            with cc:
                if st.button("Cancelar", use_container_width=True, key="btn_cancel_lan"):
                    st.session_state["editar_id"] = None
                    st.rerun()