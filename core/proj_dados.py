"""
Camada de DADOS da projecao - so leitura do Supabase.
Modulo core/proj_dados.py do App 10M.

Segunda das tres camadas (decisao D-07):

    core/proj_motor.py    -> matematica pura, zero banco
    core/proj_dados.py    -> so leitura do banco (este arquivo)
    pages/08_Projecoes.py -> so UI

Regras deste modulo:

- SO LE. Nenhum INSERT/UPDATE/DELETE (decisao D-08). A V1 e read-only.
- Nao faz matematica de projecao - devolve numeros crus e deixa o motor
  calcular. A unica aritmetica aqui e a que define a JANELA e o teto do
  SRS, porque isso e regra de origem do dado, nao de projecao.
- Todo retorno carrega PROCEDENCIA (janela usada, contagem de
  lancamentos, mes de referencia), porque a UI precisa exibir de onde
  cada numero veio (D-07).
- 'hoje' e argumento OBRIGATORIO em tudo que depende de calendario. Sem
  default. Motivo: date.today() roda em UTC no Streamlit Cloud, nao em
  Asia/Singapore; nas primeiras 8h do dia 1 de cada mes a janela
  escorregaria um mes inteiro sem aviso.

Formula da capacidade mensal (decisao D-01, revisada em 23/08/2026):

    capacidade = media(24 meses fechados, lancamentos de Investimento
                       cujo item NAO comeca com 'SRS')
               + teto anual do SRS / 12

O SRS sai da media e entra pelo teto porque e constante conhecida (o
Vinicius contribui o teto todo ano), nao algo a estimar. Isso torna a
formula imune a como o lancamento foi registrado - e ha registros
inconsistentes na base (contribuicao anual ora distribuida em 12
parcelas, ora lancada em bloco num mes so). O filtro e ESTRUTURAL
(item NOT ILIKE 'SRS%%'), nao lista de nomes: conta SRS nova entra na
regra sozinha, sem cadastro em lugar nenhum.

NAO ha linha de "parcela do apartamento liberada": o financiamento foi
quitado em maio/2026 com resgate da XP (Brasil). Nao e evento futuro.
"""

from __future__ import annotations

from datetime import date

from core.db import query_df, _hh
from core.proj_motor import meses_entre, somar_meses, ultimo_mes_fechado

__all__ = [
    "JANELA_MESES_PADRAO",
    "get_parametros",
    "get_base_patrimonial",
    "get_capacidade_mensal",
    "get_meses_ate_elegibilidade",
    "montar_entradas_projecao",
]


# Janela da media de aportes, em meses. DEVE ser multiplo de 12 (decisao
# D-04): o bonus de julho e um outlier RECORRENTE, e o tratamento correto
# e garantir que a janela contenha exatamente uma ocorrencia por ano.
# Janelas de 6 meses estao proibidas por construcao - foram a causa dos
# numeros que "dancavam" na pagina antiga.
JANELA_MESES_PADRAO = 24


def _ym(ano: int, mes: int) -> int:
    """Converte (ano, mes) na chave inteira AAAAMM usada nos filtros."""
    return ano * 100 + mes


def _vazio(valor) -> bool:
    """
    True se o valor vindo do banco deve ser tratado como ausente.

    Cuidado necessario: o pandas converte NULL do Postgres em NaN quando
    a coluna e numerica, e NaN NAO e None - a checagem ingenua
    `valor is not None` passa e float(NaN) devolve nan silenciosamente,
    contaminando todo o calculo a jusante sem erro visivel. NaN e o unico
    valor que nao e igual a si mesmo, e assim que o detectamos aqui sem
    precisar importar pandas.
    """
    return valor is None or valor != valor


def _parse_ano_mes(texto: str) -> tuple[int, int]:
    """Converte 'AAAA-MM' em (ano, mes). Levanta ValueError se malformado."""
    partes = str(texto).strip().split("-")
    if len(partes) < 2:
        raise ValueError(f"formato de ano-mes invalido: {texto!r} (esperado AAAA-MM)")
    return int(partes[0]), int(partes[1])


def get_parametros(household_id: int | None = None) -> dict:
    """
    Le a tabela `parametros` e devolve um dict {chave: valor}, onde o
    valor e o campo numerico quando existe e o texto caso contrario.

    Chaves relevantes pra projecao: meta_patrimonio, meta_data,
    retorno_padrao, srs_teto_anual, srs_primeira_contribuicao.
    (apto_liberado_mensal existe mas esta marcado OBSOLETO no banco -
    nao usar.)
    """
    hh = _hh(household_id)
    df = query_df(
        "select chave, valor, valor_texto from parametros where household_id = %s",
        (hh,),
    )
    saida: dict = {}
    for _, linha in df.iterrows():
        valor, texto = linha["valor"], linha["valor_texto"]
        if not _vazio(valor):
            saida[linha["chave"]] = float(valor)
        elif not _vazio(texto):
            saida[linha["chave"]] = texto
        else:
            saida[linha["chave"]] = None
    return saida


