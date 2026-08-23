# -*- coding: utf-8 -*-
"""
Pagina Projecoes - V1 (minimo auditavel).

Terceira e ultima camada da arquitetura (decisao D-07):

    core/proj_motor.py    -> matematica pura
    core/proj_dados.py    -> so leitura do banco
    pages/08_Projecoes.py -> so UI (este arquivo)

Esta pagina NAO calcula e NAO consulta o banco diretamente. Ela junta as
duas camadas e exibe. Regra de ouro herdada do fracasso da pagina antiga:
CADA NUMERO NA TELA CARREGA SUA PROCEDENCIA - janela usada, formula,
parcelas, mes de referencia. Numero sem origem visivel foi o que tornou a
versao anterior irrecuperavel por edicao incremental.

V1 (D-02): cenario unico, saldo atual + capacidade mensal -> data
projetada da meta. Sem dividendos, sem cenarios multiplos, sem grafico de
trajetoria (o motor ja tem projetar() para isso, mas entra depois).

Read-only (D-08): a pagina nao escreve nada no banco.
"""

import sys
from datetime import date
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).parent.parent))

from core.proj_dados import montar_entradas_projecao, JANELA_MESES_PADRAO
from core.proj_motor import (
    taxa_mensal,
    resolver_meta_com_srs,
    formatar_prazo,
    REGIME_PRE,
    REGIME_POS,
    REGIME_FRONTEIRA,
    REGIME_INATINGIVEL,
)

st.set_page_config(page_title="Projecoes", page_icon="📈", layout="centered")


def _hoje_singapura() -> date:
    """
    Data de HOJE no fuso de Singapura.

    Nao usar date.today(): o Streamlit Cloud roda em UTC, e nas primeiras
    8 horas do dia 1 de cada mes o UTC ainda esta no mes anterior - a
    janela de 24 meses escorregaria um mes inteiro, silenciosamente, uma
    vez por mes. Com fallback para date.today() caso o tzdata nao esteja
    disponivel no ambiente.
    """
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime

        return datetime.now(ZoneInfo("Asia/Singapore")).date()
    except Exception:
        return date.today()


def _sgd(valor: float) -> str:
    """Formata em SGD com separador de milhar e 2 casas."""
    return f"S$ {valor:,.2f}"


def _sgd0(valor: float) -> str:
    """Formata em SGD sem casas decimais (para valores grandes)."""
    return f"S$ {valor:,.0f}"


def _mes_texto(d: date) -> str:
    meses = ["jan", "fev", "mar", "abr", "mai", "jun",
             "jul", "ago", "set", "out", "nov", "dez"]
    return f"{meses[d.month - 1]}/{d.year}"


# ---------------------------------------------------------------------------
# Carga dos dados
# ---------------------------------------------------------------------------

st.title("Projeções")

hoje = _hoje_singapura()

try:
    entradas = montar_entradas_projecao(hoje, n_meses=JANELA_MESES_PADRAO)
except Exception as erro:
    st.error(
        "Não foi possível carregar os dados da projeção. "
        "Nenhum cálculo foi executado."
    )
    st.exception(erro)
    st.stop()

base = entradas["base"]
cap = entradas["capacidade"]
srs = entradas["srs"]
params = entradas["parametros"]

retorno_anual = params.get("retorno_padrao")
if retorno_anual is None:
    retorno_anual = 0.03
    st.warning(
        "Parâmetro `retorno_padrao` não encontrado no banco. "
        "Usando 3% ao ano como padrão."
    )
retorno_anual = float(retorno_anual)

meta_banco = params.get("meta_patrimonio") or 2_000_000.0

patrimonio_hoje = base["saldo_outros"] + base["srs_bruto"] * base["fator_pre"]
patrimonio_projecao = base["saldo_outros"] + base["srs_bruto"] * base["fator_pos"]

if base["mes_ref"] is None:
    st.error("Não há registros de patrimônio para este household. Nada a projetar.")
    st.stop()


# ---------------------------------------------------------------------------
# Bloco 1 - situacao atual
# ---------------------------------------------------------------------------

col1, col2 = st.columns(2)
col1.metric(
    "Patrimônio investível hoje",
    _sgd0(patrimonio_hoje),
    help=(
        f"Referência: {base['mes_ref_texto']}. Soma das categorias marcadas como "
        f"investíveis ({base['n_categorias']} categorias), com o SRS avaliado pelo "
        f"fator de HOJE ({base['fator_pre']:.2f} — saque antecipado). "
        "O apartamento fica de fora: é estoque em BRL, estático, que só vira "
        "dinheiro na venda (decisão D-03). Este é o mesmo número da página de "
        "Patrimônio."
    ),
)
col2.metric(
    "Capacidade de investimento",
    _sgd0(cap["capacidade"]) + " /mês",
    help=(
        f"Média de {cap['n_meses']} meses fechados ({cap['janela_texto']}) dos "
        f"aportes não-SRS, mais o teto anual do SRS dividido por 12."
    ),
)

