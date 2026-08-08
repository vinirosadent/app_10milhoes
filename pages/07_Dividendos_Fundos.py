# =============================================================================
# Pagina: Dividendos por Fundo
# App: app10milhoes (Streamlit + Supabase)
#
# O QUE ESTA PAGINA FAZ
# Ate jul/2026 os dividendos eram lancados como um valor unico por produto
# ("Manu 4k", "Manu 2k"). Agora cada produto e uma carteira de fundos, e cada
# fundo paga separado. Esta pagina tem tres partes:
#   1. Cadastro de fundos  -> voce diz QUAIS fundos existem em cada produto
#   2. Lancamento mensal   -> voce diz QUANTO cada fundo pagou no mes
#   3. Analise / BI        -> yield por fundo, evolucao, recebido vs reinvestido
#
# IMPORTANTE: o total por produto em investimentos_serie.dividendo e recalculado
# AUTOMATICAMENTE por um trigger no banco (trg_recalcular_dividendo) toda vez
# que um lancamento de fundo e inserido, alterado ou apagado. Esta pagina NUNCA
# escreve direto em investimentos_serie.
# =============================================================================

import datetime as dt
import sys
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pandas as pd
import streamlit as st

# -----------------------------------------------------------------------------
# CONEXAO COM O BANCO
# Reaproveita o helper de conexao ja existente no projeto: core/db.py, que e o
# unico ponto do app que abre conexao com o Postgres (Supabase).
#
# core.db.get_conn() devolve uma conexao psycopg2 CRUA e quem chama e
# responsavel por fechar (o app usa o Transaction Pooler, com o padrao
# abre-conexao -> 1 query -> fecha). O `with` nativo do psycopg2 fecha apenas a
# TRANSACAO, nao a conexao. Por isso o wrapper abaixo: mantem a sintaxe
# `with get_conn() as conn:` usada no resto da pagina e garante o close().
# -----------------------------------------------------------------------------
sys.path.append(str(Path(__file__).parent.parent))
from core.db import get_conn as _abrir_conexao  # noqa: E402
from core.db import _hh  # noqa: E402  household do usuario logado (session_state)


@contextmanager
def get_conn():
    """Abre uma conexao do projeto e fecha ao sair do bloco `with`."""
    conn = _abrir_conexao()
    try:
        yield conn
    finally:
        conn.close()


# Household: as demais paginas nao usam id fixo — o household vem do usuario
# logado (st.session_state), resolvido por core.db._hh() / core.auth. Mesmo
# padrao aqui, entao a pagina respeita o isolamento por household do app.

st.set_page_config(page_title="Dividendos", page_icon="💰", layout="wide")