def get_base_patrimonial(household_id: int | None = None, ym_max: int | None = None) -> dict:
    """
    Devolve a base patrimonial do ultimo mes disponivel, ja separada em:

        saldo_outros -> soma LIQUIDA de todas as categorias investiveis
                        que NAO tem regra especial de projecao
        srs_bruto    -> soma BRUTA das categorias que tem regra especial
        fator_pre    -> fator_liquido dessas categorias (valor HOJE)
        fator_pos    -> fator_liquido_projecao (valor pos-elegibilidade)

    A categoria "especial" NAO e identificada por id fixo: e aquela com
    `fator_liquido_projecao IS NOT NULL`. Assim, se um dia o SRS da
    Juliana ficar elegivel, basta preencher a coluna dela - nenhum codigo
    muda. Se nenhuma categoria tiver a coluna preenchida, srs_bruto vem
    0 e os fatores vem 1.0, e a projecao degenera no caso simples.

    Categorias com investivel = false (o Apartamento) ficam FORA por
    decisao D-03: e estoque em BRL, estatico, que so vira dinheiro na
    venda - soma-lo faria a meta parecer batida sem um dolar a mais
    disponivel.
    """
    hh = _hh(household_id)
    teto = ym_max if ym_max is not None else 999912
    sql = """
        with ref as (
          select max(ano*100 + nro_mes) as ym
          from patrimonio_registros
          where household_id = %s and (ano*100 + nro_mes) <= %s
        )
        select
          coalesce(sum(case when c.fator_liquido_projecao is null
                            then r.valor_bruto * coalesce(c.fator_liquido, 1)
                            else 0 end), 0)                                  as saldo_outros,
          coalesce(sum(case when c.fator_liquido_projecao is not null
                            then r.valor_bruto else 0 end), 0)               as srs_bruto,
          max(c.fator_liquido)          filter (where c.fator_liquido_projecao is not null) as fator_pre,
          max(c.fator_liquido_projecao) filter (where c.fator_liquido_projecao is not null) as fator_pos,
          count(*) filter (where c.fator_liquido_projecao is not null)       as n_categorias_srs,
          count(*)                                                          as n_categorias,
          (select ym from ref)                                              as mes_ref
        from patrimonio_registros r
        join patrimonio_categorias c on c.id = r.categoria_id
        where r.household_id = %s
          and c.investivel = true
          and (r.ano*100 + r.nro_mes) = (select ym from ref)
    """
    df = query_df(sql, (hh, teto, hh))
    if df.empty or _vazio(df.iloc[0]["mes_ref"]):
        return {
            "saldo_outros": 0.0, "srs_bruto": 0.0,
            "fator_pre": 1.0, "fator_pos": 1.0,
            "n_categorias": 0, "n_categorias_srs": 0,
            "mes_ref": None, "mes_ref_texto": "sem dados",
        }

    l = df.iloc[0]
    ym = int(l["mes_ref"])
    fator_pre = 1.0 if _vazio(l["fator_pre"]) else float(l["fator_pre"])
    fator_pos = 1.0 if _vazio(l["fator_pos"]) else float(l["fator_pos"])
    return {
        "saldo_outros": float(l["saldo_outros"]),
        "srs_bruto": float(l["srs_bruto"]),
        "fator_pre": fator_pre,
        "fator_pos": fator_pos,
        "n_categorias": int(l["n_categorias"]),
        "n_categorias_srs": int(l["n_categorias_srs"]),
        "mes_ref": ym,
        "mes_ref_texto": f"{ym % 100:02d}/{ym // 100}",
    }


