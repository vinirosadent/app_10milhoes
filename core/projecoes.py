"""
Modulo de PROJECOES do App 10M — o motor de "para onde estou indo".

Separa claramente duas coisas que a projecao antiga misturava:

  - APORTE: fluxo que voce controla, em SGD/mes, constante ao longo da projecao.
  - RETORNO: taxa anual aplicada sobre o SALDO, que por definicao compoe.

A formula do mes e sempre a mesma, e da pra conferir de cabeca:

    saldo_final = saldo_inicial * (1 + taxa_mensal) + aporte

Com taxa=0 vira soma pura ("so o que eu coloco") — o PISO da projecao, que nao
tem como ser otimista demais. Por isso a pagina desenha sempre DUAS linhas: o
piso (taxa 0) e o cenario escolhido.

Convencoes do modulo:
  - Tudo em SGD. Ativos em outra moeda ja chegam convertidos pelo fator_liquido
    da categoria de patrimonio (ex.: 'Apartamento (BRL)' tem fator = cambio).
  - PATRIMONIO INVESTIVEL = so categorias com investivel = TRUE. Imovel de uso
    entra no patrimonio total mas NAO na projecao (nao da pra viver de 4% dele
    sem vender).
  - Os parametros configuraveis (cambio, meta, taxa padrao) vivem na tabela
    `parametros`, nunca chumbados aqui.
  - MES EM ABERTO NAO ENTRA EM MEDIA. Ver `ultimo_mes_fechado()` — o mes
    corrente so tem parte dos lancamentos, e incluir essa fracao na janela
    subestima o ritmo de forma que cresce ao longo do mes.

Organizado em 2 blocos:
  1) PURO — matematica de projecao, sem banco e sem Streamlit. Testavel isolado.
  2) DADOS — leitura do banco (patrimonio investivel, ritmo de aporte, parametros).
"""
from __future__ import annotations

from datetime import date

import pandas as pd

# ──────────────────────────────────────────────────────────────────────────
# 1) BLOCO PURO — matematica da projecao (sem banco, sem Streamlit)
# ──────────────────────────────────────────────────────────────────────────

MAX_MESES = 900   # trava de seguranca dos lacos (75 anos)


def taxa_mensal(taxa_anual: float) -> float:
    """
    Converte taxa anual em mensal EQUIVALENTE (composta), nao dividindo por 12.
    5% ao ano = 1.05^(1/12) - 1 = 0.407%/mes, nao 0.4167%. Dividir por 12
    superestima: (1+0.05/12)^12 = 5.12% ao ano.
    """
    return (1.0 + float(taxa_anual)) ** (1.0 / 12.0) - 1.0


def projetar(saldo_inicial: float, aporte_mensal: float, taxa_anual: float,
             meses: int) -> list:
    """
    Projeta mes a mes e devolve a LISTA de saldos (tamanho = meses), comecando
    pelo saldo do 1o mes projetado. Aporte entra no fim do mes (convencao
    conservadora: nao rende no proprio mes em que foi feito).
    """
    r = taxa_mensal(taxa_anual)
    saldo = float(saldo_inicial)
    out = []
    for _ in range(max(0, int(meses))):
        saldo = saldo * (1.0 + r) + float(aporte_mensal)
        out.append(saldo)
    return out


def valor_em(saldo_inicial: float, aporte_mensal: float, taxa_anual: float,
             meses: int) -> float:
    """Quanto terei daqui a N meses. Modo 'dada a data, quanto tenho'."""
    serie = projetar(saldo_inicial, aporte_mensal, taxa_anual, meses)
    return serie[-1] if serie else float(saldo_inicial)