MESES_NOME = {
    1: "Janeiro", 2: "Fevereiro", 3: "Marco", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


# =============================================================================
# CAMADA DE DADOS - leitura
# =============================================================================

def carregar_produtos_com_dividendo():
    """Produtos que distribuem dividendo (paga_dividendo = true).

    Produtos de acumulacao (Manu 1k) e os de rendimento (SRS, IBKR) ficam de
    fora: eles nao pagam dividendo e nao devem aparecer nesta pagina.
    """
    sql = """
        SELECT id, nome, ordem
        FROM config_investimentos
        WHERE household_id = %s AND ativo = true AND paga_dividendo = true
        ORDER BY ordem, nome
    """
    with get_conn() as conn:
        return pd.read_sql(sql, conn, params=(_hh(),))


def carregar_fundos(apenas_ativos=True):
    """Catalogo de fundos, com o nome do produto a que cada um pertence."""
    sql = """
        SELECT f.id, f.produto_id, c.nome AS produto, f.nome_fundo,
               f.ativo, f.ordem
        FROM fundos_investimento f
        JOIN config_investimentos c ON c.id = f.produto_id
        WHERE f.household_id = %s
    """
    if apenas_ativos:
        sql += " AND f.ativo = true"
    sql += " ORDER BY c.ordem, f.ordem, f.nome_fundo"
    with get_conn() as conn:
        return pd.read_sql(sql, conn, params=(_hh(),))


def carregar_lancamentos(ano, nro_mes):
    """Lancamentos ja registrados para um mes de competencia."""
    sql = """
        SELECT id, fundo_id, dividendo, unidades, taxa_distribuicao,
               data_pagamento, tipo_distribuicao, saldo
        FROM fundos_serie
        WHERE household_id = %s AND ano = %s AND nro_mes = %s
    """
    with get_conn() as conn:
        return pd.read_sql(sql, conn, params=(_hh(), ano, nro_mes))


def carregar_serie_completa():
    """Serie historica completa por fundo, ja com yield calculado pela view."""
    sql = """
        SELECT produto, nome_fundo, nome_curto, ano, nro_mes, mes, data_pagamento,
               tipo_distribuicao, dividendo, recebido_caixa, unidades,
               taxa_distribuicao, saldo, yield_mensal_pct, yield_anualizado_pct
        FROM vw_fundos_yield
        WHERE household_id = %s
        ORDER BY ano, nro_mes, produto, nome_fundo
    """
    with get_conn() as conn:
        return pd.read_sql(sql, conn, params=(_hh(),))


def carregar_conferencia():
    """Compara o total lancado a mao (legado) com a soma dos fundos.

    Serve de auditoria: enquanto nem todos os fundos de um mes estiverem
    lancados, a soma fica menor que o legado e o mes aparece aqui.
    """
    sql = """
        SELECT c.nome AS produto, s.ano, s.nro_mes,
               s.dividendo_legado AS lancado_mao,
               s.dividendo        AS soma_fundos,
               ROUND(s.dividendo - s.dividendo_legado, 2) AS diferenca
        FROM investimentos_serie s
        JOIN config_investimentos c ON c.id = s.produto_id
        WHERE s.household_id = %s
          AND s.dividendo_legado IS NOT NULL
          AND ABS(s.dividendo - s.dividendo_legado) > 1.5
        ORDER BY s.ano DESC, s.nro_mes DESC
    """
    with get_conn() as conn:
        return pd.read_sql(sql, conn, params=(_hh(),))


# =============================================================================
# CAMADA DE DADOS - escrita
# =============================================================================

def inserir_fundo(produto_id, nome_fundo, ordem):
    """Cadastra um fundo novo dentro de um produto."""
    sql = """
        INSERT INTO fundos_investimento
            (household_id, produto_id, nome_fundo, ativo, ordem)
        VALUES (%s, %s, %s, true, %s)
        ON CONFLICT (household_id, produto_id, nome_fundo) DO NOTHING
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (_hh(), produto_id, nome_fundo.strip(), ordem))
        conn.commit()


def alternar_fundo_ativo(fundo_id, ativo):
    """Ativa/desativa um fundo sem apagar o historico dele."""
    sql = "UPDATE fundos_investimento SET ativo = %s WHERE id = %s AND household_id = %s"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (ativo, fundo_id, _hh()))
        conn.commit()


def salvar_lancamento(fundo_id, ano, nro_mes, data_pagamento, unidades,
                      taxa_distribuicao, dividendo, tipo_distribuicao, saldo):
    """Grava (ou atualiza) o pagamento de um fundo.

    A chave natural e (household, fundo, data_pagamento): um fundo pode pagar
    mais de uma vez no mesmo mes -- foi o que aconteceu com o MGF em maio/2026
    (04/mai reinvestment e 29/mai payout).
    """
    sql = """
        INSERT INTO fundos_serie
            (household_id, fundo_id, ano, nro_mes, dividendo, unidades,
             taxa_distribuicao, data_pagamento, tipo_distribuicao, saldo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (household_id, fundo_id, data_pagamento)
        DO UPDATE SET
            ano = EXCLUDED.ano,
            nro_mes = EXCLUDED.nro_mes,
            dividendo = EXCLUDED.dividendo,
            unidades = EXCLUDED.unidades,
            taxa_distribuicao = EXCLUDED.taxa_distribuicao,
            tipo_distribuicao = EXCLUDED.tipo_distribuicao,
            saldo = EXCLUDED.saldo,
            atualizado_em = now()
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (_hh(), fundo_id, ano, nro_mes, dividendo,
                              unidades, taxa_distribuicao, data_pagamento,
                              tipo_distribuicao, saldo))
        conn.commit()


def apagar_lancamento(lancamento_id):
    """Remove um pagamento. O trigger recalcula o total do produto sozinho."""
    sql = "DELETE FROM fundos_serie WHERE id = %s AND household_id = %s"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (lancamento_id, _hh()))
        conn.commit()


