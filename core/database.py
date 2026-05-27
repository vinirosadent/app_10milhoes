"""
Camada de acesso ao Postgres (Supabase) do App 10M.

A partir da Etapa 3 (multi-usuario), TODAS as queries em tabelas tenant-
isoladas (lancamentos, orcamento, config_saidas, config_entradas) precisam
filtrar por household_id. O isolamento real entre households (Admin =
Vinicius+Juliana; Ladroes = Ricardo+Josi) e feito AQUI, no codigo, via
filtro WHERE household_id = ?. A RLS do Postgres serve apenas como rede
de seguranca defensiva (block do role anon), porque o psycopg2 conecta
como role com BYPASSRLS.

Convencoes:
  - Tabelas globais (meses, formas_pagamento, households) — sem filtro de tenant.
  - Tabelas tenant-isoladas — toda funcao publica ou recebe household_id explicito
    ou faz fallback para get_current_household_id() do session_state.
  - INSERTs preenchem household_id automaticamente a partir do session_state.
  - UPDATEs e DELETEs sempre incluem AND household_id = ? no WHERE, para impedir
    que um bug de codigo permita afetar dados de outro household.

Conexao via SESSION POOLER + sslmode=require (decisao fixa do projeto — Direct
Connection falha por IPv6 no host onde o Streamlit Cloud roda).
"""
import os
import psycopg2
import psycopg2.extras
import pandas as pd
from dotenv import load_dotenv
from pathlib import Path

from core.auth import get_current_household_id

load_dotenv(Path(__file__).parent.parent / ".env")

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "dbname":   os.getenv("DB_NAME", "app10milhoes"),
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "sslmode":  "require",
}


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def query_df(sql, params=None):
    conn = get_conn()
    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()
    return df