def meses_ate_meta(saldo_inicial: float, aporte_mensal: float,
                   taxa_anual: float, meta: float):
    """
    Em quantos meses atinjo a meta. Modo 'dado o alvo, quando chego'.
    Devolve int (meses) ou None se nao chega dentro de MAX_MESES — o que
    acontece quando aporte<=0 e taxa nao cobre a diferenca.
    """
    if float(saldo_inicial) >= float(meta):
        return 0
    r = taxa_mensal(taxa_anual)
    saldo, m = float(saldo_inicial), 0
    while saldo < float(meta) and m < MAX_MESES:
        saldo = saldo * (1.0 + r) + float(aporte_mensal)
        m += 1
    return m if saldo >= float(meta) else None


def aporte_necessario(saldo_inicial: float, meta: float, taxa_anual: float,
                      meses: int):
    """
    Quanto preciso aportar por mes para atingir a meta na data. Modo
    'dado alvo + data, quanto preciso guardar' — o mais acionavel dos tres.

    Resolve em forma FECHADA (valor futuro de uma anuidade postecipada):
        meta = P0*(1+r)^n + A * [((1+r)^n - 1) / r]
    Isolando A. Com r=0 vira (meta - P0)/n. Devolve 0.0 se o saldo inicial
    projetado ja passa da meta sem aporte nenhum.
    """
    n = int(meses)
    if n <= 0:
        return None
    r = taxa_mensal(taxa_anual)
    P0, M = float(saldo_inicial), float(meta)
    if abs(r) < 1e-12:
        A = (M - P0) / n
    else:
        fator = (1.0 + r) ** n
        A = (M - P0 * fator) * r / (fator - 1.0)
    return max(0.0, A)


def meses_entre(ano_ini: int, mes_ini: int, ano_fim: int, mes_fim: int) -> int:
    """Distancia em meses entre dois (ano, mes). Negativo se a data ja passou."""
    return (int(ano_fim) - int(ano_ini)) * 12 + (int(mes_fim) - int(mes_ini))


def somar_meses(ano: int, mes: int, n: int):
    """(ano, mes) + n meses -> (ano, mes). Util pra rotular o fim da projecao."""
    total = (int(ano) * 12 + (int(mes) - 1)) + int(n)
    return total // 12, total % 12 + 1


def ultimo_mes_fechado(hoje=None):
    """
    (ano, mes) do ultimo mes CALENDARIO ja encerrado. Hoje e' 18/08/2026 ->
    (2026, 7).

    Por que isso existe: as medias de ritmo dividem pela janela CHEIA (ver
    `ritmo_aporte`). Se o mes corrente entra na janela, ele contribui com os
    poucos lancamentos ja feitos mas ocupa uma vaga inteira no divisor — a
    media sai subestimada, e o vies ENCOLHE ao longo do mes conforme voce
    lanca. O numero muda sozinho sem nada ter mudado na sua vida financeira.

    O erro fica grave quando o mes corrente e' um dos grandes: abrir a
    projecao em meados de julho (mes de aporte anual) contaria julho pela
    metade e derrubaria a media em milhares.

    `hoje` e' injetavel para teste.
    """
    d = hoje or date.today()
    ano, mes = int(d.year), int(d.month) - 1
    if mes == 0:
        ano, mes = ano - 1, 12
    return ano, mes


def formatar_prazo(meses) -> str:
    """N meses -> 'Xa Ym' legivel. None -> 'nao chega no ritmo atual'."""
    if meses is None:
        return "nao chega no ritmo atual"
    if meses == 0:
        return "ja atingida"
    a, m = divmod(int(meses), 12)
    if a and m:
        return f"{a}a {m}m"
    return f"{a} anos" if a else f"{m} meses"


def variacao_pct(atual: float, anterior: float):
    """
    Variacao percentual com guarda de denominador. Devolve None quando a base e
    ~zero — em vez de imprimir um '+9900%' que nao significa nada.
    """
    if anterior is None or abs(float(anterior)) < 1e-9:
        return None
    return (float(atual) - float(anterior)) / abs(float(anterior)) * 100.0


