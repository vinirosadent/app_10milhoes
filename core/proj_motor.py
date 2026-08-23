"""
Motor de projecao financeira - matematica pura, sem dependencia de banco.
Modulo core/proj_motor.py do App 10M.

Este modulo NAO acessa o Supabase e NAO conhece o schema do app. Recebe
numeros prontos (saldo atual, capacidade mensal, taxa de retorno, meta) e
devolve resultados de projecao. Faz parte da arquitetura em 3 camadas
(decisao D-07 do handoff Projecoes):

    core/proj_motor.py  -> so numeros, testavel isolado (este arquivo)
    core/proj_dados.py  -> so leitura do Supabase, devolve DataFrames crus
    pages/08_Projecoes.py -> so UI, cada numero exibido carrega procedencia

V1 (decisao D-02): projecao de cenario unico, saldo atual + capacidade
mensal -> data projetada da meta. Sem dividendos, sem multiplos cenarios.
Read-only (D-08): este modulo nunca escreve em lugar nenhum.
"""

from __future__ import annotations

import math
from datetime import date

__all__ = [
    "MAX_MESES_PROJECAO",
    "taxa_mensal",
    "projetar",
    "valor_em",
    "meses_ate_meta",
    "aporte_necessario",
    "data_projetada_meta",
    "meses_entre",
    "somar_meses",
    "ultimo_mes_fechado",
    "formatar_prazo",
    "resolver_meta_com_srs",
    "REGIME_PRE",
    "REGIME_POS",
    "REGIME_FRONTEIRA",
    "REGIME_INATINGIVEL",
]


# Horizonte maximo que a projecao aceita datar: 100 anos (1200 meses).
# Alem disso o resultado nao e informacao util - e sintoma de capacidade
# mensal proxima de zero (dado faltando, filtro errado em proj_dados) ou
# de meta inatingivel na pratica. Sem esse teto, um prazo absurdo estoura
# o ano maximo do date (9999) e trava a pagina.
MAX_MESES_PROJECAO = 1200


# ---------------------------------------------------------------------------
# Matematica pura
# ---------------------------------------------------------------------------

def taxa_mensal(retorno_anual: float) -> float:
    """
    Converte uma taxa de retorno anual (ex: 0.03 = 3% ao ano) na taxa
    mensal equivalente, por juros compostos.

        taxa_mensal = (1 + retorno_anual) ** (1/12) - 1
    """
    if retorno_anual <= -1:
        raise ValueError("retorno_anual deve ser maior que -100% (-1.0)")
    return (1 + retorno_anual) ** (1 / 12) - 1


def projetar(
    saldo_inicial: float,
    aporte_mensal: float,
    taxa_mensal_: float,
    meses: int,
) -> list[float]:
    """
    Projeta o saldo mes a mes. Aporte lancado no FIM de cada mes
    (anuidade postecipada), rendimento composto sobre o saldo do inicio
    do mes.

    Devolve lista de tamanho (meses + 1): posicao 0 = saldo_inicial (mes
    atual, sem aporte/rendimento ainda), posicao k = saldo apos k meses
    completos. Uso: series pra grafico de trajetoria (BI futuro).
    """
    if meses < 0:
        raise ValueError("meses nao pode ser negativo")
    serie = [saldo_inicial]
    saldo = saldo_inicial
    for _ in range(meses):
        saldo = saldo * (1 + taxa_mensal_) + aporte_mensal
        serie.append(saldo)
    return serie


def valor_em(
    saldo_inicial: float,
    aporte_mensal: float,
    taxa_mensal_: float,
    meses: int,
) -> float:
    """
    Valor projetado apos um numero inteiro de meses, por formula fechada
    de anuidade (mais preciso e mais rapido que iterar quando meses e
    grande; projetar() acima serve pra quando se quer a serie inteira).

        FV = PV*(1+i)^n + PMT * [(1+i)^n - 1] / i     (i != 0)
        FV = PV + PMT * n                               (i == 0)
    """
    if meses < 0:
        raise ValueError("meses nao pode ser negativo")
    i = taxa_mensal_
    n = meses
    if i == 0:
        return saldo_inicial + aporte_mensal * n
    fator = (1 + i) ** n
    return saldo_inicial * fator + aporte_mensal * (fator - 1) / i


