import os
import psycopg2
import psycopg2.extras
import pandas as pd
from dotenv import load_dotenv
from pathlib import Path

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

# ── MESES ─────────────────────────────────────────────────────────────────
def get_meses():
    return query_df("SELECT nro, nome FROM meses ORDER BY nro")

def get_ultimo_mes():
    df = query_df("SELECT mes FROM lancamentos ORDER BY criado_em DESC LIMIT 1")
    return df["mes"].values[0] if not df.empty else None

# ── CONFIG ────────────────────────────────────────────────────────────────
def get_config_saidas():
    return query_df("SELECT natureza, tipo, item FROM config_saidas ORDER BY natureza, ordem, item")

def get_config_entradas():
    return query_df("SELECT quem, natureza, tipo, requer_comentario FROM config_entradas ORDER BY natureza, tipo")

def get_formas_pagamento():
    return query_df("SELECT nome FROM formas_pagamento ORDER BY nome")

# ── LANCAMENTOS ───────────────────────────────────────────────────────────
def inserir_lancamento(d):
    sql = """
        INSERT INTO lancamentos
            (data, mes, ano, quem, tipo_geral, natureza, quem_resp,
             categoria, item, valor, pagamento, observacao, valor_real, nro_mes)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    valor_real = d["valor"] if d["tipo_geral"] == "Entrada" else -d["valor"]
    execute(sql, (
        d["data"], d["mes"], d["ano"], d["quem"], d["tipo_geral"],
        d["natureza"], d["quem"], d["categoria"], d.get("item"),
        d["valor"], d.get("pagamento"), d.get("observacao"),
        valor_real, d["nro_mes"]
    ))

def get_lancamentos(ano=2026, quem=None, tipo_geral=None, natureza=None):
    sql = "SELECT * FROM lancamentos WHERE ano = %s"
    params = [ano]
    if quem:
        sql += " AND quem = %s"; params.append(quem)
    if tipo_geral:
        sql += " AND tipo_geral = %s"; params.append(tipo_geral)
    if natureza:
        sql += " AND natureza = %s"; params.append(natureza)
    sql += " ORDER BY data DESC"
    return query_df(sql, params)

def update_lancamento(id, campos):
    sets = ", ".join([f"{k} = %s" for k in campos.keys()])
    execute(f"UPDATE lancamentos SET {sets} WHERE id = %s", list(campos.values()) + [id])

def delete_lancamento(id):
    execute("DELETE FROM lancamentos WHERE id = %s", [id])

def delete_lancamentos(ids):
    execute("DELETE FROM lancamentos WHERE id = ANY(%s)", [ids])

# ── CONSULTA DE SALDO ─────────────────────────────────────────────────────
def get_consulta_saldo(categoria, item, nro_mes, ano):
    item_q = item if item else None

    # Orçamento mês atual
    orc_mes = float(query_df("SELECT COALESCE(SUM(valor),0) AS v FROM orcamento WHERE tipo=%s AND (item=%s OR item IS NULL) AND nro_mes=%s AND ano=%s", [categoria,item_q,nro_mes,ano])["v"].values[0])

    # Gasto mês atual
    gasto_mes = float(query_df("SELECT COALESCE(SUM(valor),0) AS v FROM lancamentos WHERE tipo_geral='Saida' AND categoria=%s AND nro_mes=%s AND ano=%s", [categoria,nro_mes,ano])["v"].values[0])

    # Rollover: orçado - gasto de todos os meses anteriores
    orc_ant   = float(query_df("SELECT COALESCE(SUM(valor),0) AS v FROM orcamento WHERE tipo=%s AND (item=%s OR item IS NULL) AND nro_mes<%s AND ano=%s", [categoria,item_q,nro_mes,ano])["v"].values[0])
    gasto_ant = float(query_df("SELECT COALESCE(SUM(valor),0) AS v FROM lancamentos WHERE tipo_geral='Saida' AND categoria=%s AND nro_mes<%s AND ano=%s", [categoria,nro_mes,ano])["v"].values[0])
    rollover  = orc_ant - gasto_ant

    # Disponível total no mês (rollover + orçamento do mês)
    disponivel_mes = rollover + orc_mes

    # Orçamento restante do ano (mês atual até dezembro)
    orc_restante = float(query_df("SELECT COALESCE(SUM(valor),0) AS v FROM orcamento WHERE tipo=%s AND (item=%s OR item IS NULL) AND nro_mes>=%s AND ano=%s", [categoria,item_q,nro_mes,ano])["v"].values[0])

    # Gasto total do ano até agora
    gasto_ano = float(query_df("SELECT COALESCE(SUM(valor),0) AS v FROM lancamentos WHERE tipo_geral='Saida' AND categoria=%s AND ano=%s", [categoria,ano])["v"].values[0])

    # Orçamento total do ano
    orc_ano = float(query_df("SELECT COALESCE(SUM(valor),0) AS v FROM orcamento WHERE tipo=%s AND (item=%s OR item IS NULL) AND ano=%s", [categoria,item_q,ano])["v"].values[0])

    # Saldo disponível para o resto do ano
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

def get_total_ano(categoria, item, ano):
    return float(query_df("SELECT COALESCE(SUM(valor),0) AS v FROM lancamentos WHERE tipo_geral='Saida' AND categoria=%s AND (item=%s OR item IS NULL) AND ano=%s", [categoria, item if item else None, ano])["v"].values[0])

# ── ORÇAMENTO ─────────────────────────────────────────────────────────────
def get_orcamento_matrix(ano=2026):
    return query_df("SELECT natureza, tipo, nro_mes, valor FROM orcamento WHERE ano=%s ORDER BY natureza, tipo, nro_mes", [ano])

def set_orcamento_mes(natureza, tipo, nro_mes, ano, valor):
    # Usa DO UPDATE simples com WHERE para evitar problema de ON CONFLICT com NULL
    execute("""
        UPDATE orcamento SET valor=%s
        WHERE natureza=%s AND tipo=%s AND nro_mes=%s AND ano=%s AND item IS NULL
    """, [valor, natureza, tipo, nro_mes, ano])
    execute("""
        INSERT INTO orcamento (natureza, tipo, item, nro_mes, ano, valor)
        SELECT %s,%s,NULL,%s,%s,%s
        WHERE NOT EXISTS (
            SELECT 1 FROM orcamento
            WHERE natureza=%s AND tipo=%s AND nro_mes=%s AND ano=%s AND item IS NULL
        )
    """, [natureza, tipo, nro_mes, ano, valor, natureza, tipo, nro_mes, ano])

def set_orcamento_daqui_em_diante(natureza, tipo, nro_mes_inicio, ano, valor):
    for m in range(nro_mes_inicio, 13):
        set_orcamento_mes(natureza, tipo, m, ano, valor)

def set_orcamento_anual(natureza, tipo, ano, valor_anual):
    for m in range(1, 13):
        set_orcamento_mes(natureza, tipo, m, ano, round(valor_anual/12, 2))

def get_categorias_orcamento(ano=2026):
    return query_df("SELECT DISTINCT natureza, tipo FROM orcamento WHERE ano=%s ORDER BY natureza, tipo", [ano])

def get_orcamento_vs_realizado(ano=2026, nro_mes=None):
    if nro_mes:
        sql = """
            SELECT o.natureza, o.tipo, o.orcado,
                   COALESCE(l.gasto,0) AS gasto,
                   o.orcado - COALESCE(l.gasto,0) AS saldo
            FROM (SELECT natureza, tipo, SUM(valor) AS orcado FROM orcamento WHERE ano=%s AND nro_mes=%s GROUP BY natureza, tipo) o
            LEFT JOIN (SELECT categoria, SUM(valor) AS gasto FROM lancamentos WHERE tipo_geral='Saida' AND ano=%s AND nro_mes=%s GROUP BY categoria) l
            ON l.categoria = o.tipo ORDER BY o.natureza, o.tipo
        """
        return query_df(sql, [ano, nro_mes, ano, nro_mes])
    else:
        sql = """
            SELECT o.natureza, o.tipo, o.orcado,
                   COALESCE(l.gasto,0) AS gasto,
                   o.orcado - COALESCE(l.gasto,0) AS saldo
            FROM (SELECT natureza, tipo, SUM(valor) AS orcado FROM orcamento WHERE ano=%s GROUP BY natureza, tipo) o
            LEFT JOIN (SELECT categoria, SUM(valor) AS gasto FROM lancamentos WHERE tipo_geral='Saida' AND ano=%s GROUP BY categoria) l
            ON l.categoria = o.tipo ORDER BY o.natureza, o.tipo
        """
        return query_df(sql, [ano, ano])

# ── USUARIOS ─────────────────────────────────────────────────────────────
def get_usuarios(apenas_ativos=False):
    sql = "SELECT * FROM usuarios"
    if apenas_ativos:
        sql += " WHERE ativo = TRUE"
    return query_df(sql + " ORDER BY nome")

def inserir_usuario(nome, papel, tipo):
    execute("INSERT INTO usuarios (nome, papel, tipo, ativo) VALUES (%s,%s,%s,TRUE)", [nome, papel, tipo])

def update_usuario(id, campos):
    sets = ", ".join([f"{k} = %s" for k in campos.keys()])
    execute(f"UPDATE usuarios SET {sets} WHERE id = %s", list(campos.values()) + [id])

def toggle_usuario_ativo(id, ativo):
    execute("UPDATE usuarios SET ativo = %s WHERE id = %s", [ativo, id])

# ── DASHBOARD ─────────────────────────────────────────────────────────────
def get_resumo_mensal(ano=2026, quem=None, natureza=None):
    sql = """
        SELECT l.nro_mes, m.nome AS mes,
            SUM(CASE WHEN l.tipo_geral='Entrada' THEN l.valor ELSE 0 END) AS entradas,
            SUM(CASE WHEN l.tipo_geral='Saida'   THEN l.valor ELSE 0 END) AS saidas,
            SUM(CASE WHEN l.tipo_geral='Entrada' THEN l.valor ELSE 0 END) -
            SUM(CASE WHEN l.tipo_geral='Saida'   THEN l.valor ELSE 0 END) AS saldo
        FROM lancamentos l
        JOIN meses m ON m.nro = l.nro_mes
        WHERE l.ano=%s
    """
    params = [ano]
    if quem:     sql += " AND l.quem=%s";     params.append(quem)
    if natureza: sql += " AND l.natureza=%s"; params.append(natureza)
    return query_df(sql + " GROUP BY l.nro_mes, m.nome ORDER BY l.nro_mes", params)

def get_gastos_por_categoria(ano=2026, nro_mes=None, quem=None, natureza=None):
    sql = "SELECT categoria, SUM(valor) AS total FROM lancamentos WHERE tipo_geral='Saida' AND ano=%s"
    params = [ano]
    if nro_mes:  sql += " AND nro_mes=%s";  params.append(nro_mes)
    if quem:     sql += " AND quem=%s";     params.append(quem)
    if natureza: sql += " AND natureza=%s"; params.append(natureza)
    return query_df(sql + " GROUP BY categoria ORDER BY total DESC", params)

def get_gastos_mensais_por_pessoa(ano=2026, natureza=None):
    sql = """
        SELECT l.nro_mes, m.nome AS mes, l.quem, SUM(l.valor) AS total
        FROM lancamentos l
        JOIN meses m ON m.nro = l.nro_mes
        WHERE l.tipo_geral='Saida' AND l.ano=%s
    """
    params = [ano]
    if natureza: sql += " AND l.natureza=%s"; params.append(natureza)
    return query_df(sql + " GROUP BY l.nro_mes, m.nome, l.quem ORDER BY l.nro_mes, l.quem", params)

def get_gastos_por_pessoa(ano=2026, nro_mes=None, natureza=None):
    sql = "SELECT quem, SUM(valor) AS total FROM lancamentos WHERE tipo_geral='Saida' AND ano=%s"
    params = [ano]
    if nro_mes:  sql += " AND nro_mes=%s";  params.append(nro_mes)
    if natureza: sql += " AND natureza=%s"; params.append(natureza)
    return query_df(sql + " GROUP BY quem ORDER BY total DESC", params)

def get_saldo_acumulado(ano=2026, natureza=None):
    where_nat = "AND l.natureza=%s" if natureza else ""
    params    = [ano] + ([natureza] if natureza else [])
    return query_df(f"""
        SELECT sub.nro_mes, m.nome AS mes,
            SUM(sub.valor_real) OVER (ORDER BY sub.nro_mes) AS saldo_acumulado
        FROM (
            SELECT nro_mes, SUM(valor_real) AS valor_real
            FROM lancamentos l WHERE ano=%s {where_nat}
            GROUP BY nro_mes
        ) sub
        JOIN meses m ON m.nro = sub.nro_mes
        ORDER BY sub.nro_mes
    """, params)