st.caption(
    f"Patrimônio de {base['mes_ref_texto']} · capacidade medida em {cap['janela_texto']} "
    f"· retorno assumido de {retorno_anual:.1%} ao ano · hoje = {hoje.strftime('%d/%m/%Y')} (SGT)"
)

with st.expander("Como a capacidade mensal é calculada"):
    st.markdown(
        f"""
| Parcela | Valor | Origem |
|---|---:|---|
| Aportes (exceto SRS) | {_sgd(cap['media_aportes'])} | média de {cap['n_lancamentos']} lançamentos em {cap['n_meses']} meses ({cap['janela_texto']}) |
| SRS | {_sgd(cap['srs_mensal'])} | teto anual {_sgd0(cap['srs_teto_anual'])} ÷ 12 |
| **Capacidade** | **{_sgd(cap['capacidade'])}** | soma das duas linhas |
"""
    )
    st.markdown(
        f"""
O SRS **sai da média e entra pelo teto** porque é constante conhecida — o teto é
contribuído todo ano. Isso torna a fórmula imune a como o lançamento foi
registrado no banco, e há registros inconsistentes (contribuição ora distribuída
em 12 parcelas, ora lançada em bloco num mês só).

A janela é sempre múltiplo de 12 meses, para conter exatamente uma ocorrência do
bônus de julho por ano — que é capacidade real e recorrente, não outlier a
descartar.

Meses com movimento na janela: {cap['n_meses_com_lancamento']} de {cap['n_meses']}.
"""
    )
    if cap["n_meses_com_lancamento"] < cap["n_meses"]:
        st.warning(
            f"{cap['n_meses'] - cap['n_meses_com_lancamento']} mês(es) da janela não têm "
            "nenhum lançamento de investimento. A média está sendo diluída por meses "
            "vazios — pode ser lacuna de registro, não ausência real de aporte."
        )

st.divider()


# ---------------------------------------------------------------------------
# Bloco 2 - meta e resultado
# ---------------------------------------------------------------------------

st.subheader("Meta")

meta = st.slider(
    "Patrimônio-alvo",
    min_value=1_000_000,
    max_value=3_000_000,
    value=int(min(max(meta_banco, 1_000_000), 3_000_000)),
    step=50_000,
    format="S$ %d",
    help=(
        f"O valor gravado no banco (`meta_patrimonio`) é {_sgd0(meta_banco)}. "
        "Mover o slider não altera o banco — a V1 é somente leitura. "
        "Passo de 50 mil: com passo de 100 mil, a faixa em que a meta cai sobre a "
        "virada de elegibilidade do SRS (hoje ~1,62M a ~1,67M) ficaria inalcançável."
    ),
)

taxa_m = taxa_mensal(retorno_anual)
resultado = resolver_meta_com_srs(
    saldo_outros=base["saldo_outros"],
    srs_bruto=base["srs_bruto"],
    fator_pre=base["fator_pre"],
    fator_pos=base["fator_pos"],
    meses_ate_elegibilidade=srs["meses"],
    aporte_mensal=cap["capacidade"],
    taxa_mensal_=taxa_m,
    meta=float(meta),
    data_base=hoje,
)

regime = resultado["regime"]
data_meta = resultado["data"]
meses = resultado["meses"]

if regime == REGIME_INATINGIVEL:
    st.error(
        "**Meta inatingível com os parâmetros atuais.** Com a capacidade mensal e o "
        "retorno assumido, o patrimônio não alcança esse valor. Verifique se a "
        "capacidade mensal está correta antes de concluir qualquer coisa."
    )

elif data_meta is None:
    st.warning(
        f"**Prazo superior a 100 anos** ({meses:,.0f} meses). A data não é exibida "
        "porque não seria informação útil. Um prazo desse tamanho quase sempre "
        "significa que a capacidade mensal foi calculada errado — confira a janela e "
        "os lançamentos antes de interpretar."
    )