def meses_ate_meta(
    saldo_inicial: float,
    aporte_mensal: float,
    taxa_mensal_: float,
    meta: float,
) -> float | None:
    """
    Numero de meses (fracionario) ate o saldo atingir a meta, com aporte
    mensal fixo e taxa de retorno mensal constante. Resolve a formula
    fechada de anuidade pra n:

        (1+i)^n = (FV + PMT/i) / (PV + PMT/i)     (i != 0)
        n = ln(...) / ln(1+i)

    Casos especiais:
    - saldo_inicial ja >= meta -> retorna 0.0.
    - i == 0 (taxa zero) -> relacao linear: n = (meta - PV) / PMT.
    - parametros insuficientes pra crescer ate a meta (ex.: aporte e
      saldo zerados) -> retorna None (meta inatingivel).

    Nota: valido pro regime de taxa positiva ou nula, que e o caso de uso
    do app (retorno_padrao = 0.03). Regimes de taxa negativa nao foram
    validados e podem devolver resultado matematicamente consistente mas
    irreal (serie com teto assintotico abaixo da meta).
    """
    if saldo_inicial >= meta:
        return 0.0

    i = taxa_mensal_

    if i == 0:
        if aporte_mensal <= 0:
            return None
        return (meta - saldo_inicial) / aporte_mensal

    pv_ajustado = saldo_inicial + aporte_mensal / i
    fv_ajustado = meta + aporte_mensal / i

    if pv_ajustado <= 0 or fv_ajustado <= 0:
        return None

    razao = fv_ajustado / pv_ajustado
    if razao <= 0:
        return None

    denom = math.log(1 + i)
    if denom == 0:
        return None

    n = math.log(razao) / denom
    if n < 0:
        return None
    return n


def aporte_necessario(
    saldo_inicial: float,
    taxa_mensal_: float,
    meses: int,
    meta: float,
) -> float:
    """
    Aporte mensal fixo necessario pra atingir a meta em exatamente
    'meses' meses, dada a taxa mensal. Util pra simulacao futura
    ("quanto eu precisaria investir por mes pra bater a meta ate X").

        PMT = (FV - PV*(1+i)^n) * i / [(1+i)^n - 1]     (i != 0)
        PMT = (FV - PV) / n                               (i == 0)
    """
    if meses <= 0:
        raise ValueError("meses deve ser maior que zero")
    i = taxa_mensal_
    n = meses
    if i == 0:
        return (meta - saldo_inicial) / n
    fator = (1 + i) ** n
    return (meta - saldo_inicial * fator) * i / (fator - 1)


def data_projetada_meta(
    saldo_inicial: float,
    aporte_mensal: float,
    taxa_mensal_: float,
    meta: float,
    data_base: date,
) -> tuple[date | None, float | None]:
    """
    Combina meses_ate_meta + somar_meses: devolve (data_projetada,
    meses_fracionarios) a partir de data_base. O numero de meses e
    arredondado PRA CIMA antes de somar (fracao de mes conta como mais
    um mes completo, pra nao antecipar a data).

    Retornos:
    - (date, meses)  -> projecao valida.
    - (None, None)   -> meta inatingivel com os parametros informados.
    - (None, meses)  -> prazo acima de MAX_MESES_PROJECAO (100 anos). A
      data nao e calculada porque nao seria informacao util, mas o numero
      de meses volta pra UI poder dizer "prazo superior a 100 anos" e
      sinalizar que a capacidade mensal provavelmente esta errada.

    A UI deve distinguir os tres casos - nao tratar todo None como erro.
    """
    meses = meses_ate_meta(saldo_inicial, aporte_mensal, taxa_mensal_, meta)
    if meses is None:
        return None, None
    if meses > MAX_MESES_PROJECAO:
        return None, meses
    meses_inteiros = math.ceil(meses)
    return somar_meses(data_base, meses_inteiros), meses


# ---------------------------------------------------------------------------
# Calendario
# ---------------------------------------------------------------------------