# ──────────────────────────────────────────────────────────────────────────
# 2) BLOCO DADOS — leitura do banco (patrimonio, ritmo de aporte, parametros)
# Import do core fica AQUI de proposito: o bloco 1 acima roda sem banco.
# ──────────────────────────────────────────────────────────────────────────
from core.db import query_df, execute, _hh   # noqa: E402


def get_parametros(household_id=None) -> dict:
    """
    Todos os parametros do household num dict {chave: valor}. Numerico volta
    float; quando `valor` e NULL usa `valor_texto` (ex.: meta_data='2032-12').
    Sem parametro cadastrado -> dict vazio (a pagina aplica os defaults dela).
    """
    hh = _hh(household_id)
    df = query_df(
        "SELECT chave, valor, valor_texto FROM parametros WHERE household_id=%s",
        [hh],
    )
    out = {}
    for r in df.itertuples():
        # pd.read_sql traz a coluna numerica como float64, entao NULL vira NaN
        # (que E um float, nao None) — testar `is not None` deixaria passar e
        # float(nan) nao levanta erro. pd.notna cobre None e NaN de uma vez.
        out[r.chave] = float(r.valor) if pd.notna(r.valor) else r.valor_texto
    return out


def set_parametro(chave, valor=None, valor_texto=None, household_id=None):
    """Upsert de um parametro. Guarda numero em `valor` e texto em `valor_texto`."""
    hh = _hh(household_id)
    execute(
        "INSERT INTO parametros (household_id, chave, valor, valor_texto) "
        "VALUES (%s,%s,%s,%s) "
        "ON CONFLICT (household_id, chave) DO UPDATE SET "
        "  valor = EXCLUDED.valor, valor_texto = EXCLUDED.valor_texto, "
        "  atualizado_em = now()",
        [hh, chave, valor, valor_texto],
    )


def get_patrimonio_detalhado(household_id=None):
    """
    Serie mensal do patrimonio separando INVESTIVEL de NAO-INVESTIVEL.

    Colunas: ano, nro_mes, mes, periodo, investivel, nao_investivel, total, cats.
      - investivel     -> soma das categorias com investivel = TRUE (base da projecao)
      - nao_investivel -> imovel de uso etc. (entra no total, fica fora da projecao)
      - cats           -> quantas categorias tem registro no mes (informativo).
                          Para saber o que FALTA preencher use
                          get_categorias_faltantes(), que olha so as ativas.
    Todos os valores ja multiplicados pelo fator_liquido da categoria (SRS 0.71,
    cambio do apartamento etc.).
    """
    hh = _hh(household_id)
    df = query_df(
        "SELECT r.ano, r.nro_mes, m.nome AS mes, "
        "  COALESCE(SUM(r.valor_bruto*c.fator_liquido) FILTER (WHERE c.investivel), 0) AS investivel, "
        "  COALESCE(SUM(r.valor_bruto*c.fator_liquido) FILTER (WHERE NOT c.investivel), 0) AS nao_investivel, "
        "  COALESCE(SUM(r.valor_bruto*c.fator_liquido), 0) AS total, "
        "  COUNT(*) AS cats "
        "FROM patrimonio_registros r "
        "JOIN patrimonio_categorias c ON c.id = r.categoria_id "
        "JOIN meses m ON m.nro = r.nro_mes "
        "WHERE r.household_id = %s "
        "GROUP BY r.ano, r.nro_mes, m.nome "
        "ORDER BY r.ano, r.nro_mes",
        [hh],
    )
    if not df.empty:
        for c in ("investivel", "nao_investivel", "total"):
            df[c] = df[c].astype(float)
        df["periodo"] = pd.to_datetime(dict(year=df["ano"], month=df["nro_mes"], day=1))
    return df