def get_capacidade_mensal(
    hoje: date,
    household_id: int | None = None,
    n_meses: int = JANELA_MESES_PADRAO,
) -> dict:
    """
    Capacidade mensal de investimento (formula D-01).

    'hoje' e OBRIGATORIO e deve ser a data de Singapura - ver docstring
    do modulo. A janela termina no ultimo mes FECHADO (se hoje e
    23/ago/2026, agosto ainda corre, entao a janela termina em jul/2026).

    Devolve as duas parcelas SEPARADAS, mais a procedencia de cada uma,
    porque a tela mostra as linhas separadamente (D-07):

        media_aportes  -> media dos lancamentos nao-SRS na janela
        srs_mensal     -> teto anual do SRS / 12
        capacidade     -> soma das duas

    Levanta ValueError se n_meses nao for multiplo de 12 (D-04).
    """
    if n_meses <= 0 or n_meses % 12 != 0:
        raise ValueError(
            f"janela deve ser multiplo de 12 meses (recebido {n_meses}). "
            "Ver decisao D-04: o bonus de julho e outlier recorrente e a "
            "janela precisa conter exatamente uma ocorrencia por ano."
        )

    hh = _hh(household_id)
    fim = ultimo_mes_fechado(hoje)                    # dia 1 do ultimo mes fechado
    ini = somar_meses(fim, -(n_meses - 1))            # inclusive
    ym_ini, ym_fim = _ym(ini.year, ini.month), _ym(fim.year, fim.month)

    sql = """
        select
          count(*)                            as n_lancamentos,
          count(distinct ano*100 + nro_mes)   as n_meses_com_lancamento,
          coalesce(sum(valor), 0)             as total
        from lancamentos
        where household_id = %s
          and tipo_geral = 'Investimento'
          and item not ilike 'SRS%%'
          and (ano*100 + nro_mes) between %s and %s
    """
    df = query_df(sql, (hh, ym_ini, ym_fim))
    l = df.iloc[0]
    total = float(l["total"])
    media = total / n_meses

    params = get_parametros(hh)
    teto_bruto = params.get("srs_teto_anual")
    teto = 0.0 if _vazio(teto_bruto) else float(teto_bruto)
    srs_mensal = teto / 12.0

    return {
        "media_aportes": media,
        "srs_mensal": srs_mensal,
        "capacidade": media + srs_mensal,
        # procedencia
        "janela_ini": ym_ini,
        "janela_fim": ym_fim,
        "janela_texto": f"{ym_ini % 100:02d}/{ym_ini // 100} a {ym_fim % 100:02d}/{ym_fim // 100}",
        "n_meses": n_meses,
        "n_lancamentos": int(l["n_lancamentos"]),
        "n_meses_com_lancamento": int(l["n_meses_com_lancamento"]),
        "total_janela": total,
        "srs_teto_anual": teto,
    }


def get_meses_ate_elegibilidade(hoje: date, household_id: int | None = None) -> dict:
    """
    Meses de 'hoje' ate o SRS completar 10 anos desde a primeira
    contribuicao - o marco em que o saque deixa de custar 5% de multa +
    100% tributavel e passa a ser sem multa e 50% tributavel.

    Devolve dict com meses (nunca negativo), a data de elegibilidade e a
    origem, pra tela poder mostrar a procedencia. Se ja elegivel, meses
    vem 0 e 'ja_elegivel' vem True.

    Se o parametro srs_primeira_contribuicao nao existir, devolve meses
    = 0 e ja_elegivel = None (indeterminado) - cabe a UI avisar em vez
    de assumir silenciosamente um dos regimes.
    """
    params = get_parametros(household_id)
    texto = params.get("srs_primeira_contribuicao")
    if _vazio(texto) or not str(texto).strip():
        return {"meses": 0, "data_elegibilidade": None, "ja_elegivel": None,
                "primeira_contribuicao": None}

    ano, mes = _parse_ano_mes(texto)
    primeira = date(ano, mes, 1)
    elegibilidade = somar_meses(primeira, 120)        # 10 anos
    meses = meses_entre(date(hoje.year, hoje.month, 1), elegibilidade)
    return {
        "meses": max(meses, 0),
        "data_elegibilidade": elegibilidade,
        "ja_elegivel": meses <= 0,
        "primeira_contribuicao": primeira,
    }


def montar_entradas_projecao(
    hoje: date,
    household_id: int | None = None,
    n_meses: int = JANELA_MESES_PADRAO,
) -> dict:
    """
    Reune tudo que `proj_motor.resolver_meta_com_srs` precisa, numa
    chamada so. Devolve os blocos separados (base, capacidade, srs,
    parametros) pra UI poder exibir procedencia de cada numero sem
    reconsultar o banco.

    Este modulo NAO chama o motor - so prepara a entrada. Quem combina
    os dois e a pagina.
    """
    hh = _hh(household_id)
    base = get_base_patrimonial(hh)
    cap = get_capacidade_mensal(hoje, hh, n_meses)
    srs = get_meses_ate_elegibilidade(hoje, hh)
    params = get_parametros(hh)

    return {
        "base": base,
        "capacidade": cap,
        "srs": srs,
        "parametros": params,
        "hoje": hoje,
        # atalho com os argumentos ja no formato do motor
        "args_motor": {
            "saldo_outros": base["saldo_outros"],
            "srs_bruto": base["srs_bruto"],
            "fator_pre": base["fator_pre"],
            "fator_pos": base["fator_pos"],
            "meses_ate_elegibilidade": srs["meses"],
            "aporte_mensal": cap["capacidade"],
        },
    }