def execute(sql, params=None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


def _hh(household_id=None) -> int:
    """
    Resolve household_id: usa o explicito se passado, senao puxa do session_state.
    Levanta RuntimeError se nao houver usuario logado (vide core/auth.py).
    """
    if household_id is not None:
        return int(household_id)
    return get_current_household_id()


# ── MESES (global) ────────────────────────────────────────────────────────
def get_meses():
    return query_df("SELECT nro, nome FROM meses ORDER BY nro")


def get_ultimo_mes(household_id=None):
    """Ultimo mes com lancamento no household atual (para sugerir no form)."""
    hh = _hh(household_id)
    df = query_df(
        "SELECT mes FROM lancamentos WHERE household_id=%s ORDER BY criado_em DESC LIMIT 1",
        [hh],
    )
    return df["mes"].values[0] if not df.empty else None


# ── HOUSEHOLDS ────────────────────────────────────────────────────────────
def get_households():
    """Lista todos os households (global — usado em telas administrativas)."""
    return query_df("SELECT id, nome FROM households ORDER BY id")


def get_household_nome(household_id):
    df = query_df("SELECT nome FROM households WHERE id=%s", [int(household_id)])
    return df["nome"].values[0] if not df.empty else f"Household {household_id}"


# ── CONFIG SAIDAS ─────────────────────────────────────────────────────────
def get_config_saidas(esconder_quitadas_do_ano=None, household_id=None):
    """
    Retorna categorias de saida do household atual com colunas:
      natureza, tipo, item, ordem, anual, quitado_ano.

    esconder_quitadas_do_ano=2026 omite as anuais ja quitadas em 2026 (uso comum
    em listas que filtram "o que ainda esta ativo no orcamento").
    """
    hh = _hh(household_id)
    sql = "SELECT natureza, tipo, item, ordem, anual, quitado_ano FROM config_saidas WHERE household_id=%s"
    params = [hh]
    if esconder_quitadas_do_ano is not None:
        sql += " AND NOT (anual = TRUE AND quitado_ano = %s)"
        params.append(esconder_quitadas_do_ano)
    sql += " ORDER BY natureza, ordem, item"
    return query_df(sql, params)


def get_categorias_anuais(household_id=None):
    """Lista de tipos (str) marcados como anuais no household atual."""
    hh = _hh(household_id)
    return query_df(
        "SELECT DISTINCT tipo FROM config_saidas WHERE household_id=%s AND anual = TRUE ORDER BY tipo",
        [hh],
    )["tipo"].tolist()


def get_categorias_quitadas_no_ano(ano, household_id=None):
    """Lista de tipos (str) de categorias anuais ja quitadas no ano informado, no household atual."""
    hh = _hh(household_id)
    return query_df(
        "SELECT DISTINCT tipo FROM config_saidas "
        "WHERE household_id=%s AND anual = TRUE AND quitado_ano = %s ORDER BY tipo",
        [hh, ano],
    )["tipo"].tolist()


def is_categoria_anual(tipo, household_id=None):
    """True se a categoria 'tipo' esta marcada como anual no household atual."""
    hh = _hh(household_id)
    df = query_df(
        "SELECT anual FROM config_saidas WHERE household_id=%s AND tipo = %s LIMIT 1",
        [hh, tipo],
    )
    return bool(df["anual"].values[0]) if not df.empty else False


def set_categoria_anual(tipo, anual, household_id=None):
    """Liga/desliga flag 'anual' de TODAS as linhas do tipo no household atual."""
    hh = _hh(household_id)
    execute(
        "UPDATE config_saidas SET anual = %s WHERE household_id=%s AND tipo = %s",
        [anual, hh, tipo],
    )


def quitar_categoria(tipo, ano, household_id=None):
    hh = _hh(household_id)
    execute(
        "UPDATE config_saidas SET quitado_ano = %s WHERE household_id=%s AND tipo = %s",
        [ano, hh, tipo],
    )


def desquitar_categoria(tipo, household_id=None):
    hh = _hh(household_id)
    execute(
        "UPDATE config_saidas SET quitado_ano = NULL WHERE household_id=%s AND tipo = %s",
        [hh, tipo],
    )


# ── CONFIG ENTRADAS ───────────────────────────────────────────────────────
def get_config_entradas(household_id=None):
    hh = _hh(household_id)
    return query_df(
        "SELECT quem, natureza, tipo, requer_comentario FROM config_entradas "
        "WHERE household_id=%s ORDER BY natureza, tipo",
        [hh],
    )


# ── FORMAS DE PAGAMENTO (global) ──────────────────────────────────────────
def get_formas_pagamento():
    return query_df("SELECT nome FROM formas_pagamento ORDER BY nome")


# ── LANCAMENTOS ───────────────────────────────────────────────────────────
def inserir_lancamento(d, household_id=None):
    """
    Insere lancamento. household_id e preenchido automaticamente do session_state
    se nao passado explicitamente — chamadas das pages/ nao precisam saber dele.
    """
    hh = _hh(household_id)
    sql = """
        INSERT INTO lancamentos
            (data, mes, ano, quem, tipo_geral, natureza, quem_resp,
             categoria, item, valor, pagamento, observacao, valor_real, nro_mes, household_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    valor_real = d["valor"] if d["tipo_geral"] == "Entrada" else -d["valor"]
    execute(sql, (
        d["data"], d["mes"], d["ano"], d["quem"], d["tipo_geral"],
        d["natureza"], d["quem"], d["categoria"], d.get("item"),
        d["valor"], d.get("pagamento"), d.get("observacao"),
        valor_real, d["nro_mes"], hh,
    ))


def get_lancamentos(ano=2026, quem=None, tipo_geral=None, natureza=None, household_id=None):
    hh = _hh(household_id)
    sql = "SELECT * FROM lancamentos WHERE household_id=%s AND ano = %s"
    params = [hh, ano]
    if quem:
        sql += " AND quem = %s"; params.append(quem)
    if tipo_geral:
        sql += " AND tipo_geral = %s"; params.append(tipo_geral)
    if natureza:
        sql += " AND natureza = %s"; params.append(natureza)
    sql += " ORDER BY data DESC"
    return query_df(sql, params)


def update_lancamento(id, campos, household_id=None):
    """Atualiza lancamento; AND household_id no WHERE previne afetar dados de outro tenant."""
    hh = _hh(household_id)
    sets = ", ".join([f"{k} = %s" for k in campos.keys()])
    execute(
        f"UPDATE lancamentos SET {sets} WHERE id = %s AND household_id = %s",
        list(campos.values()) + [id, hh],
    )


def delete_lancamento(id, household_id=None):
    hh = _hh(household_id)
    execute("DELETE FROM lancamentos WHERE id = %s AND household_id = %s", [id, hh])


def delete_lancamentos(ids, household_id=None):
    hh = _hh(household_id)
    execute(
        "DELETE FROM lancamentos WHERE id = ANY(%s) AND household_id = %s",
        [ids, hh],
    )


# ── CONSULTA DE SALDO ─────────────────────────────────────────────────────
def get_consulta_saldo(categoria, item, nro_mes, ano, household_id=None):
    hh = _hh(household_id)
    item_q = item if item else None

    # Orcamento mes atual
    orc_mes = float(query_df(
        "SELECT COALESCE(SUM(valor),0) AS v FROM orcamento "
        "WHERE household_id=%s AND tipo=%s AND (item=%s OR item IS NULL) AND nro_mes=%s AND ano=%s",
        [hh, categoria, item_q, nro_mes, ano]
    )["v"].values[0])

    # Gasto mes atual
    gasto_mes = float(query_df(
        "SELECT COALESCE(SUM(valor),0) AS v FROM lancamentos "
        "WHERE household_id=%s AND tipo_geral='Saida' AND categoria=%s AND nro_mes=%s AND ano=%s",
        [hh, categoria, nro_mes, ano]
    )["v"].values[0])

    # Rollover: orcado - gasto de todos os meses anteriores
    orc_ant = float(query_df(
        "SELECT COALESCE(SUM(valor),0) AS v FROM orcamento "
        "WHERE household_id=%s AND tipo=%s AND (item=%s OR item IS NULL) AND nro_mes<%s AND ano=%s",
        [hh, categoria, item_q, nro_mes, ano]
    )["v"].values[0])
    gasto_ant = float(query_df(
        "SELECT COALESCE(SUM(valor),0) AS v FROM lancamentos "
        "WHERE household_id=%s AND tipo_geral='Saida' AND categoria=%s AND nro_mes<%s AND ano=%s",
        [hh, categoria, nro_mes, ano]
    )["v"].values[0])
    rollover = orc_ant - gasto_ant

    disponivel_mes = rollover + orc_mes

    orc_restante = float(query_df(
        "SELECT COALESCE(SUM(valor),0) AS v FROM orcamento "
        "WHERE household_id=%s AND tipo=%s AND (item=%s OR item IS NULL) AND nro_mes>=%s AND ano=%s",
        [hh, categoria, item_q, nro_mes, ano]
    )["v"].values[0])

    gasto_ano = float(query_df(
        "SELECT COALESCE(SUM(valor),0) AS v FROM lancamentos "
        "WHERE household_id=%s AND tipo_geral='Saida' AND categoria=%s AND ano=%s",
        [hh, categoria, ano]
    )["v"].values[0])

    orc_ano = float(query_df(
        "SELECT COALESCE(SUM(valor),0) AS v FROM orcamento "
        "WHERE household_id=%s AND tipo=%s AND (item=%s OR item IS NULL) AND ano=%s",
        [hh, categoria, item_q, ano]
    )["v"].values[0])

    saldo_ano = orc_ano - gasto_ano

    return {
        "orc_mes":         orc_mes,
        "gasto_mes":       gasto_mes,
        "rollover":        rollover,
        "disponivel_mes":  disponivel_mes,
        "orc_ano":         orc_ano,
        "gasto_ano":       gasto_ano,
        "saldo_ano":       saldo_ano,
        "orc_restante":    orc_restante,
    }


def get_total_ano(categoria, item, ano, household_id=None):
    hh = _hh(household_id)
    return float(query_df(
        "SELECT COALESCE(SUM(valor),0) AS v FROM lancamentos "
        "WHERE household_id=%s AND tipo_geral='Saida' AND categoria=%s AND (item=%s OR item IS NULL) AND ano=%s",
        [hh, categoria, item if item else None, ano]
    )["v"].values[0])


# ── ORCAMENTO ─────────────────────────────────────────────────────────────
def get_orcamento_matrix(ano=2026, household_id=None):
    hh = _hh(household_id)
    return query_df(
        "SELECT natureza, tipo, nro_mes, valor FROM orcamento "
        "WHERE household_id=%s AND ano=%s ORDER BY natureza, tipo, nro_mes",
        [hh, ano],
    )


def set_orcamento_mes(natureza, tipo, nro_mes, ano, valor, household_id=None):
    """
    UPDATE-then-INSERT atomico em escopo de household. A race condition descrita
    em [[project-indice-orcamento-divergencia]] continua existindo mas e ainda
    mais improvavel agora (so colide se 2 usuarios DO MESMO household editarem
    a mesma celula simultaneamente).
    """
    hh = _hh(household_id)
    execute(
        "UPDATE orcamento SET valor=%s "
        "WHERE household_id=%s AND natureza=%s AND tipo=%s AND nro_mes=%s AND ano=%s AND item IS NULL",
        [valor, hh, natureza, tipo, nro_mes, ano],
    )
    execute(
        "INSERT INTO orcamento (natureza, tipo, item, nro_mes, ano, valor, household_id) "
        "SELECT %s,%s,NULL,%s,%s,%s,%s "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM orcamento "
        "  WHERE household_id=%s AND natureza=%s AND tipo=%s AND nro_mes=%s AND ano=%s AND item IS NULL"
        ")",
        [natureza, tipo, nro_mes, ano, valor, hh,
         hh, natureza, tipo, nro_mes, ano],
    )


def set_orcamento_daqui_em_diante(natureza, tipo, nro_mes_inicio, ano, valor, household_id=None):
    hh = _hh(household_id)
    for m in range(nro_mes_inicio, 13):
        set_orcamento_mes(natureza, tipo, m, ano, valor, household_id=hh)


def set_orcamento_anual(natureza, tipo, ano, valor_anual, household_id=None):
    hh = _hh(household_id)
    for m in range(1, 13):
        set_orcamento_mes(natureza, tipo, m, ano, round(valor_anual/12, 2), household_id=hh)


def get_categorias_orcamento(ano=2026, household_id=None):
    hh = _hh(household_id)
    return query_df(
        "SELECT DISTINCT natureza, tipo FROM orcamento "
        "WHERE household_id=%s AND ano=%s ORDER BY natureza, tipo",
        [hh, ano],
    )


def get_orcamento_vs_realizado(ano=2026, nro_mes=None, esconder_quitadas_anteriores=False,
                                household_id=None):
    """
    Resumo orcado vs gasto por categoria do household atual. Colunas:
    natureza, tipo, orcado, gasto, saldo, anual, quitado_ano, orcado_anual.

    Mantém a logica complexa de "anual usa orcado anual completo, recorrente
    mensal usa acumulado ate o mes N" — apenas adiciona filtro household_id em
    todas as CTEs (orcamento, config_saidas via cs_agg, lancamentos).
    """
    hh = _hh(household_id)

    if nro_mes:
        sql = """
            WITH cs_agg AS (
                SELECT tipo,
                       BOOL_OR(anual)   AS anual,
                       MAX(quitado_ano) AS quitado_ano
                FROM config_saidas
                WHERE household_id = %s
                GROUP BY tipo
            ),
            orc_calc AS (
                SELECT
                    org.natureza,
                    org.tipo,
                    cs.anual,
                    cs.quitado_ano,
                    SUM(
                        CASE
                            WHEN cs.anual = TRUE          THEN org.valor
                            WHEN org.nro_mes <= %s        THEN org.valor
                            ELSE 0
                        END
                    ) AS orcado,
                    SUM(org.valor) AS orcado_anual
                FROM orcamento org
                LEFT JOIN cs_agg cs ON cs.tipo = org.tipo
                WHERE org.household_id = %s AND org.ano = %s
                GROUP BY org.natureza, org.tipo, cs.anual, cs.quitado_ano
            ),
            gasto_calc AS (
                SELECT categoria, SUM(valor) AS gasto
                FROM lancamentos
                WHERE household_id = %s
                  AND tipo_geral = 'Saida' AND ano = %s AND nro_mes <= %s
                GROUP BY categoria
            )
            SELECT
                o.natureza,
                o.tipo,
                o.orcado,
                COALESCE(g.gasto, 0)              AS gasto,
                o.orcado - COALESCE(g.gasto, 0)   AS saldo,
                COALESCE(o.anual, FALSE)          AS anual,
                o.quitado_ano,
                o.orcado_anual
            FROM orc_calc o
            LEFT JOIN gasto_calc g ON g.categoria = o.tipo
            ORDER BY o.natureza, o.tipo
        """
        df = query_df(sql, [hh, nro_mes, hh, ano, hh, ano, nro_mes])

        if esconder_quitadas_anteriores and not df.empty:
            quitadas_no_ano = df[
                (df["anual"] == True) & (df["quitado_ano"] == ano)
            ]["tipo"].tolist()

            if quitadas_no_ano:
                df_primeiro_pgto = query_df(
                    "SELECT categoria, MIN(nro_mes) AS primeiro_mes_pago "
                    "FROM lancamentos "
                    "WHERE household_id=%s AND tipo_geral='Saida' AND ano=%s AND categoria = ANY(%s) "
                    "GROUP BY categoria",
                    [hh, ano, quitadas_no_ano],
                )
                if not df_primeiro_pgto.empty:
                    ja_pagas_antes = df_primeiro_pgto[
                        df_primeiro_pgto["primeiro_mes_pago"] < nro_mes
                    ]["categoria"].tolist()
                    df = df[~df["tipo"].isin(ja_pagas_antes)]
        return df

    else:
        sql = """
            WITH cs_agg AS (
                SELECT tipo,
                       BOOL_OR(anual)   AS anual,
                       MAX(quitado_ano) AS quitado_ano
                FROM config_saidas
                WHERE household_id = %s
                GROUP BY tipo
            )
            SELECT
                o.natureza,
                o.tipo,
                o.orcado,
                COALESCE(l.gasto, 0)              AS gasto,
                o.orcado - COALESCE(l.gasto, 0)   AS saldo,
                COALESCE(cs.anual, FALSE)         AS anual,
                cs.quitado_ano,
                o.orcado                          AS orcado_anual
            FROM (
                SELECT natureza, tipo, SUM(valor) AS orcado
                FROM orcamento WHERE household_id = %s AND ano = %s
                GROUP BY natureza, tipo
            ) o
            LEFT JOIN cs_agg cs ON cs.tipo = o.tipo
            LEFT JOIN (
                SELECT categoria, SUM(valor) AS gasto
                FROM lancamentos
                WHERE household_id = %s AND tipo_geral = 'Saida' AND ano = %s
                GROUP BY categoria
            ) l ON l.categoria = o.tipo
            ORDER BY o.natureza, o.tipo
        """
        return query_df(sql, [hh, hh, ano, hh, ano])


# ── USUARIOS ──────────────────────────────────────────────────────────────
def autenticar_usuario(login, senha):
    """
    Verifica credenciais. Aceita `login` como nome (ex: 'admin', 'ladrons') OU
    como email completo (ex: 'admin@10milhoes.local') — torna o login mais
    amigavel para o modelo simples de 2 logins compartilhados.

    Retorna dict com os dados do usuario (incluindo household_id e household_nome)
    se bater, ou None caso contrario. Importa verify_password localmente para
    evitar ciclo de import.
    """
    if not login or not senha:
        return None
    from core.auth import verify_password

    login_norm = login.strip().lower()
    df = query_df(
        "SELECT id, nome, email, papel, household_id, password_hash, ativo "
        "FROM usuarios WHERE LOWER(nome) = %s OR LOWER(email) = %s LIMIT 1",
        [login_norm, login_norm],
    )
    if df.empty:
        return None
    row = df.iloc[0]
    if not bool(row["ativo"]):
        return None
    if not row["password_hash"]:
        return None  # usuario sem senha configurada nunca loga
    if not verify_password(senha, str(row["password_hash"])):
        return None

    hh_id = int(row["household_id"]) if pd.notna(row["household_id"]) else None
    hh_nome = get_household_nome(hh_id) if hh_id else "—"

    return {
        "id":             int(row["id"]),
        "nome":           row["nome"],
        "email":          row["email"],
        "papel":          row["papel"],
        "household_id":   hh_id,
        "household_nome": hh_nome,
    }


def get_membros_household(household_id=None):
    """
    Lista de nomes (str) que aparecem no select "quem" do form de Lancamentos
    e nos filtros do Dashboard/Configuracoes.

    No modelo de 2 logins (Admin e Ladron), cada login e usado por 2 pessoas que
    nao tem usuario proprio — Vinicius e Juliana usam Admin; Ricardo e Josi usam
    Ladron. A lista de nomes mora em `households.membros` (text[]) e e a fonte
    autoritativa do que aparece no select.

    Retorna a lista ordenada alfabeticamente. Se a coluna estiver vazia, retorna
    lista vazia — a UI faz fallback para "-".
    """
    hh = _hh(household_id)
    df = query_df("SELECT membros FROM households WHERE id = %s", [hh])
    if df.empty:
        return []
    membros = df["membros"].iloc[0]
    if membros is None:
        return []
    return sorted(list(membros))


def resetar_senha(id, nova_senha, household_id=None):
    """
    Reset de senha do login atual (Admin ou Ladron). No modelo de 2 logins, o
    proprio usuario troca a propria senha em Configuracoes -> Minha senha.
    Mantido household_id no WHERE como defesa em profundidade (impede um codigo
    bugado de resetar a senha do outro login por engano).
    """
    from core.auth import hash_password
    hh = _hh(household_id)
    novo_hash = hash_password(nova_senha)
    execute(
        "UPDATE usuarios SET password_hash = %s WHERE id = %s AND household_id = %s",
        [novo_hash, id, hh],
    )


# ── DASHBOARD ─────────────────────────────────────────────────────────────
def get_resumo_mensal(ano=2026, quem=None, natureza=None, household_id=None):
    hh = _hh(household_id)
    sql = """
        SELECT l.nro_mes, m.nome AS mes,
            SUM(CASE WHEN l.tipo_geral='Entrada' THEN l.valor ELSE 0 END) AS entradas,
            SUM(CASE WHEN l.tipo_geral='Saida'   THEN l.valor ELSE 0 END) AS saidas,
            SUM(CASE WHEN l.tipo_geral='Entrada' THEN l.valor ELSE 0 END) -
            SUM(CASE WHEN l.tipo_geral='Saida'   THEN l.valor ELSE 0 END) AS saldo
        FROM lancamentos l
        JOIN meses m ON m.nro = l.nro_mes
        WHERE l.household_id=%s AND l.ano=%s
    """
    params = [hh, ano]
    if quem:     sql += " AND l.quem=%s";     params.append(quem)
    if natureza: sql += " AND l.natureza=%s"; params.append(natureza)
    return query_df(sql + " GROUP BY l.nro_mes, m.nome ORDER BY l.nro_mes", params)


def get_gastos_por_categoria(ano=2026, nro_mes=None, quem=None, natureza=None, household_id=None):
    hh = _hh(household_id)
    sql = "SELECT categoria, SUM(valor) AS total FROM lancamentos WHERE household_id=%s AND tipo_geral='Saida' AND ano=%s"
    params = [hh, ano]
    if nro_mes:  sql += " AND nro_mes=%s";  params.append(nro_mes)
    if quem:     sql += " AND quem=%s";     params.append(quem)
    if natureza: sql += " AND natureza=%s"; params.append(natureza)
    return query_df(sql + " GROUP BY categoria ORDER BY total DESC", params)


def get_gastos_mensais_por_pessoa(ano=2026, natureza=None, household_id=None):
    hh = _hh(household_id)
    sql = """
        SELECT l.nro_mes, m.nome AS mes, l.quem, SUM(l.valor) AS total
        FROM lancamentos l
        JOIN meses m ON m.nro = l.nro_mes
        WHERE l.household_id=%s AND l.tipo_geral='Saida' AND l.ano=%s
    """
    params = [hh, ano]
    if natureza: sql += " AND l.natureza=%s"; params.append(natureza)
    return query_df(sql + " GROUP BY l.nro_mes, m.nome, l.quem ORDER BY l.nro_mes, l.quem", params)


def get_gastos_por_pessoa(ano=2026, nro_mes=None, natureza=None, household_id=None):
    hh = _hh(household_id)
    sql = "SELECT quem, SUM(valor) AS total FROM lancamentos WHERE household_id=%s AND tipo_geral='Saida' AND ano=%s"
    params = [hh, ano]
    if nro_mes:  sql += " AND nro_mes=%s";  params.append(nro_mes)
    if natureza: sql += " AND natureza=%s"; params.append(natureza)
    return query_df(sql + " GROUP BY quem ORDER BY total DESC", params)


def get_saldo_acumulado(ano=2026, natureza=None, household_id=None):
    hh = _hh(household_id)
    where_nat = "AND l.natureza=%s" if natureza else ""
    params    = [hh, ano] + ([natureza] if natureza else [])
    return query_df(f"""
        SELECT sub.nro_mes, m.nome AS mes,
            SUM(sub.valor_real) OVER (ORDER BY sub.nro_mes) AS saldo_acumulado
        FROM (
            SELECT nro_mes, SUM(valor_real) AS valor_real
            FROM lancamentos l WHERE household_id=%s AND ano=%s {where_nat}
            GROUP BY nro_mes
        ) sub
        JOIN meses m ON m.nro = sub.nro_mes
        ORDER BY sub.nro_mes
    """, params)