# =============================================================================
# LOGICA PURA (sem banco, sem streamlit) - facil de testar
# =============================================================================

def calcular_dividendo(unidades, taxa_distribuicao):
    """dividendo = unidades * taxa por unidade, arredondado a 2 casas.

    Confere com os extratos: 2425.777 x 0.12 = 291.09 (abrdn, 03/ago/2026) e
    253067.006 x 0.005431 = 1374.41 (MGF, 03/ago/2026).
    """
    if unidades is None or taxa_distribuicao is None:
        return 0.0
    bruto = Decimal(str(unidades)) * Decimal(str(taxa_distribuicao))
    return float(round(bruto, 2))


def calcular_yield_anualizado(dividendo, saldo):
    """Yield anualizado simples: (dividendo mensal x 12) / account value."""
    if not saldo or saldo <= 0:
        return None
    return round(float(dividendo) * 12 / float(saldo) * 100, 4)


# =============================================================================
# INTERFACE
# =============================================================================

def render_cadastro_fundos(produtos):
    """Parte 1: o catalogo. Cadastrar aqui vem ANTES de lancar valores."""
    st.subheader("1. Cadastro de fundos")
    st.caption(
        "Cadastre uma vez quais fundos existem dentro de cada produto. "
        "Depois, todo mes, so preencha os valores na secao 2."
    )

    fundos = carregar_fundos(apenas_ativos=False)

    if fundos.empty:
        st.info("Nenhum fundo cadastrado ainda.")
    else:
        for _, prod in produtos.iterrows():
            do_produto = fundos[fundos["produto_id"] == prod["id"]]
            if do_produto.empty:
                continue
            st.markdown(f"**{prod['nome']}**")
            for _, f in do_produto.iterrows():
                col_nome, col_acao = st.columns([5, 1])
                marca = "" if f["ativo"] else "  _(inativo)_"
                col_nome.markdown(f"- {f['nome_fundo']}{marca}")
                rotulo = "Desativar" if f["ativo"] else "Reativar"
                if col_acao.button(rotulo, key=f"toggle_{f['id']}"):
                    alternar_fundo_ativo(f["id"], not f["ativo"])
                    st.rerun()

    with st.expander("Adicionar fundo"):
        with st.form("form_novo_fundo"):
            produto_sel = st.selectbox(
                "Produto",
                options=produtos["id"].tolist(),
                format_func=lambda i: produtos.loc[produtos["id"] == i, "nome"].iloc[0],
            )
            nome_novo = st.text_input(
                "Nome do fundo",
                placeholder="Ex.: Allianz Income and Growth AMI3 (H2-SGD) (AIGA2)",
            )
            ordem_nova = st.number_input("Ordem de exibicao", min_value=1, value=1, step=1)
            if st.form_submit_button("Cadastrar fundo"):
                if not nome_novo.strip():
                    st.error("Informe o nome do fundo.")
                else:
                    inserir_fundo(produto_sel, nome_novo, int(ordem_nova))
                    st.success(f"Fundo '{nome_novo.strip()}' cadastrado.")
                    st.rerun()