else:
    col_a, col_b = st.columns(2)
    col_a.metric("Meta atingida em", _mes_texto(data_meta))
    col_b.metric("Prazo", formatar_prazo(meses))

    if regime == REGIME_PRE:
        st.info(
            f"**A meta é atingida antes de {_mes_texto(srs['data_elegibilidade'])}**, "
            f"quando o SRS completa 10 anos. O SRS foi avaliado a "
            f"**{base['fator_pre']:.2f}** — saque antecipado custa 5% de multa e "
            "100% do valor é tributável.\n\n"
            "Se esperar até a elegibilidade, o mesmo saldo bruto vale mais."
        )
    elif regime == REGIME_POS:
        st.success(
            f"**A meta é atingida depois de "
            f"{_mes_texto(srs['data_elegibilidade'])}**, quando o SRS completa 10 anos. "
            f"O SRS foi avaliado a **{base['fator_pos']:.2f}** — sem multa de 5%, e "
            "apenas 50% do valor é tributável.\n\n"
            "Isso exige saque **único e total**, e exige ter permanecido não-cidadão "
            "e não-PR durante os 10 anos."
        )
    elif regime == REGIME_FRONTEIRA:
        st.warning(
            f"**Esta meta cai exatamente sobre a virada de elegibilidade do SRS.**\n\n"
            f"Medindo o SRS a {base['fator_pre']:.2f}, a meta cairia em "
            f"{_mes_texto(resultado['data_pre'])} — já depois da elegibilidade, logo o "
            f"fator deveria ser {base['fator_pos']:.2f}. Mas medindo a "
            f"{base['fator_pos']:.2f}, ela cairia em "
            f"{_mes_texto(resultado['data_pos'])} — antes da elegibilidade, logo o "
            f"fator deveria ser {base['fator_pre']:.2f}. Os dois cenários se "
            "contradizem.\n\n"
            f"Não é erro de cálculo: o próprio destravamento do SRS "
            f"(+{_sgd0(patrimonio_projecao - patrimonio_hoje)}) é grande o bastante "
            "para cruzar a meta sozinho. A data exibida é o mês seguinte à "
            "elegibilidade, assumindo o comportamento racional de esperar destravar "
            "o SRS em vez de sacar com multa a poucas semanas da virada."
        )

    if regime in (REGIME_POS, REGIME_FRONTEIRA):
        st.caption(
            f"Base da projeção: {_sgd0(patrimonio_projecao)} "
            f"(SRS a {base['fator_pos']:.2f}) — diferente dos "
            f"{_sgd0(patrimonio_hoje)} exibidos acima, que usam o fator de hoje. "
            "Patrimônio responde 'quanto tenho se parar agora'; a projeção responde "
            "'quanto isso vale quando eu sacar'."
        )

st.divider()


# ---------------------------------------------------------------------------
# Bloco 3 - procedencia
# ---------------------------------------------------------------------------

with st.expander("Procedência dos números e premissas"):
    st.markdown(
        f"""
**Patrimônio** — mês de referência {base['mes_ref_texto']},
{base['n_categorias']} categorias investíveis, das quais
{base['n_categorias_srs']} têm regra especial de projeção.
Apartamento excluído (D-03).

**Capacidade** — {_sgd(cap['media_aportes'])} de média
({cap['n_lancamentos']} lançamentos, {cap['janela_texto']})
mais {_sgd(cap['srs_mensal'])} de SRS pelo teto.
Total da janela: {_sgd(cap['total_janela'])}.

**SRS** — primeira contribuição em
{_mes_texto(srs['primeira_contribuicao']) if srs['primeira_contribuicao'] else '—'},
elegibilidade em
{_mes_texto(srs['data_elegibilidade']) if srs['data_elegibilidade'] else '—'}
(faltam {srs['meses']} meses). Fator hoje {base['fator_pre']:.2f},
fator pós-elegibilidade {base['fator_pos']:.2f}.

**Retorno** — {retorno_anual:.1%} ao ano, equivalente a
{taxa_m:.4%} ao mês, composto.

**Datas candidatas** — a {base['fator_pre']:.2f}:
{_mes_texto(resultado['data_pre']) if resultado['data_pre'] else '—'} ·
a {base['fator_pos']:.2f}:
{_mes_texto(resultado['data_pos']) if resultado['data_pos'] else '—'}.
"""
    )
    st.markdown("---")
    st.markdown(
        """
**Premissas e limites desta V1**

- Aporte constante, no fim de cada mês, sem reajuste por inflação ou promoção.
- Retorno constante e determinístico — não há cenários nem intervalo de confiança.
- Dividendos não entram como linha separada (estão embutidos no retorno assumido).
- O apartamento não aparece: foi quitado em maio/2026 e o imóvel é estoque em BRL.
- A data da primeira contribuição do SRS (e portanto a elegibilidade) vem de
  lançamentos **reconstruídos**, não de extrato bancário. Confirmar antes de
  tomar decisão de saque com base nisso.
- Os fatores do SRS (0,71 / 0,89) são estimativas de carga tributária, não
  cálculo fiscal. O valor real depende da renda no ano do saque e da residência
  fiscal naquele momento.
- Esta página é somente leitura: mover o slider não altera nada no banco.
"""
    )

st.caption("App dos 10 Milhões · Projeções V1")