def meses_entre(data_inicio: date, data_fim: date) -> int:
    """
    Numero de meses entre duas datas (so considera ano/mes, ignora o
    dia). Positivo se data_fim e depois de data_inicio.
    """
    return (data_fim.year - data_inicio.year) * 12 + (data_fim.month - data_inicio.month)


def somar_meses(data_base: date, meses: int) -> date:
    """
    Soma (ou subtrai, se meses < 0) um numero inteiro de meses a uma
    data, preservando o dia quando possivel. Se o dia original nao
    existir no mes de destino (ex.: 31/jan + 1 mes = fevereiro), cai
    pro ultimo dia valido desse mes.

    Levanta OverflowError se o resultado cair fora do intervalo que o
    modulo datetime suporta (ano 1 a 9999). Sem essa guarda, o ajuste de
    dia abaixo entraria em loop infinito tentando corrigir um erro que
    nao e do dia, e sim do ano - e travaria a pagina inteira.
    """
    total_meses = (data_base.year * 12 + (data_base.month - 1)) + meses
    ano_novo = total_meses // 12
    mes_novo = total_meses % 12 + 1
    if not (date.min.year <= ano_novo <= date.max.year):
        raise OverflowError(
            f"data resultante fora do intervalo suportado (ano {ano_novo})"
        )
    dia_novo = data_base.day
    while dia_novo > 1:
        try:
            return date(ano_novo, mes_novo, dia_novo)
        except ValueError:
            dia_novo -= 1
    return date(ano_novo, mes_novo, 1)


def ultimo_mes_fechado(hoje: date | None = None) -> date:
    """
    Dia 1 do ultimo mes TOTALMENTE fechado antes de hoje. Ex.: se hoje =
    23/ago/2026, agosto ainda esta em curso -> devolve date(2026, 7, 1).

    ATENCAO ao default: sem argumento, usa date.today(), que no Streamlit
    Cloud e UTC, nao Asia/Singapore (UTC+8). Nas primeiras 8 horas do dia
    1 de cada mes (00:00-08:00 SGT) o UTC ainda esta no mes anterior, e a
    funcao devolveria um mes A MENOS do que deveria - a janela de 24 meses
    escorregaria por um mes sem aviso. Quem chama em producao deve passar
    'hoje' explicitamente com a data de Singapura.
    """
    if hoje is None:
        hoje = date.today()
    primeiro_dia_mes_atual = date(hoje.year, hoje.month, 1)
    return somar_meses(primeiro_dia_mes_atual, -1)


def formatar_prazo(meses: float | None) -> str:
    """
    Formata um numero de meses (pode ser fracionario) num texto tipo
    "6 anos e 3 meses". Arredonda PRA CIMA (fracao de mes conta como
    mais um mes, pra nao subestimar o prazo).

    "meta ja atingida" se meses <= 0.
    "meta inatingivel com os parametros atuais" se meses for None.
    """
    if meses is None:
        return "meta inatingivel com os parametros atuais"
    if meses <= 0:
        return "meta ja atingida"

    total_meses = math.ceil(meses)
    anos = total_meses // 12
    meses_restantes = total_meses % 12

    partes = []
    if anos > 0:
        partes.append(f"{anos} ano" if anos == 1 else f"{anos} anos")
    if meses_restantes > 0:
        partes.append(f"{meses_restantes} mes" if meses_restantes == 1 else f"{meses_restantes} meses")
    if not partes:
        partes.append("menos de 1 mes")

    return " e ".join(partes)


# ---------------------------------------------------------------------------
# Resolucao do regime do SRS (ponto fixo fator <-> data)
# ---------------------------------------------------------------------------

# Regimes devolvidos por resolver_meta_com_srs.
REGIME_PRE = "pre"                # meta atingida ANTES da elegibilidade -> fator de saque antecipado
REGIME_POS = "pos"                # meta atingida DEPOIS -> fator pos-10-anos
REGIME_FRONTEIRA = "fronteira"    # os dois cenarios se contradizem
REGIME_INATINGIVEL = "inatingivel"