def render_lancamento_mensal(produtos):
    """Parte 2: preenchimento do mes, fundo a fundo."""
    st.subheader("2. Lancar dividendos do mes")

    hoje = dt.date.today()
    col_ano, col_mes = st.columns(2)
    ano = col_ano.number_input(
        "Ano de competencia", min_value=2023, max_value=2100, value=hoje.year, step=1
    )
    nro_mes = col_mes.selectbox(
        "Mes de competencia",
        options=list(range(1, 13)),
        index=hoje.month - 1,
        format_func=lambda m: MESES_NOME[m],
    )
    ano, nro_mes = int(ano), int(nro_mes)

    st.caption(
        "Competencia = o mes em que voce contabiliza o dividendo. Pode diferir "
        "da data do pagamento (o payout de 29/mai/2026 foi contabilizado em junho)."
    )

    fundos = carregar_fundos(apenas_ativos=True)
    if fundos.empty:
        st.warning("Cadastre ao menos um fundo na secao 1 antes de lancar valores.")
        return

    existentes = carregar_lancamentos(ano, nro_mes)
    # Um fundo pode ter MAIS DE UM pagamento na mesma competencia, entao cada
    # fundo mapeia para uma LISTA de lancamentos -- nunca para um so.
    por_fundo = {}
    if not existentes.empty:
        for registro in existentes.to_dict("records"):
            por_fundo.setdefault(registro["fundo_id"], []).append(registro)

    for _, prod in produtos.iterrows():
        do_produto = fundos[fundos["produto_id"] == prod["id"]]
        if do_produto.empty:
            continue

        st.markdown(f"### {prod['nome']}")
        for _, f in do_produto.iterrows():
            lancs = por_fundo.get(f["id"], [])
            titulo = f["nome_fundo"]
            if len(lancs) > 1:
                titulo += f"  ({len(lancs)} pagamentos)"
            with st.expander(titulo, expanded=not lancs):
                _render_pagamentos_existentes(f, lancs)
                _render_form_fundo(f, ano, nro_mes, lancs)

        soma = sum(
            float(l["dividendo"])
            for fid in do_produto["id"]
            for l in por_fundo.get(fid, [])
        )
        st.info(f"Total lancado em {prod['nome']} neste mes: **{soma:,.2f}**")


def _render_pagamentos_existentes(fundo, lancs):
    """Lista os pagamentos ja gravados do fundo nesta competencia, com opcao de apagar."""
    if not lancs:
        return
    st.caption("Pagamentos ja lancados nesta competencia:")
    for l in sorted(lancs, key=lambda r: r["data_pagamento"]):
        col_txt, col_del = st.columns([5, 1])
        rotulo_tipo = "recebido" if l["tipo_distribuicao"] == "payout" else "reinvestido"
        col_txt.markdown(
            f"- {l['data_pagamento']:%d/%m/%Y} - "
            f"**{float(l['dividendo']):,.2f}** ({rotulo_tipo})"
        )
        if col_del.button("Apagar", key=f"del_{l['id']}"):
            apagar_lancamento(l["id"])
            st.rerun()
    st.divider()


