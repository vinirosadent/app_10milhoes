"""
Modulo de RECONCILIACAO do App 10M — o "termometro" da qualidade dos dados.

Existe porque o app guarda o patrimonio de DUAS formas independentes, e as duas
podem divergir sem que nada avise:

  OBSERVADO  = `patrimonio_registros`. O valor que voce le no extrato e digita.
               E' o dado primario: se o extrato diz 271.802, e' 271.802.

  DERIVADO   = `lancamentos` (aportes) + `investimentos_serie` (rendimento).
               E' reconstruido. Serve para responder "quanto disso foi dinheiro
               que eu coloquei e quanto foi o mercado que me deu".

Num mundo perfeito os dois batem em todo produto:

    aporte_acumulado + rendimento_acumulado == patrimonio_observado

Quando NAO batem, um dos tres esta errado, e a diferenca aponta qual:

  - Diferenca POSITIVA (observado > derivado): falta aporte ou falta rendimento.
    Tipicamente um deposito que nunca foi lancado, ou rendimento nao registrado.
  - Diferenca NEGATIVA (derivado > observado): sobra aporte ou sobra rendimento.
    Tipicamente uma transferencia entre contas contada como aporte novo nos dois
    lados, ou um produto liquidado que continua somando.

Foi exatamente assim que se descobriu, em ago/2026, que o DigiPortfolio tinha
15.210 de rendimento fantasma (o aporte estava sub-registrado, entao o app
atribuia todo o crescimento ao mercado) e que o Smartwealth liquidado continuava
somando 74.824 que nao existiam mais.

Por que isso NAO vira um alerta automatico que corrige sozinho: a correcao exige
documento. O app so aponta onde olhar; quem decide o valor certo e' o extrato.

Sem banco na parte de cima do modulo para o calculo ser testavel isolado.
"""
from __future__ import annotations

import pandas as pd

# Abaixo deste valor absoluto (SGD) a diferenca e' considerada arredondamento e
# nao vira alerta. Snapshots sao digitados a mao, entao alguns dolares de
# diferenca sao normais e sinalizar isso so gera ruido.
TOLERANCIA_SGD = 50.0


def classificar(diferenca: float, tolerancia: float = TOLERANCIA_SGD) -> str:
    """
    Traduz a diferenca em um dos tres estados. String simples de proposito: quem
    desenha decide o icone, este modulo nao sabe nada de UI.

      'ok'     -> dentro da tolerancia
      'falta'  -> observado > derivado (falta aporte ou rendimento lancado)
      'sobra'  -> derivado > observado (aporte ou rendimento a mais)
    """
    if abs(float(diferenca)) <= float(tolerancia):
        return "ok"
    return "falta" if float(diferenca) > 0 else "sobra"


def diagnostico(estado: str, produto: str) -> str:
    """Frase curta explicando o que a diferenca provavelmente significa."""
    if estado == "ok":
        return "Fecha com o extrato."
    if estado == "falta":
        return (f"O patrimonio de {produto} e' maior do que aporte + rendimento "
                "lancados. Provavel aporte ou rendimento nao registrado.")
    return (f"Aporte + rendimento de {produto} passam do patrimonio observado. "
            "Provavel transferencia contada como aporte novo, ou rendimento "
            "duplicado.")


# ──────────────────────────────────────────────────────────────────────────
# BLOCO DADOS — import do core aqui de proposito: o bloco acima roda sem banco.
# ──────────────────────────────────────────────────────────────────────────
from core.db import query_df, _hh   # noqa: E402