def get_categorias_faltantes(ano, mes, household_id=None):
    """
    Categorias ATIVAS que ainda nao tem valor lancado no mes — ou seja, o que
    de fato falta preencher.

    Por que nao contar quantas categorias o mes tem: uma categoria encerrada
    (ativa=FALSE) para de aparecer para sempre, entao qualquer criterio por
    CONTAGEM acusa todo mes posterior ao encerramento como "incompleto" — um
    falso-positivo que nunca se resolve porque nao ha nada a preencher. Olhar so
    para as categorias ativas responde a pergunta certa: falta algo AGORA?

    Devolve lista de nomes (vazia = mes completo).
    """
    hh = _hh(household_id)
    df = query_df(
        "SELECT c.nome FROM patrimonio_categorias c "
        "WHERE c.household_id = %s AND c.ativa = TRUE "
        "  AND NOT EXISTS ( "
        "    SELECT 1 FROM patrimonio_registros r "
        "    WHERE r.categoria_id = c.id AND r.household_id = c.household_id "
        "      AND r.ano = %s AND r.nro_mes = %s) "
        "ORDER BY c.ordem, c.nome",
        [hh, int(ano), int(mes)],
    )
    return df["nome"].tolist() if not df.empty else []


def get_aportes_mensais(household_id=None):
    """
    Serie mensal de APORTE FINANCEIRO (tudo que foi para investimento: Manulife,
    IBKR, DigiPortfolio, SRS — nao so o aporte fixo). Colunas: ano, nro_mes,
    aporte, periodo. Valores negativos sao resgates/vendas e entram com o sinal
    deles, entao a soma da o fluxo LIQUIDO — que e o que interessa pro ritmo.

    NAO inclui o pagamento do apartamento: ele nunca passou por `lancamentos`.
    Quem soma o imovel ao esforco de poupanca e' get_esforco_por_ano(), que
    deriva o desembolso do delta da serie de patrimonio da categoria
    nao-investivel. Sao dois caminhos deliberadamente separados — lancar o
    apartamento aqui tambem duplicaria o valor naquele grafico.
    """
    hh = _hh(household_id)
    df = query_df(
        "SELECT ano, nro_mes, SUM(valor) AS aporte "
        "FROM lancamentos "
        "WHERE household_id = %s AND tipo_geral = 'Investimento' "
        "GROUP BY ano, nro_mes ORDER BY ano, nro_mes",
        [hh],
    )
    if not df.empty:
        df["aporte"] = df["aporte"].astype(float)
        df["periodo"] = pd.to_datetime(dict(year=df["ano"], month=df["nro_mes"], day=1))
    return df


def ritmo_aporte(df_aportes, ano_ref: int, mes_ref: int, meses: int = 12,
                 coluna: str = "aporte") -> float:
    """
    Media mensal na janela dos ultimos `meses` ate (ano_ref, mes_ref).
    Divide pela janela CHEIA, nao pelo numero de meses com lancamento: um mes
    sem aporte e' um mes de ritmo zero, nao um mes inexistente. Ignorar isso
    inflaria o ritmo de quem aporta esporadicamente.

    Passe SEMPRE um (ano_ref, mes_ref) de mes fechado — ver
    `ultimo_mes_fechado()`. Um mes em aberto ocupa uma vaga cheia no divisor
    com uma fracao dos lancamentos.

    A janela deve ser MULTIPLA DE 12 quando ha sazonalidade anual (aporte de
    bonus, 13o). Uma janela de 18 meses pega dois julhos e divide por 18: da
    ao mes sazonal peso 2/18 em vez de 1/12, superponderando o pico em 33% —
    e o vies troca de sinal conforme o mes em que a pagina e' aberta. E o
    mesmo motivo pelo qual varejo compara "12 meses contra 12 meses".

    `coluna` permite reusar a mesma janela para dividendos (coluna 'dividendo').
    """
    if df_aportes is None or df_aportes.empty or coluna not in df_aportes.columns:
        return 0.0
    ym_fim = int(ano_ref) * 12 + (int(mes_ref) - 1)
    ym_ini = ym_fim - int(meses) + 1
    ym = df_aportes["ano"].astype(int) * 12 + (df_aportes["nro_mes"].astype(int) - 1)
    sel = df_aportes[(ym >= ym_ini) & (ym <= ym_fim)]
    return float(sel[coluna].sum()) / float(meses) if meses else 0.0