def _render_form_fundo(fundo, ano, nro_mes, lancs):
    """Formulario de UM pagamento. Calcula o dividendo a partir de unidades x taxa.

    Se ja existe pagamento na competencia, pre-preenche pelo mais recente. Salvar
    com uma data DIFERENTE cria um segundo pagamento em vez de sobrescrever --
    e o caso do MGF, que pagou em 04/mai e 29/mai de 2026.
    """
    anterior = max(lancs, key=lambda r: r["data_pagamento"]) if lancs else {}
    if lancs:
        st.caption("Para adicionar outro pagamento, mude a data antes de salvar.")
    with st.form(f"form_lanc_{fundo['id']}_{ano}_{nro_mes}"):
        col1, col2 = st.columns(2)

        data_pag = col1.date_input(
            "Data do pagamento",
            value=anterior.get("data_pagamento") or dt.date(ano, nro_mes, 1),
            key=f"data_{fundo['id']}",
        )
        tipo = col2.selectbox(
            "Tipo de distribuicao",
            options=["payout", "reinvestment"],
            index=0 if anterior.get("tipo_distribuicao", "payout") == "payout" else 1,
            format_func=lambda t: "Payout (dinheiro recebido)" if t == "payout"
            else "Reinvestment (reaplicado)",
            key=f"tipo_{fundo['id']}",
        )

        col3, col4 = st.columns(2)
        unidades = col3.number_input(
            "Fund units",
            min_value=0.0,
            value=float(anterior.get("unidades") or 0.0),
            step=0.001,
            format="%.3f",
            key=f"unid_{fundo['id']}",
        )
        taxa = col4.number_input(
            "Distribution rate (por unidade)",
            min_value=0.0,
            value=float(anterior.get("taxa_distribuicao") or 0.0),
            step=0.0000001,
            format="%.10f",
            key=f"taxa_{fundo['id']}",
        )

        calculado = calcular_dividendo(unidades, taxa)
        col5, col6 = st.columns(2)
        dividendo = col5.number_input(
            "Dividendo (calculado, pode sobrescrever)",
            min_value=0.0,
            value=calculado if calculado > 0 else float(anterior.get("dividendo") or 0.0),
            step=0.01,
            format="%.2f",
            key=f"div_{fundo['id']}",
        )
        saldo = col6.number_input(
            "Account value (opcional, base do yield)",
            min_value=0.0,
            value=float(anterior.get("saldo") or 0.0),
            step=0.01,
            format="%.2f",
            key=f"saldo_{fundo['id']}",
        )

        if calculado > 0:
            st.caption(f"unidades x taxa = {calculado:,.2f}")
        if saldo > 0:
            y = calcular_yield_anualizado(dividendo, saldo)
            st.caption(f"Yield anualizado estimado: {y:.2f}%")

        if st.form_submit_button("Salvar"):
            salvar_lancamento(
                fundo_id=int(fundo["id"]),
                ano=ano,
                nro_mes=nro_mes,
                data_pagamento=data_pag,
                unidades=unidades or None,
                taxa_distribuicao=taxa or None,
                dividendo=dividendo,
                tipo_distribuicao=tipo,
                saldo=saldo or None,
            )
            st.success("Lancamento salvo. Total do produto recalculado.")
            st.rerun()


def _competencia_incompleta(serie):
    """Retorna (competencia, faltam, esperado) do ultimo mes com lancamento parcial.

    A referencia e quantos fundos pagaram no MES ANTERIOR, nao quantos estao
    ativos. Isso importa: um fundo pode continuar ativo na carteira e parar de
    distribuir (fundo suspende dividendo). Comparando contra os fundos ativos,
    todo mes seguinte seria marcado como incompleto para sempre e sumiria das
    tendencias -- em silencio. Comparando contra o mes anterior, a expectativa
    cai sozinha no mes seguinte e a serie volta a andar.
    """
    if serie.empty:
        return None, 0, 0
    por_comp = serie.groupby("competencia")["nome_curto"].nunique().sort_index()
    if len(por_comp) < 2:
        return None, 0, 0
    ultima = por_comp.index[-1]
    lancaram = int(por_comp.iloc[-1])
    esperado = int(por_comp.iloc[-2])
    if lancaram >= esperado:
        return None, 0, esperado
    return ultima, esperado - lancaram, esperado