def resolver_meta_com_srs(
    saldo_outros: float,
    srs_bruto: float,
    fator_pre: float,
    fator_pos: float,
    meses_ate_elegibilidade: int,
    aporte_mensal: float,
    taxa_mensal_: float,
    meta: float,
    data_base: date,
) -> dict:
    """
    Resolve a circularidade entre o fator liquido do SRS e a data da meta.

    O problema: o fator que se aplica ao SRS depende de QUANDO o saque
    acontece (antes ou depois da elegibilidade de 10 anos), mas a data em
    que a meta e atingida depende do saldo, que depende do fator. E um
    ponto fixo - nao da pra calcular direto.

    Metodo: projeta os dois cenarios (fator_pre e fator_pos) e escolhe o
    que e AUTO-CONSISTENTE, isto e, aquele cuja data resultante cai do
    lado da fronteira que o proprio fator pressupoe.

    Tres desfechos possiveis:

    - REGIME_PRE: a meta cai antes da elegibilidade mesmo no cenario
      otimista -> vale o fator de saque antecipado.
    - REGIME_POS: a meta cai depois da elegibilidade mesmo no cenario
      conservador -> vale o fator pos-10-anos.
    - REGIME_FRONTEIRA: os dois se contradizem. Medindo por fator_pre a
      meta cai DEPOIS da elegibilidade (logo o fator deveria ser o pos);
      medindo por fator_pos ela cai ANTES (logo deveria ser o pre). Isso
      acontece quando o proprio degrau de elegibilidade e grande o
      bastante pra cruzar a meta sozinho. Nao e erro de calculo: e uma
      faixa de metas em que a meta e atingida NO momento da virada.
      Convencao adotada: devolve o mes SEGUINTE a elegibilidade, porque o
      comportamento racional e esperar destravar o SRS em vez de sacar
      com multa a poucas semanas da virada.

    Devolve dict com:
        regime            -> uma das constantes REGIME_*
        data              -> date da meta, ou None se inatingivel
        meses             -> meses fracionarios, ou None
        fator_aplicado    -> fator usado no SRS (None se inatingivel)
        saldo_inicial     -> saldo de partida sob o fator aplicado
        data_pre/data_pos -> as duas datas candidatas, pra UI mostrar a
                             procedencia do numero (exigencia D-07)
    """
    saldo_pre = saldo_outros + srs_bruto * fator_pre
    saldo_pos = saldo_outros + srs_bruto * fator_pos

    d_pre, m_pre = data_projetada_meta(saldo_pre, aporte_mensal, taxa_mensal_, meta, data_base)
    d_pos, m_pos = data_projetada_meta(saldo_pos, aporte_mensal, taxa_mensal_, meta, data_base)

    base = {"data_pre": d_pre, "data_pos": d_pos, "meses_pre": m_pre, "meses_pos": m_pos}

    # Inatingivel nos dois cenarios: nem o mais otimista chega la.
    if m_pre is None and m_pos is None:
        return {**base, "regime": REGIME_INATINGIVEL, "data": None, "meses": None,
                "fator_aplicado": None, "saldo_inicial": saldo_pos}

    # "Atinge depois da elegibilidade" inclui o caso de nao atingir nunca.
    def depois_da_elegibilidade(meses):
        return meses is None or meses >= meses_ate_elegibilidade

    pre_cai_depois = depois_da_elegibilidade(m_pre)
    pos_cai_depois = depois_da_elegibilidade(m_pos)

    if not pre_cai_depois:
        # Ate no cenario conservador a meta chega antes da virada.
        return {**base, "regime": REGIME_PRE, "data": d_pre, "meses": m_pre,
                "fator_aplicado": fator_pre, "saldo_inicial": saldo_pre}

    if pos_cai_depois:
        # Ate no cenario otimista a meta so chega depois da virada.
        return {**base, "regime": REGIME_POS, "data": d_pos, "meses": m_pos,
                "fator_aplicado": fator_pos, "saldo_inicial": saldo_pos}

    # Contradicao: o degrau de elegibilidade sozinho cruza a meta.
    meses_fronteira = meses_ate_elegibilidade + 1
    return {**base, "regime": REGIME_FRONTEIRA,
            "data": somar_meses(data_base, meses_fronteira),
            "meses": float(meses_fronteira),
            "fator_aplicado": fator_pos, "saldo_inicial": saldo_pos}