def ultimo_valor(df, coluna: str = "dividendo", ano_ref=None, mes_ref=None):
    """
    Valor do mes mais recente COM DADO, ate (ano_ref, mes_ref) inclusive.
    Devolve (valor, ano, mes); (0.0, None, None) se nao houver nada.

    Usado para o dividendo. Media de 12 meses e' errada aqui porque a carteira
    MUDA de patamar: quando um fundo novo comeca a pagar, o dividendo salta e
    fica no patamar novo — a media arrasta meses do patamar antigo e subestima
    o fluxo que existe hoje. Para aporte a media faz sentido (suaviza
    irregularidade); para dividendo o que importa e' o nivel corrente.

    Combine com `ultimo_mes_fechado()` no `ano_ref`: um mes em aberto pode ter
    so parte dos fundos creditada e apareceria como queda.
    """
    if df is None or df.empty or coluna not in df.columns:
        return 0.0, None, None
    d = df
    if ano_ref is not None and mes_ref is not None:
        ym_lim = int(ano_ref) * 12 + (int(mes_ref) - 1)
        ym = d["ano"].astype(int) * 12 + (d["nro_mes"].astype(int) - 1)
        d = d[ym <= ym_lim]
    if d.empty:
        return 0.0, None, None
    d = d.sort_values(["ano", "nro_mes"])
    linha = d.iloc[-1]
    return float(linha[coluna]), int(linha["ano"]), int(linha["nro_mes"])


def get_dividendos_mensais(household_id=None):
    """
    Serie mensal de DIVIDENDOS recebidos. Colunas: ano, nro_mes, dividendo, periodo.

    Dividendo aqui e' caixa que SAIU da carteira: os lancamentos tem
    reinvestido=FALSE, entao o dinheiro nao voltou para o patrimonio. Por isso
    ele nao aparece nem no patrimonio nem no rendimento (que foi derivado do
    patrimonio pelo metodo TAV).

    Consequencia para a projecao: a taxa de retorno do slider representa apenas
    VALORIZACAO de capital. Se o usuario decidir reinvestir os dividendos, eles
    entram como aporte adicional — e' essa a conta que a pagina oferece.
    """
    hh = _hh(household_id)
    df = query_df(
        "SELECT ano, nro_mes, SUM(dividendo) AS dividendo "
        "FROM investimentos_serie "
        "WHERE household_id = %s AND dividendo IS NOT NULL AND dividendo <> 0 "
        "GROUP BY ano, nro_mes ORDER BY ano, nro_mes",
        [hh],
    )
    if not df.empty:
        df["dividendo"] = df["dividendo"].astype(float)
        df["periodo"] = pd.to_datetime(dict(year=df["ano"], month=df["nro_mes"], day=1))
    return df


def yield_dividendos(div_mensal: float, patrimonio: float) -> float:
    """
    Dividend yield anualizado implicito, em fracao (0.015 = 1,5%).

    Serve para calibrar o slider de retorno: o retorno TOTAL de mercado inclui
    dividendos, mas a projecao aplica a taxa so sobre o saldo. Quem saca os
    dividendos deve informar a taxa de valorizacao, isto e, o retorno total
    MENOS este yield — caso contrario conta o dividendo duas vezes.
    """
    if not patrimonio:
        return 0.0
    return (float(div_mensal) * 12.0) / float(patrimonio)


