"""
Modulo Networth (Patrimonio) do App 10M.

Acompanha a evolucao do patrimonio TOTAL do household ao longo dos meses/anos.
O usuario informa, por categoria e por mes, o valor em DOLAR DE CINGAPURA (SGD).
O grafico mostra apenas o TOTAL; as categorias servem so como forma de entrada
e para aplicar o ajuste das contas SRS.

Conceitos:
  - patrimonio_categorias: a lista de categorias (XP Vinicius, Cash, etc.).
      fator_liquido = 1.0 normal; 0.71 nas 3 contas SRS (o valor informado e o
      BRUTO; o que conta no patrimonio e bruto * 0.71 = liquido, ja descontada a
      multa de saque antecipado do SRS de Cingapura).
      ativa = FALSE esconde a categoria do formulario de entrada, mas mantem o
      historico ja registrado (a curva passada nao muda).
  - patrimonio_registros: o valor (valor_bruto, em SGD) de cada categoria em cada
      mes (ano + nro_mes). O indice unico (household_id, categoria_id, ano,
      nro_mes) garante 1 registro por categoria por mes; reenviar sobrescreve.

Patrimonio do mes = SOMA de (valor_bruto * fator_liquido) de todas as categorias
daquele mes. O fator vive na categoria, entao o 0.71 nao fica chumbado no codigo.

Reusa a camada de conexao de core/database.py (query_df / execute) e o isolamento
por household_id, igual ao resto do app.
"""
import pandas as pd

from core.database import query_df, execute
from core.auth import get_current_household_id


def _hh(household_id=None) -> int:
    """Resolve household_id: usa o explicito se passado, senao puxa do login."""
    if household_id is not None:
        return int(household_id)
    return get_current_household_id()


# -- CATEGORIAS ------------------------------------------------------------
def get_categorias(somente_ativas=False, household_id=None):
    """
    Categorias de patrimonio do household. Colunas: id, nome, fator_liquido,
    ativa, ordem. somente_ativas=True traz so as ativas (formulario de entrada);
    False traz todas (tela de gestao de categorias).
    """
    hh = _hh(household_id)
    sql = ("SELECT id, nome, fator_liquido, ativa, ordem, investivel "
           "FROM patrimonio_categorias WHERE household_id=%s")
    params = [hh]
    if somente_ativas:
        sql += " AND ativa = TRUE"
    sql += " ORDER BY ordem, nome"
    return query_df(sql, params)


def add_categoria(nome, fator_liquido=1.0, ordem=None, household_id=None):
    """
    Cadastra categoria nova. Se ordem=None, joga pro fim da lista.
    fator_liquido=0.71 marca conta SRS (informa bruto, conta liquido).
    """
    hh = _hh(household_id)
    if ordem is None:
        df = query_df(
            "SELECT COALESCE(MAX(ordem),0)+1 AS prox "
            "FROM patrimonio_categorias WHERE household_id=%s",
            [hh],
        )
        ordem = int(df["prox"].values[0])
    execute(
        "INSERT INTO patrimonio_categorias (household_id, nome, fator_liquido, ordem) "
        "VALUES (%s,%s,%s,%s)",
        [hh, nome.strip(), fator_liquido, ordem],
    )


def update_categoria(id, campos, household_id=None):
    """
    Atualiza categoria (nome, fator_liquido, ativa, ordem). AND household_id no
    WHERE impede afetar categoria de outro household.
    """
    hh = _hh(household_id)
    sets = ", ".join([f"{k} = %s" for k in campos.keys()])
    execute(
        f"UPDATE patrimonio_categorias SET {sets} WHERE id = %s AND household_id = %s",
        list(campos.values()) + [id, hh],
    )


def encerrar_categoria(id, household_id=None):
    """Marca categoria como inativa (some do formulario; historico fica intacto)."""
    update_categoria(id, {"ativa": False}, household_id=household_id)


