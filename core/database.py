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
import pandas as pd

# Conexao e primitivas (get_conn/query_df/execute/_hh) agora moram em core/db.py.
# Importamos query_df, execute e _hh de la e os reexportamos: quem ja faz
# "from core.database import query_df/execute" continua funcionando sem mudanca.
from core.db import query_df, execute, _hh


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
    # valor_real e o impacto no FLUXO DE CAIXA do household:
    #   Entrada      -> +valor (dinheiro novo na conta)
    #   Saida        -> -valor (dinheiro que saiu de verdade)
    #   Investimento -> 0      (aporte conta->corretora: o dinheiro continua
    #                           sendo do casal, so mudou de endereco. O salario
    #                           cheio ja foi contado como Entrada; se o aporte
    #                           contasse como -valor, a poupanca acumulada do
    #                           Dashboard cairia indevidamente a cada aporte.)
    if d["tipo_geral"] == "Entrada":
        valor_real = d["valor"]
    elif d["tipo_geral"] == "Investimento":
        valor_real = 0
    else:
        valor_real = -d["valor"]
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


def get_total_ano(categoria, item, ano, tipo_geral="Saida", household_id=None):
    """
    Total do ano de uma categoria. tipo_geral parametrizado (default 'Saida'
    preserva o comportamento das chamadas existentes) — antes era hardcoded
    'Saida', o que fazia o "total acumulado no ano" exibido apos registrar
    uma ENTRADA (ex.: salario) retornar sempre 0.
    """
    hh = _hh(household_id)
    return float(query_df(
        "SELECT COALESCE(SUM(valor),0) AS v FROM lancamentos "
        "WHERE household_id=%s AND tipo_geral=%s AND categoria=%s AND (item=%s OR item IS NULL) AND ano=%s",
        [hh, tipo_geral, categoria, item if item else None, ano]
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
    """
    Serie mensal com entradas, saidas, saldo e investimentos (coluna propria —
    aporte nao e entrada nem saida). Saldo inicial fica fora da serie mensal
    de investimentos: e patrimonio pre-app ancorado em Janeiro, nao aporte
    daquele mes (incluiria um degrau gigante no grafico).

    O filtro de natureza se aplica so a Entrada/Saida: a serie de investimentos
    permanece visivel em qualquer recorte (natureza='Investimento' e fixa nos
    aportes, entao 'Pessoal'/'Profissional' a zerariam). O filtro `quem` se
    aplica normalmente a tudo.
    """
    hh = _hh(household_id)
    sql = """
        SELECT l.nro_mes, m.nome AS mes,
            SUM(CASE WHEN l.tipo_geral='Entrada' THEN l.valor ELSE 0 END) AS entradas,
            SUM(CASE WHEN l.tipo_geral='Saida'   THEN l.valor ELSE 0 END) AS saidas,
            SUM(CASE WHEN l.tipo_geral='Investimento' AND l.categoria <> 'Saldo inicial'
                     THEN l.valor ELSE 0 END) AS investimentos,
            SUM(CASE WHEN l.tipo_geral='Entrada' THEN l.valor ELSE 0 END) -
            SUM(CASE WHEN l.tipo_geral='Saida'   THEN l.valor ELSE 0 END) AS saldo
        FROM lancamentos l
        JOIN meses m ON m.nro = l.nro_mes
        WHERE l.household_id=%s AND l.ano=%s
    """
    params = [hh, ano]
    if quem:
        sql += " AND l.quem=%s"
        params.append(quem)
    if natureza:
        sql += " AND (l.natureza=%s OR l.tipo_geral='Investimento')"
        params.append(natureza)
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


# ── INVESTIMENTOS (modulo "dinheiro guardado") ────────────────────────────
# Habilitado por household via households.investimentos_ativo (hoje so Admin).
#
# Convencao de armazenamento — reusa `lancamentos`, sem tabela de movimentos
# propria (edicao, exclusao e isolamento por household ja funcionam de graca):
#
#   Aporte fixo:    tipo_geral='Investimento', natureza='Investimento',
#                   categoria='Aporte fixo',     item=<produto>, valor_real=0
#   Aporte variavel:tipo_geral='Investimento', natureza='Investimento',
#                   categoria='Aporte variável', item=<produto|NULL>, valor_real=0
#   Saldo inicial:  tipo_geral='Investimento', natureza='Investimento',
#                   categoria='Saldo inicial',   item=<produto|NULL>, valor_real=0
#   Dividendo:      tipo_geral='Entrada',      natureza='Pessoal',
#                   categoria='Dividendos',      item=<origem|NULL>, valor_real=+valor
#
# Racional financeiro: aporte e transferencia conta->corretora — o salario
# CHEIO ja entrou como Entrada, entao o aporte nao e nem entrada nem saida
# (valor_real=0 mantem a poupanca do Dashboard intacta). Dividendo cai na
# conta corrente, logo E renda real do mes: entra como Entrada normal e
# tambem aparece no modulo como renda passiva.
#
# A lista de produtos de aporte fixo (ex.: 'Manu 4k' -> 4166/mes) vive em
# `config_investimentos` — permite registrar o pacote do mes em 1 clique.

CAT_APORTE_FIXO   = "Aporte fixo"
CAT_APORTE_VAR    = "Aporte variável"
CAT_SALDO_INICIAL = "Saldo inicial"
CAT_DIVIDENDOS    = "Dividendos"
CATS_INVESTIMENTO = [CAT_APORTE_FIXO, CAT_APORTE_VAR, CAT_SALDO_INICIAL, CAT_DIVIDENDOS]


def get_investimentos_ativo(household_id=None) -> bool:
    """
    True se o household atual tem o modulo de investimentos habilitado.
    Falha FECHADO (False) para qualquer erro — inclusive a janela de deploy
    em que o codigo novo roda antes da migration que cria a coluna: nesse
    caso o app continua de pe, apenas sem exibir a pagina de investimentos.
    """
    try:
        hh = _hh(household_id)
        df = query_df("SELECT investimentos_ativo FROM households WHERE id=%s", [hh])
        return bool(df["investimentos_ativo"].values[0]) if not df.empty else False
    except Exception:
        return False


# ── Config de produtos de investimento ────────────────────────────────────
# Dois tipos de produto:
#   'fixo'     -> valor mensal que nunca muda (ex.: 'Manu 4k' = 4166/mes).
#                 Entram no botao de registro em lote ("cliquei, pago").
#   'variavel' -> produto cadastrado sem valor fixo; quando o usuario manda
#                 dinheiro, escolhe o produto no aporte avulso e digita o valor.
def get_config_investimentos(somente_ativos=True, tipo=None, household_id=None):
    """Produtos do household. tipo='fixo'|'variavel' filtra; None traz todos.
    `data_inicio` (DATE) = mes em que o plano comecou a aportar — usado para
    saber a partir de quando a serie de aportes existe."""
    hh = _hh(household_id)
    sql = ("SELECT id, nome, valor_fixo, tipo, ativo, ordem, data_inicio "
           "FROM config_investimentos WHERE household_id=%s")
    params = [hh]
    if somente_ativos:
        sql += " AND ativo = TRUE"
    if tipo is not None:
        sql += " AND tipo = %s"
        params.append(tipo)
    sql += " ORDER BY ordem, nome"
    return query_df(sql, params)


def add_config_investimento(nome, valor_fixo, tipo="fixo", data_inicio=None, household_id=None):
    """
    Cadastra produto novo. Para tipo='variavel' o valor_fixo e gravado como 0 —
    o valor real e informado a cada aporte avulso. `data_inicio` (opcional) marca
    o mes em que o plano comecou a aportar.
    """
    hh = _hh(household_id)
    execute(
        "INSERT INTO config_investimentos (nome, valor_fixo, tipo, data_inicio, household_id) "
        "VALUES (%s, %s, %s, %s, %s)",
        [nome.strip(), valor_fixo if tipo == "fixo" else 0, tipo, data_inicio, hh],
    )


def update_config_investimento(id, campos, household_id=None):
    """
    Atualiza produto (valor_fixo, ativo, nome, ordem). Mudar valor_fixo NAO
    altera aportes ja registrados — eles guardam o valor historico da epoca.
    """
    hh = _hh(household_id)
    sets = ", ".join([f"{k} = %s" for k in campos.keys()])
    execute(
        f"UPDATE config_investimentos SET {sets} WHERE id = %s AND household_id = %s",
        list(campos.values()) + [id, hh],
    )


# ── Registro de aportes ───────────────────────────────────────────────────
def get_aportes_fixos_registrados_no_mes(nro_mes, ano, household_id=None):
    """
    Nomes de produtos (coluna item) que JA tem aporte fixo no mes/ano — usado
    para a protecao anti-duplicacao do botao "registrar aportes do mes".
    """
    hh = _hh(household_id)
    df = query_df(
        "SELECT DISTINCT item FROM lancamentos "
        "WHERE household_id=%s AND tipo_geral='Investimento' AND categoria=%s "
        "AND nro_mes=%s AND ano=%s AND item IS NOT NULL",
        [hh, CAT_APORTE_FIXO, nro_mes, ano],
    )
    return df["item"].tolist()


def registrar_aportes_fixos(quem, mes_nome, nro_mes, ano, produtos, household_id=None):
    """
    Insere em lote os aportes fixos do mes. `produtos` = lista de dicts
    {'nome': str, 'valor_fixo': float}. Retorna a quantidade inserida.
    Cada aporte vira um lancamento individual (1 por produto) para permitir
    analise por produto e exclusao granular depois.
    """
    from datetime import date as _date
    hh = _hh(household_id)
    for p in produtos:
        inserir_lancamento({
            "data": _date.today(), "mes": mes_nome, "ano": ano,
            "quem": quem, "tipo_geral": "Investimento",
            "natureza": "Investimento", "categoria": CAT_APORTE_FIXO,
            "item": p["nome"], "valor": p["valor_fixo"],
            "pagamento": None, "observacao": None, "nro_mes": nro_mes,
        }, household_id=hh)
    return len(produtos)


# ── Consultas do modulo ───────────────────────────────────────────────────
def get_investimentos_mensal(ano=2026, household_id=None):
    """
    Serie mensal do modulo NO ANO informado: aporte_fixo, aporte_variavel
    (de `lancamentos`) + dividendos e rendimentos (da tabela
    `investimentos_serie`). Saldo inicial fica FORA (e baseline do patrimonio,
    nao fluxo do mes). Retorna so os meses com algum movimento.

    Dividendo e rendimento vivem em `investimentos_serie` (nao em lancamentos)
    de proposito: assim NAO entram no fluxo de caixa do Dashboard. Por isso o
    join e por (ano, nro_mes) com a serie.
    """
    hh = _hh(household_id)
    return query_df("""
        WITH ap AS (
            SELECT l.nro_mes,
                SUM(CASE WHEN l.categoria=%s THEN l.valor ELSE 0 END) AS aporte_fixo,
                SUM(CASE WHEN l.categoria=%s THEN l.valor ELSE 0 END) AS aporte_variavel
            FROM lancamentos l
            WHERE l.household_id=%s AND l.ano=%s AND l.tipo_geral='Investimento'
              AND l.categoria IN (%s,%s)
            GROUP BY l.nro_mes
        ),
        di AS (
            SELECT nro_mes,
                   SUM(dividendo)  AS dividendos,
                   SUM(rendimento) AS rendimentos
            FROM investimentos_serie
            WHERE household_id=%s AND ano=%s
            GROUP BY nro_mes
        )
        SELECT m.nro AS nro_mes, m.nome AS mes,
            COALESCE(ap.aporte_fixo, 0)      AS aporte_fixo,
            COALESCE(ap.aporte_variavel, 0)  AS aporte_variavel,
            COALESCE(di.dividendos, 0)       AS dividendos,
            COALESCE(di.rendimentos, 0)      AS rendimentos
        FROM meses m
        LEFT JOIN ap ON ap.nro_mes = m.nro
        LEFT JOIN di ON di.nro_mes = m.nro
        WHERE COALESCE(ap.aporte_fixo,0) <> 0 OR COALESCE(ap.aporte_variavel,0) <> 0
           OR COALESCE(di.dividendos,0) <> 0 OR COALESCE(di.rendimentos,0) <> 0
        ORDER BY m.nro
    """, [CAT_APORTE_FIXO, CAT_APORTE_VAR, hh, ano, CAT_APORTE_FIXO, CAT_APORTE_VAR,
          hh, ano])


def get_total_investido(produto=None, household_id=None):
    """
    Total aportado (custo) = saldo inicial + soma de TODOS os aportes (todos os anos).
    Opcionalmente filtra por produto (item). Dividendos NAO entram aqui — eles ja
    estao dentro do rendimento/valor (sao reinvestidos).
    """
    hh = _hh(household_id)
    sql = ("SELECT COALESCE(SUM(valor),0) AS v FROM lancamentos "
           "WHERE household_id=%s AND tipo_geral='Investimento'")
    params = [hh]
    if produto:
        sql += " AND item = %s"
        params.append(produto)
    return float(query_df(sql, params)["v"].values[0])


def get_investido_por_produto(household_id=None):
    """
    Total guardado por produto (saldo inicial + aportes, todos os anos).
    item NULL agrupa como 'Geral'. Ordenado do maior para o menor.
    """
    hh = _hh(household_id)
    return query_df(
        "SELECT COALESCE(item, 'Geral') AS produto, SUM(valor) AS total "
        "FROM lancamentos WHERE household_id=%s AND tipo_geral='Investimento' "
        "GROUP BY COALESCE(item, 'Geral') ORDER BY total DESC",
        [hh])


def get_saldo_inicial_investimentos(produto=None, household_id=None):
    """Soma dos registros de saldo inicial (0.0 se ainda nao registrado). Opcional: produto."""
    hh = _hh(household_id)
    sql = ("SELECT COALESCE(SUM(valor),0) AS v FROM lancamentos "
           "WHERE household_id=%s AND tipo_geral='Investimento' AND categoria=%s")
    params = [hh, CAT_SALDO_INICIAL]
    if produto:
        sql += " AND item = %s"
        params.append(produto)
    return float(query_df(sql, params)["v"].values[0])


def get_registros_investimentos(ano=2026, household_id=None):
    """
    Todos os registros do modulo no ano (aportes, saldo inicial e dividendos)
    para a tabela de gestao da pagina — inclui id para exclusao granular.
    """
    hh = _hh(household_id)
    return query_df("""
        SELECT id, data, mes, nro_mes, quem, tipo_geral, categoria, item,
               valor, observacao
        FROM lancamentos
        WHERE household_id=%s AND ano=%s
          AND (tipo_geral='Investimento' OR
               (tipo_geral='Entrada' AND categoria=%s))
        ORDER BY nro_mes DESC, categoria, item
    """, [hh, ano, CAT_DIVIDENDOS])


# ══════════════════════════════════════════════════════════════════════════
# SERIE MENSAL DE INVESTIMENTOS (rendimento + dividendo) — tabela propria
# ══════════════════════════════════════════════════════════════════════════
# `investimentos_serie` guarda, por produto e por mes, o RENDIMENTO (valorizacao
# da carteira, pode ser + ou -) e o DIVIDENDO recebido. Vive FORA de
# `lancamentos` de proposito:
#   - rendimento e valorizacao, nao movimento de caixa;
#   - dividendo aqui e tratado como renda do investimento (acompanhada no modulo),
#     nao como Entrada do mes — assim o Dashboard de fluxo de caixa de 2026 nao e
#     afetado por dividendos historicos. (Se um dia quiser que dividendo conte como
#     renda real, basta tambem inserir um lancamento Entrada — decisao separada.)
#
# Modelo financeiro do modulo, agora completo:
#   Total aportado (custo)   = saldo inicial + Σ aportes        (de `lancamentos`)
#   Rendimento total         = Σ rendimento                     (de `investimentos_serie`)
#   PATRIMONIO (valor mkt)   = Total aportado + Rendimento total
#   Dividendos recebidos     = Σ dividendo                      (de `investimentos_serie`)

def _sum_serie(coluna, hh, produto=None):
    """Soma uma coluna da serie (rendimento/dividendo), opcional por produto."""
    sql = (f"SELECT COALESCE(SUM(s.{coluna}),0) AS v FROM investimentos_serie s "
           "JOIN config_investimentos c ON c.id = s.produto_id WHERE s.household_id=%s")
    params = [hh]
    if produto:
        sql += " AND c.nome = %s"
        params.append(produto)
    return float(query_df(sql, params)["v"].values[0])


def get_total_rendimento(produto=None, household_id=None):
    """Rendimento acumulado (valorizacao +/-). Opcional: filtra por produto."""
    return _sum_serie("rendimento", _hh(household_id), produto)


def get_total_dividendos(produto=None, household_id=None):
    """Total de dividendos gerados pelos fundos (reinvestidos — ja dentro do rendimento)."""
    return _sum_serie("dividendo", _hh(household_id), produto)


def get_aportado_no_ano(ano, produto=None, household_id=None):
    """Aportes (fixo + variavel) feitos no ano — exclui saldo inicial. Opcional: produto."""
    hh = _hh(household_id)
    sql = ("SELECT COALESCE(SUM(valor),0) AS v FROM lancamentos "
           "WHERE household_id=%s AND tipo_geral='Investimento' AND ano=%s AND categoria IN (%s,%s)")
    params = [hh, ano, CAT_APORTE_FIXO, CAT_APORTE_VAR]
    if produto:
        sql += " AND item = %s"
        params.append(produto)
    return float(query_df(sql, params)["v"].values[0])


def _evolucao_frame(ap, sr, saldo_ini):
    """
    Monta a serie mensal CONTINUA (sem buracos) a partir de:
      ap = DataFrame [ano, nro_mes, aporte]   (aportes de lancamentos)
      sr = DataFrame [ano, nro_mes, rendimento, dividendo]  (da serie)
    Calcula os acumulados em pandas (logica simples de seguir):
      aporte_acum     = saldo inicial + soma corrida dos aportes
      rendimento_acum = soma corrida dos rendimentos
      patrimonio      = aporte_acum + rendimento_acum   (= valor de mercado)
    """
    cols = ["periodo", "ano", "nro_mes", "aporte", "rendimento", "dividendo",
            "aporte_acum", "rendimento_acum", "patrimonio", "dividendo_acum"]

    def _periodo(df):
        if df.empty:
            df = df.copy()
            df["periodo"] = pd.to_datetime([])
            return df
        df = df.copy()
        df["periodo"] = pd.to_datetime(dict(year=df["ano"], month=df["nro_mes"], day=1))
        return df

    ap, sr = _periodo(ap), _periodo(sr)
    periodos = pd.concat([ap.get("periodo", pd.Series(dtype="datetime64[ns]")),
                          sr.get("periodo", pd.Series(dtype="datetime64[ns]"))])
    if periodos.empty:
        return pd.DataFrame(columns=cols)

    # Spine: um ponto por mes, do 1o ao ultimo dado — sem buracos na curva.
    spine = pd.date_range(periodos.min(), periodos.max(), freq="MS")
    out = pd.DataFrame({"periodo": spine})
    a = ap.groupby("periodo")["aporte"].sum() if not ap.empty else pd.Series(dtype=float)
    r = sr.groupby("periodo")["rendimento"].sum() if not sr.empty else pd.Series(dtype=float)
    d = sr.groupby("periodo")["dividendo"].sum() if not sr.empty else pd.Series(dtype=float)
    out["aporte"]     = out["periodo"].map(a).fillna(0.0).astype(float)
    out["rendimento"] = out["periodo"].map(r).fillna(0.0).astype(float)
    out["dividendo"]  = out["periodo"].map(d).fillna(0.0).astype(float)
    out["ano"]     = out["periodo"].dt.year
    out["nro_mes"] = out["periodo"].dt.month
    out["aporte_acum"]     = saldo_ini + out["aporte"].cumsum()
    out["rendimento_acum"] = out["rendimento"].cumsum()
    out["patrimonio"]      = out["aporte_acum"] + out["rendimento_acum"]
    out["dividendo_acum"]  = out["dividendo"].cumsum()
    return out[cols]


def get_investimentos_evolucao(produto=None, household_id=None):
    """
    Serie mensal consolidada (ou de 1 produto) para os graficos de evolucao.
    Colunas: periodo, ano, nro_mes, aporte, rendimento, dividendo,
             aporte_acum, rendimento_acum, patrimonio, dividendo_acum.
    """
    hh = _hh(household_id)
    ap_sql = ("SELECT ano, nro_mes, SUM(valor) AS aporte FROM lancamentos "
              "WHERE household_id=%s AND tipo_geral='Investimento' AND categoria IN (%s,%s)")
    ap_p = [hh, CAT_APORTE_FIXO, CAT_APORTE_VAR]
    if produto:
        ap_sql += " AND item = %s"
        ap_p.append(produto)
    ap_sql += " GROUP BY ano, nro_mes"
    ap = query_df(ap_sql, ap_p)

    sr_sql = ("SELECT s.ano, s.nro_mes, SUM(s.rendimento) AS rendimento, SUM(s.dividendo) AS dividendo "
              "FROM investimentos_serie s JOIN config_investimentos c ON c.id = s.produto_id "
              "WHERE s.household_id=%s")
    sr_p = [hh]
    if produto:
        sr_sql += " AND c.nome = %s"
        sr_p.append(produto)
    sr_sql += " GROUP BY s.ano, s.nro_mes"
    sr = query_df(sr_sql, sr_p)
    return _evolucao_frame(ap, sr, get_saldo_inicial_investimentos(produto, hh))


def get_investimentos_evolucao_produto(household_id=None):
    """
    Evolucao do VALOR por produto (para area empilhada). Colunas:
    periodo, produto, valor — onde valor = soma corrida de (aporte + rendimento)
    daquele produto ate o mes (valor de mercado do plano ao longo do tempo).
    """
    hh = _hh(household_id)
    ap = query_df(
        "SELECT ano, nro_mes, item AS produto, SUM(valor) AS aporte FROM lancamentos "
        "WHERE household_id=%s AND tipo_geral='Investimento' AND categoria IN (%s,%s) "
        "AND item IS NOT NULL GROUP BY ano, nro_mes, item",
        [hh, CAT_APORTE_FIXO, CAT_APORTE_VAR])
    sr = query_df(
        "SELECT s.ano, s.nro_mes, c.nome AS produto, SUM(s.rendimento) AS rendimento "
        "FROM investimentos_serie s JOIN config_investimentos c ON c.id = s.produto_id "
        "WHERE s.household_id=%s GROUP BY s.ano, s.nro_mes, c.nome",
        [hh])

    if ap.empty and sr.empty:
        return pd.DataFrame(columns=["periodo", "produto", "valor"])

    for df in (ap, sr):
        if not df.empty:
            df["periodo"] = pd.to_datetime(dict(year=df["ano"], month=df["nro_mes"], day=1))

    pmins = [d["periodo"].min() for d in (ap, sr) if not d.empty]
    pmaxs = [d["periodo"].max() for d in (ap, sr) if not d.empty]
    spine = pd.date_range(min(pmins), max(pmaxs), freq="MS")
    produtos = sorted(set(
        (ap["produto"].tolist() if not ap.empty else []) +
        (sr["produto"].tolist() if not sr.empty else [])
    ))

    blocos = []
    for prod in produtos:
        a = (ap[ap["produto"] == prod].groupby("periodo")["aporte"].sum()
             if not ap.empty else pd.Series(dtype=float))
        r = (sr[sr["produto"] == prod].groupby("periodo")["rendimento"].sum()
             if not sr.empty else pd.Series(dtype=float))
        sub = pd.DataFrame({"periodo": spine})
        sub["produto"] = prod
        fluxo = sub["periodo"].map(a).fillna(0.0) + sub["periodo"].map(r).fillna(0.0)
        sub["valor"] = fluxo.cumsum()
        blocos.append(sub)
    return pd.concat(blocos, ignore_index=True)


def get_patrimonio_produto_antes(produto, ano, nro_mes, household_id=None):
    """
    Valor de mercado (patrimonio) do produto considerando tudo ESTRITAMENTE
    ANTES do mes alvo (ano, nro_mes): saldo inicial + Σ aportes + Σ rendimentos
    cujo (ano, nro_mes) seja anterior ao alvo.

    Usado pela entrada por Account Value: inverte o valor do extrato em
    rendimento do mes ->  rendimento[m] = account_value[m] - patrimonio_antes - aporte[m].
    Assim o patrimonio reconstruido (Σaporte + Σrendimento) fica IGUAL ao Account
    Value digitado. Mesma definicao de patrimonio de get_investimentos_evolucao,
    so que cortada no mes anterior.
    """
    hh = _hh(household_id)
    chave = ano * 100 + nro_mes
    ap = query_df(
        "SELECT COALESCE(SUM(valor),0) AS v FROM lancamentos "
        "WHERE household_id=%s AND tipo_geral='Investimento' "
        "AND categoria IN (%s,%s) AND item=%s AND (ano*100 + nro_mes) < %s",
        [hh, CAT_APORTE_FIXO, CAT_APORTE_VAR, produto, chave])
    sr = query_df(
        "SELECT COALESCE(SUM(s.rendimento),0) AS v FROM investimentos_serie s "
        "JOIN config_investimentos c ON c.id = s.produto_id "
        "WHERE s.household_id=%s AND c.nome=%s AND (s.ano*100 + s.nro_mes) < %s",
        [hh, produto, chave])
    saldo_ini = get_saldo_inicial_investimentos(produto, hh)
    return saldo_ini + float(ap["v"].values[0]) + float(sr["v"].values[0])


def get_aporte_produto_mes(produto, ano, nro_mes, household_id=None):
    """
    Soma dos aportes (fixo + variavel) ja lancados para um produto num mes/ano.
    Usado pela entrada por Account Value: se ja existe aporte do mes, reaproveita
    o valor (NAO duplica); se for 0, a pagina lanca o aporte fixo do produto.
    """
    hh = _hh(household_id)
    df = query_df(
        "SELECT COALESCE(SUM(valor),0) AS v FROM lancamentos "
        "WHERE household_id=%s AND tipo_geral='Investimento' "
        "AND categoria IN (%s,%s) AND item=%s AND ano=%s AND nro_mes=%s",
        [hh, CAT_APORTE_FIXO, CAT_APORTE_VAR, produto, ano, nro_mes])
    return float(df["v"].values[0])


def upsert_serie(produto_id, ano, nro_mes, rendimento=None, dividendo=None,
                 reinvestido=None, household_id=None):
    """
    Insere/atualiza um ponto da serie (1 produto, 1 mes). Passe rendimento e/ou
    dividendo; o campo que vier None NAO sobrescreve o valor ja gravado
    (permite editar so o rendimento sem zerar o dividendo e vice-versa).

    reinvestido: TRUE = dividendo reinvestido (ja dentro do rendimento/valor);
    FALSE = dividendo pago em caixa (renda que saiu da carteira). None = nao mexe
    (no insert assume TRUE, o default da tabela). So faz sentido informar junto
    com um dividendo.
    """
    hh = _hh(household_id)
    execute(
        "INSERT INTO investimentos_serie "
        "  (household_id, produto_id, ano, nro_mes, rendimento, dividendo, reinvestido) "
        "VALUES (%s,%s,%s,%s, COALESCE(%s,0), COALESCE(%s,0), COALESCE(%s, TRUE)) "
        "ON CONFLICT (household_id, produto_id, ano, nro_mes) DO UPDATE SET "
        "  rendimento  = COALESCE(%s, investimentos_serie.rendimento), "
        "  dividendo   = COALESCE(%s, investimentos_serie.dividendo), "
        "  reinvestido = COALESCE(%s, investimentos_serie.reinvestido)",
        [hh, produto_id, ano, nro_mes, rendimento, dividendo, reinvestido,
         rendimento, dividendo, reinvestido],
    )


def get_serie_df(household_id=None):
    """Serie crua (com nome do produto e do mes) para a grade de edicao da pagina."""
    hh = _hh(household_id)
    return query_df(
        "SELECT s.id, s.produto_id, c.nome AS produto, s.ano, s.nro_mes, "
        "       m.nome AS mes, s.rendimento, s.dividendo "
        "FROM investimentos_serie s "
        "JOIN config_investimentos c ON c.id = s.produto_id "
        "JOIN meses m ON m.nro = s.nro_mes "
        "WHERE s.household_id=%s "
        "ORDER BY s.ano DESC, s.nro_mes DESC, c.nome",
        [hh])

# Fim do modulo de investimentos.