def get_esforco_por_ano(household_id=None):
    """
    Quanto foi guardado por ano, somando o APORTE FINANCEIRO com o pagamento de
    ativos NAO-INVESTIVEIS (o apartamento). O pagamento do imovel sai do delta
    da propria serie de patrimonio da categoria — como o valor registrado e o
    acumulado pago, a diferenca entre dois meses E o desembolso do mes.

    Isso responde "qual o meu potencial real de poupanca": em anos em que o
    imovel comeu a maior parte, o aporte financeiro sozinho subestima muito.

    ESTA e' a unica fonte do apartamento no app. Nao criar lancamentos
    retroativos do imovel em `lancamentos`: eles entrariam em `financeiro` sem
    sair de `imovel`, e o total dobraria.

    Colunas: ano, financeiro, imovel, total.
    """
    hh = _hh(household_id)
    fin = query_df(
        "SELECT ano, SUM(valor) AS financeiro FROM lancamentos "
        "WHERE household_id=%s AND tipo_geral='Investimento' "
        "GROUP BY ano ORDER BY ano",
        [hh],
    )
    ni = query_df(
        "SELECT r.ano, r.nro_mes, SUM(r.valor_bruto*c.fator_liquido) AS v "
        "FROM patrimonio_registros r "
        "JOIN patrimonio_categorias c ON c.id=r.categoria_id "
        "WHERE r.household_id=%s AND c.investivel = FALSE "
        "GROUP BY r.ano, r.nro_mes ORDER BY r.ano, r.nro_mes",
        [hh],
    )
    if ni.empty:
        ni_ano = pd.DataFrame(columns=["ano", "imovel"])
    else:
        ni["v"] = ni["v"].astype(float)
        # 1o mes da serie = desembolso inicial (entrada); depois, delta mes a mes.
        ni["imovel"] = ni["v"].diff().fillna(ni["v"])
        ni_ano = ni.groupby("ano", as_index=False).agg(imovel=("imovel", "sum"))

    if fin.empty and ni_ano.empty:
        return pd.DataFrame(columns=["ano", "financeiro", "imovel", "total"])
    if not fin.empty:
        fin["financeiro"] = fin["financeiro"].astype(float)
    df = pd.merge(fin, ni_ano, on="ano", how="outer").fillna(0.0)
    df["ano"] = df["ano"].astype(int)
    df["total"] = df["financeiro"] + df["imovel"]
    return df.sort_values("ano").reset_index(drop=True)


def comparar_periodos(df_aportes, ano_ref: int, mes_ref: int):
    """
    Comparacao honesta de "investi mais ou menos que antes", em duas leituras:

      - YTD    : jan..mes_ref do ano corrente vs jan..mes_ref do ano anterior.
                 Compara periodos do MESMO tamanho (ano parcial nao vira queda
                 artificial so porque ainda nao acabou).
      - Rolling: ultimos 12 meses vs os 12 meses anteriores a esses. E a leitura
                 de RITMO, insensivel a onde o calendario cortou.

    Devolve dict com valores e variacao percentual de cada leitura.
    """
    if df_aportes is None or df_aportes.empty:
        return {}
    a, m = int(ano_ref), int(mes_ref)
    ym = df_aportes["ano"].astype(int) * 12 + (df_aportes["nro_mes"].astype(int) - 1)
    v = df_aportes["aporte"].astype(float)

    def soma(ini, fim):
        return float(v[(ym >= ini) & (ym <= fim)].sum())

    ytd_ini, ytd_fim = a * 12, a * 12 + (m - 1)
    ytd = soma(ytd_ini, ytd_fim)
    ytd_ant = soma((a - 1) * 12, (a - 1) * 12 + (m - 1))

    fim = a * 12 + (m - 1)
    r12 = soma(fim - 11, fim)
    r12_ant = soma(fim - 23, fim - 12)

    return {
        "ytd": ytd, "ytd_anterior": ytd_ant, "ytd_var": variacao_pct(ytd, ytd_ant),
        "ytd_ano": a, "ytd_ano_anterior": a - 1, "ytd_meses": m,
        "rolling12": r12, "rolling12_anterior": r12_ant,
        "rolling12_var": variacao_pct(r12, r12_ant),
    }