def reativar_categoria(id, household_id=None):
    update_categoria(id, {"ativa": True}, household_id=household_id)


def delete_categoria(id, household_id=None):
    """
    APAGA a categoria E todo o historico dela (ON DELETE CASCADE nos registros).
    Use com cuidado — para parar de usar uma categoria sem perder o passado,
    prefira encerrar_categoria().
    """
    hh = _hh(household_id)
    execute(
        "DELETE FROM patrimonio_categorias WHERE id = %s AND household_id = %s",
        [id, hh],
    )


# -- REGISTROS (valor por categoria por mes) -------------------------------
def get_valores_mes(ano, nro_mes, household_id=None):
    """
    Valores ja salvos de um mes especifico. Retorna dict {categoria_id: valor_bruto}.
    Usado pelo formulario para saber o que ja foi gravado naquele mes.
    """
    hh = _hh(household_id)
    df = query_df(
        "SELECT categoria_id, valor_bruto FROM patrimonio_registros "
        "WHERE household_id=%s AND ano=%s AND nro_mes=%s",
        [hh, ano, nro_mes],
    )
    return {int(r.categoria_id): float(r.valor_bruto) for r in df.itertuples()}


def get_valores_mes_anterior(ano, nro_mes, household_id=None):
    """
    Valores do mes COM DADOS imediatamente anterior a (ano, nro_mes). Retorna dict
    {categoria_id: valor_bruto}. Serve para PRE-PREENCHER o formulario do mes novo
    com o ultimo valor conhecido de cada categoria — o usuario so ajusta o que
    mudou. Se nao houver mes anterior, retorna {} (formulario comeca zerado).
    """
    hh = _hh(household_id)
    df_mes = query_df(
        "SELECT ano, nro_mes FROM patrimonio_registros "
        "WHERE household_id=%s AND (ano < %s OR (ano = %s AND nro_mes < %s)) "
        "ORDER BY ano DESC, nro_mes DESC LIMIT 1",
        [hh, ano, ano, nro_mes],
    )
    if df_mes.empty:
        return {}
    a_ant = int(df_mes["ano"].values[0])
    m_ant = int(df_mes["nro_mes"].values[0])
    return get_valores_mes(a_ant, m_ant, household_id=hh)


def salvar_valor(categoria_id, ano, nro_mes, valor_bruto, household_id=None):
    """
    Insere ou atualiza o valor de UMA categoria num mes (upsert). Como existe o
    indice unico (household_id, categoria_id, ano, nro_mes), reenviar o mesmo mes
    sobrescreve o valor anterior — fica 1 registro so por mes (reconciliacao
    automatica, mesmo que voce atualize varias vezes no mes).
    """
    hh = _hh(household_id)
    execute(
        "INSERT INTO patrimonio_registros "
        "  (household_id, categoria_id, ano, nro_mes, valor_bruto) "
        "VALUES (%s,%s,%s,%s,%s) "
        "ON CONFLICT (household_id, categoria_id, ano, nro_mes) DO UPDATE SET "
        "  valor_bruto = EXCLUDED.valor_bruto, atualizado_em = now()",
        [hh, categoria_id, ano, nro_mes, valor_bruto],
    )


def salvar_mes(ano, nro_mes, valores, household_id=None):
    """
    Salva o mes inteiro de uma vez. `valores` = dict {categoria_id: valor_bruto}.
    Faz upsert de cada categoria. Retorna a quantidade de categorias salvas.
    """
    hh = _hh(household_id)
    for categoria_id, valor in valores.items():
        salvar_valor(categoria_id, ano, nro_mes, valor, household_id=hh)
    return len(valores)


def apagar_valor(categoria_id, ano, nro_mes, household_id=None):
    """Remove o valor de uma categoria num mes (ex.: informado por engano)."""
    hh = _hh(household_id)
    execute(
        "DELETE FROM patrimonio_registros "
        "WHERE household_id=%s AND categoria_id=%s AND ano=%s AND nro_mes=%s",
        [hh, categoria_id, ano, nro_mes],
    )