def render_analise():
    """Parte 3: o BI -- yield por fundo, evolucao e recebido vs reinvestido."""
    st.subheader("3. Analise por fundo")

    serie = carregar_serie_completa()
    if serie.empty:
        st.info("Sem lancamentos por fundo ainda.")
        return

    serie["competencia"] = (
        serie["ano"].astype(str) + "-" + serie["nro_mes"].astype(int).astype(str).str.zfill(2)
    )

    comp_parcial, faltam, total_fundos = _competencia_incompleta(serie)
    if comp_parcial:
        st.warning(
            f"**{comp_parcial} esta incompleto**: {faltam} de {total_fundos} fundos "
            "ainda nao lancaram. Os graficos abaixo excluem esse mes das tendencias "
            "para nao mostrar uma queda que nao existe."
        )

    # Serie usada nas TENDENCIAS: sem o mes parcial.
    serie_fechada = (
        serie[serie["competencia"] != comp_parcial] if comp_parcial else serie
    )

    # --- Yield atual por fundo (ultimo mes que tem account value informado) ---
    com_saldo = serie[serie["saldo"].notna()].copy()
    if not com_saldo.empty:
        ultimo = (
            com_saldo.sort_values(["ano", "nro_mes"])
            .groupby("nome_curto", as_index=False)
            .last()
        )
        meses_ref = sorted(ultimo["competencia"].unique())
        if len(meses_ref) > 1:
            st.caption(
                "Atencao: os fundos tem account value de meses diferentes ("
                + ", ".join(meses_ref)
                + "). A coluna 'Mes ref.' mostra a referencia de cada um."
            )
        st.markdown("**Yield anualizado por fundo**")
        st.dataframe(
            ultimo[["produto", "nome_curto", "competencia", "dividendo",
                    "saldo", "yield_anualizado_pct"]]
            .sort_values("yield_anualizado_pct", ascending=False)
            .rename(columns={
                "produto": "Produto",
                "nome_curto": "Fundo",
                "competencia": "Mes ref.",
                "dividendo": "Dividendo",
                "saldo": "Account value",
                "yield_anualizado_pct": "Yield anual (%)",
            }),
            use_container_width=True,
            hide_index=True,
        )
        st.bar_chart(ultimo.set_index("nome_curto")["yield_anualizado_pct"])

    # --- Evolucao do dividendo por fundo ---
    # SEM fillna(0): fundo que ainda nao estava na carteira fica com LACUNA, nao
    # com zero. Zero diria "esse fundo pagou nada", que e falso -- ele nem existia.
    st.markdown("**Evolucao do dividendo por fundo**")
    pivo = serie_fechada.pivot_table(
        index="competencia", columns="nome_curto", values="dividendo", aggfunc="sum"
    )
    st.line_chart(pivo)
    st.caption(
        "Lacuna na linha = o fundo ainda nao fazia parte da carteira naquele mes "
        "(nao e pagamento zero)."
    )

    # --- Recebido em caixa vs reinvestido ---
    st.markdown("**Recebido em caixa (payout) vs reinvestido**")
    resumo = serie_fechada.groupby("competencia", as_index=False).agg(
        total=("dividendo", "sum"),
        recebido=("recebido_caixa", "sum"),
    )
    resumo["reinvestido"] = resumo["total"] - resumo["recebido"]
    st.area_chart(resumo.set_index("competencia")[["recebido", "reinvestido"]])
    st.caption(
        "Ate mai/2026 tudo era reinvestido (nao entrava caixa). O payout comeca "
        "no pagamento de 29/05/2026."
    )

    # Os totais acumulados usam a serie COMPLETA (inclui o mes parcial): sao
    # somas historicas, e o que ja foi pago conta mesmo que o mes nao tenha fechado.
    total_recebido = serie["recebido_caixa"].sum()
    total_geral = serie["dividendo"].sum()
    col_a, col_b = st.columns(2)
    col_a.metric("Total recebido em caixa", f"{total_recebido:,.2f}")
    col_b.metric("Total gerado (inclui reinvestido)", f"{total_geral:,.2f}")

    # --- Conferencia contra o que foi lancado a mao antes da migracao ---
    st.markdown("**Conferencia: soma dos fundos vs total lancado a mao**")
    divergencias = carregar_conferencia()
    if divergencias.empty:
        st.success("Todos os meses batem com o total que voce havia lancado.")
    else:
        st.warning(
            "Meses em que a soma dos fundos difere do total antigo. "
            "Normalmente significa que falta lancar algum fundo."
        )
        st.dataframe(divergencias, use_container_width=True, hide_index=True)


def main():
    st.title("Dividendos por Fundo")
    st.caption(
        "Cada produto e uma carteira de fundos. Cadastre os fundos, lance o que "
        "cada um pagou, e o total do produto e recalculado automaticamente."
    )

    produtos = carregar_produtos_com_dividendo()
    if produtos.empty:
        st.error(
            "Nenhum produto marcado como pagador de dividendo. "
            "Verifique config_investimentos.paga_dividendo."
        )
        return

    aba_lanc, aba_cad, aba_bi = st.tabs(["Lancar mes", "Cadastro de fundos", "Analise"])
    with aba_lanc:
        render_lancamento_mensal(produtos)
    with aba_cad:
        render_cadastro_fundos(produtos)
    with aba_bi:
        render_analise()


main()