def get_reconciliacao(ano: int, mes: int, household_id=None) -> pd.DataFrame:
    """
    Compara observado x derivado, produto a produto, no mes pedido.

    So entram produtos com mapeamento em `produto_categoria_map` — sem
    mapeamento nao ha com o que comparar. Produtos liquidados devem ser
    DESMAPEADOS (e nao apagados): o historico continua em `lancamentos` para o
    BI, mas eles saem da reconciliacao, que olha so o que existe hoje.

    Colunas: produto, categoria, observado, aporte, rendimento, derivado,
             diferenca, estado.
    """
    hh = _hh(household_id)
    df = query_df(
        "SELECT p.nome AS produto, c.nome AS categoria, "
        "  ROUND(r.valor_bruto * c.fator_liquido, 2) AS observado, "
        "  COALESCE(( SELECT SUM(l.valor) FROM lancamentos l "
        "             WHERE l.household_id = %s AND l.item = p.nome "
        "               AND l.tipo_geral = 'Investimento'), 0) AS aporte, "
        "  COALESCE(( SELECT SUM(s.rendimento) FROM investimentos_serie s "
        "             WHERE s.household_id = %s AND s.produto_id = p.id), 0) AS rendimento "
        "FROM produto_categoria_map m "
        "JOIN config_investimentos p ON p.id = m.produto_id "
        "JOIN patrimonio_categorias c ON c.id = m.categoria_id "
        "JOIN patrimonio_registros r ON r.categoria_id = c.id "
        "     AND r.household_id = m.household_id "
        "     AND r.ano = %s AND r.nro_mes = %s "
        "WHERE m.household_id = %s AND c.investivel = TRUE "
        "ORDER BY r.valor_bruto DESC",
        [hh, hh, int(ano), int(mes), hh],
    )
    if df.empty:
        return pd.DataFrame(columns=["produto", "categoria", "observado", "aporte",
                                     "rendimento", "derivado", "diferenca", "estado"])
    for c in ("observado", "aporte", "rendimento"):
        df[c] = df[c].astype(float)
    df["derivado"] = df["aporte"] + df["rendimento"]
    df["diferenca"] = df["observado"] - df["derivado"]
    df["estado"] = df["diferenca"].map(classificar)
    return df


def get_totais_paginas(ano: int, mes: int, household_id=None) -> dict:
    """
    Os dois totais que as paginas Patrimonio e Investimentos mostram, lado a lado.

    Eles DIVERGEM por construcao, e isso nao e' bug:
      - `patrimonio` conta so o que existe HOJE (categorias com registro no mes).
      - `investimentos` soma o historico INTEIRO, inclusive produtos ja
        liquidados (XP, Smartwealth, SRS Manu VR). E' a leitura "tudo que ja
        passou pela carteira".

    A funcao existe para a diferenca ficar explicada na tela em vez de o usuario
    achar que um dos dois esta errado.
    """
    hh = _hh(household_id)
    pat = query_df(
        "SELECT COALESCE(SUM(r.valor_bruto * c.fator_liquido), 0) AS v "
        "FROM patrimonio_registros r JOIN patrimonio_categorias c ON c.id = r.categoria_id "
        "WHERE r.household_id = %s AND c.investivel = TRUE AND r.ano = %s AND r.nro_mes = %s",
        [hh, int(ano), int(mes)],
    )
    ap = query_df(
        "SELECT COALESCE(SUM(valor), 0) AS v FROM lancamentos "
        "WHERE household_id = %s AND tipo_geral = 'Investimento'", [hh])
    rd = query_df(
        "SELECT COALESCE(SUM(rendimento), 0) AS v FROM investimentos_serie "
        "WHERE household_id = %s", [hh])

    patrimonio = float(pat["v"].values[0])
    aporte = float(ap["v"].values[0])
    rendimento = float(rd["v"].values[0])
    return {
        "patrimonio": patrimonio,
        "aporte": aporte,
        "rendimento": rendimento,
        "investimentos": aporte + rendimento,
        "diferenca": (aporte + rendimento) - patrimonio,
    }


def get_produtos_orfaos(household_id=None) -> pd.DataFrame:
    """
    Produtos com movimento em `lancamentos` mas SEM mapeamento para categoria de
    patrimonio. Sao os que escapam da reconciliacao — ou porque foram liquidados
    (esperado) ou porque o mapeamento nunca foi feito (erro).

    Colunas: produto, ativo, aporte, rendimento, derivado.
    """
    hh = _hh(household_id)
    return query_df(
        "SELECT p.nome AS produto, p.ativo, "
        "  COALESCE(( SELECT SUM(l.valor) FROM lancamentos l "
        "             WHERE l.household_id = %s AND l.item = p.nome "
        "               AND l.tipo_geral = 'Investimento'), 0) AS aporte, "
        "  COALESCE(( SELECT SUM(s.rendimento) FROM investimentos_serie s "
        "             WHERE s.household_id = %s AND s.produto_id = p.id), 0) AS rendimento "
        "FROM config_investimentos p "
        "WHERE p.household_id = %s "
        "  AND NOT EXISTS ( SELECT 1 FROM produto_categoria_map m "
        "                   WHERE m.produto_id = p.id AND m.household_id = p.household_id) "
        "ORDER BY p.ativo DESC, p.nome",
        [hh, hh, hh],
    )