# -- PATRIMONIO (total e serie) --------------------------------------------
def get_patrimonio_total_mes(ano, nro_mes, household_id=None,
                             apenas_investivel=False):
    """
    Patrimonio LIQUIDO de um mes (em SGD): soma de (valor_bruto * fator_liquido)
    de todas as categorias daquele mes. Ja aplica o 0.71 das contas SRS.

    apenas_investivel=True exclui as categorias com investivel=FALSE (imovel de
    uso). Ver a nota em get_patrimonio_serie sobre por que as duas visoes existem.
    """
    hh = _hh(household_id)
    filtro = " AND c.investivel = TRUE" if apenas_investivel else ""
    return float(query_df(
        "SELECT COALESCE(SUM(r.valor_bruto * c.fator_liquido), 0) AS total "
        "FROM patrimonio_registros r "
        "JOIN patrimonio_categorias c ON c.id = r.categoria_id "
        "WHERE r.household_id=%s AND r.ano=%s AND r.nro_mes=%s" + filtro,
        [hh, ano, nro_mes],
    )["total"].values[0])


def get_patrimonio_serie(household_id=None, apenas_investivel=False):
    """
    Serie mensal do patrimonio ao longo de todos os anos — base do grafico
    principal. Colunas: ano, nro_mes, mes (nome), periodo (date 1o dia do mes),
    patrimonio. O total ja e LIQUIDO (valor_bruto * fator_liquido, SRS = 0.71).
    Soma TODAS as categorias, inclusive encerradas — uma conta que existiu no
    passado deve continuar contando nos meses em que existiu.

    apenas_investivel=True exclui as categorias com investivel=FALSE — hoje, o
    apartamento. As duas visoes respondem perguntas diferentes e ambas sao
    legitimas:
      - TOTAL      -> "quanto eu tenho": inclui o imovel, que e patrimonio real.
      - INVESTIVEL -> "com quanto eu posso contar": exclui o imovel de uso, que
                      nao da pra consumir 4% ao ano sem vender.
    A segunda e a base correta das projecoes e do calculo de independencia
    financeira; a primeira e a base do balanco.
    """
    hh = _hh(household_id)
    filtro = " AND c.investivel = TRUE" if apenas_investivel else ""
    df = query_df(
        "SELECT r.ano, r.nro_mes, m.nome AS mes, "
        "       SUM(r.valor_bruto * c.fator_liquido) AS patrimonio "
        "FROM patrimonio_registros r "
        "JOIN patrimonio_categorias c ON c.id = r.categoria_id "
        "JOIN meses m ON m.nro = r.nro_mes "
        "WHERE r.household_id=%s" + filtro + " "
        "GROUP BY r.ano, r.nro_mes, m.nome "
        "ORDER BY r.ano, r.nro_mes",
        [hh],
    )
    if not df.empty:
        df["periodo"] = pd.to_datetime(dict(year=df["ano"], month=df["nro_mes"], day=1))
    return df


def get_detalhe_mes(ano, nro_mes, household_id=None):
    """
    Detalhe de um mes por categoria (para conferencia/tabela): nome, valor_bruto,
    fator_liquido e valor_liquido (= bruto * fator). So categorias com registro no
    mes aparecem. Ordenado pela ordem das categorias.
    """
    hh = _hh(household_id)
    return query_df(
        "SELECT c.nome, r.valor_bruto, c.fator_liquido, "
        "       r.valor_bruto * c.fator_liquido AS valor_liquido "
        "FROM patrimonio_registros r "
        "JOIN patrimonio_categorias c ON c.id = r.categoria_id "
        "WHERE r.household_id=%s AND r.ano=%s AND r.nro_mes=%s "
        "ORDER BY c.ordem, c.nome",
        [hh, ano, nro_mes],
    )


# Fim do modulo de patrimonio (Networth).
