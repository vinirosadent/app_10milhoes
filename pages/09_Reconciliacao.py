"""
Pagina de RECONCILIACAO do App 10M — o painel de saude dos dados.

O app guarda o patrimonio de duas formas independentes:

  OBSERVADO  = o valor que voce le no extrato e digita em Patrimonio.
  DERIVADO   = aporte lancado + rendimento lancado.

Quando os dois batem, o produto esta reconciliado. Quando nao batem, ha dado
faltando ou sobrando — e a diferenca aponta qual.

Por que esta pagina existe: em ago/2026 uma auditoria manual descobriu que o
DigiPortfolio tinha 15.210 de rendimento fantasma (aporte sub-registrado fazia o
app atribuir todo o crescimento ao mercado) e que o Smartwealth, ja liquidado,
continuava somando 74.824 no total. Nenhum dos dois aparecia em lugar nenhum da
interface. Esta tela existe para que esse tipo de erro fique visivel no dia em
que acontece, e nao meses depois.

A pagina NAO corrige nada sozinha, de proposito: a correcao exige extrato. Ela
so diz onde olhar.
"""
import streamlit as st
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from core import charts
from core.auth import get_current_household_id
from core.reconciliacao import (
    get_reconciliacao, get_totais_paginas, get_produtos_orfaos,
    diagnostico, TOLERANCIA_SGD,
)
# A serie mensal de patrimonio vinha de core.projecoes.get_patrimonio_detalhado,
# que foi arquivada em _legado/projecoes/ no patch PROJ-RESET-01. Aqui ela era
# usada SO para montar a lista de meses do seletor, e core.patrimonio (codigo
# ativo) devolve as mesmas colunas ano/nro_mes da mesma tabela, no mesmo
# agrupamento — a lista de meses e' identica.
from core.patrimonio import get_patrimonio_serie

st.set_page_config(page_title="Reconciliação", page_icon="🧮", layout="wide")

ICONE = {"ok": "✅", "falta": "🔺", "sobra": "🔻"}
ROTULO = {"ok": "Fecha", "falta": "Falta lançar", "sobra": "Sobra lançado"}

st.title("🧮 Reconciliação")
st.caption("O patrimônio que você digita × o que os lançamentos reconstroem. "
           "Onde os dois divergem, há dado faltando ou sobrando.")


# ── Leitura cacheada ──────────────────────────────────────────────────────
# Mesmo motivo da pagina de Projecoes: core/db.py abre e fecha uma conexao por
# query e nao ha cache, entao cada rerun do Streamlit dispararia varias idas ao
# Transaction Pooler do Supabase. O household vai como argumento porque
# st.cache_data e' um cache GLOBAL do servidor — sem o tenant na assinatura,
# dois households colidiriam na mesma entrada.
@st.cache_data(ttl=300, show_spinner=False)
def _pat(hh):
    return get_patrimonio_serie(household_id=hh)


@st.cache_data(ttl=300, show_spinner=False)
def _recon(hh, ano, mes):
    return get_reconciliacao(ano, mes, household_id=hh)


@st.cache_data(ttl=300, show_spinner=False)
def _totais(hh, ano, mes):
    return get_totais_paginas(ano, mes, household_id=hh)


@st.cache_data(ttl=300, show_spinner=False)
def _orfaos(hh):
    return get_produtos_orfaos(household_id=hh)


hh = get_current_household_id()
df_pat = _pat(hh)

if df_pat.empty:
    st.info("Ainda não há patrimônio registrado. Preencha ao menos um mês em "
            "**Patrimônio** para haver o que reconciliar. 🚀")
    st.stop()

# Mes de referencia: o ultimo com registro de patrimonio, com opcao de voltar.
# Voltar e' util para achar EM QUE MES uma divergencia surgiu — foi assim que se
# descobriu que o snapshot do IBKR de mar/2026 era antecipatorio.
meses_disp = [(int(r.ano), int(r.nro_mes)) for r in df_pat.itertuples()][::-1]
rotulos = [f"{charts.MESES_ABREV[m-1]}/{a}" for a, m in meses_disp]
idx = st.selectbox("Mês de referência", range(len(meses_disp)),
                   format_func=lambda i: rotulos[i], index=0,
                   help="Volte no tempo para descobrir em que mês uma "
                        "divergência apareceu pela primeira vez.")
ano_ref, mes_ref = meses_disp[idx]

df = _recon(hh, ano_ref, mes_ref)
tot = _totais(hh, ano_ref, mes_ref)

# ── Resumo ────────────────────────────────────────────────────────────────
n_ok = int((df["estado"] == "ok").sum()) if not df.empty else 0
n_tot = len(df)
soma_dif = float(df["diferenca"].abs().sum()) if not df.empty else 0.0

k1, k2, k3 = st.columns(3)
with k1:
    charts.card_kpi("Produtos reconciliados", float(n_ok), eh_moeda=False,
                    ajuda=f"De {n_tot} produtos mapeados a uma categoria de "
                          f"patrimônio. Tolerância de "
                          f"{charts.fmt_moeda(TOLERANCIA_SGD)} por produto.")
with k2:
    charts.card_kpi("Divergência total", soma_dif,
                    ajuda="Soma dos desvios em valor absoluto. Zero = todos os "
                          "produtos batem com o extrato.")
with k3:
    charts.card_kpi("Patrimônio investível", tot["patrimonio"],
                    ajuda=f"Observado em {rotulos[idx]} — a fonte primária.")

if n_tot and n_ok == n_tot:
    st.success(f"Todos os {n_tot} produtos fecham com o extrato em "
               f"{rotulos[idx]}.", icon="✅")
elif n_tot:
    st.warning(f"{n_tot - n_ok} de {n_tot} produtos não fecham. "
               "Veja abaixo qual e por quanto.", icon="⚠️")

# ── Tabela por produto ────────────────────────────────────────────────────
st.markdown("### Por produto")
if df.empty:
    st.info("Nenhum produto mapeado a uma categoria de patrimônio neste mês. "
            "O mapeamento vive em `produto_categoria_map`.")
else:
    vis = df.copy()
    vis["Situação"] = vis["estado"].map(lambda e: f"{ICONE[e]} {ROTULO[e]}")
    for c in ("observado", "aporte", "rendimento", "derivado", "diferenca"):
        vis[c] = vis[c].map(charts.fmt_moeda)
    vis = vis[["produto", "categoria", "observado", "aporte", "rendimento",
               "derivado", "diferenca", "Situação"]]
    vis.columns = ["Produto", "Categoria", "Observado", "Aporte", "Rendimento",
                   "Derivado", "Diferença", "Situação"]
    st.dataframe(vis, use_container_width=True, hide_index=True)

    st.caption(
        "**Observado** é o que você digitou em Patrimônio (vem do extrato). "
        "**Derivado** é aporte + rendimento lançados. "
        "🔺 significa que falta lançar algo; 🔻 que há lançamento a mais — "
        "tipicamente uma transferência entre contas contada como aporte novo."
    )

    problemas = df[df["estado"] != "ok"]
    if not problemas.empty:
        st.markdown("#### O que investigar")
        for r in problemas.itertuples():
            st.markdown(
                f"- **{r.produto}** · {charts.fmt_moeda(abs(r.diferenca))} — "
                + diagnostico(r.estado, r.produto)
            )

# ── Por que as duas paginas mostram numeros diferentes ────────────────────
st.markdown("### Patrimônio × Investimentos")
st.caption("As duas páginas mostram totais diferentes de propósito. Aqui está o porquê.")

c1, c2 = st.columns(2)
with c1:
    with st.container(border=True):
        st.metric("Página Patrimônio", charts.fmt_moeda(tot["patrimonio"]))
        st.caption("Só o que existe **hoje**: categorias com registro no mês "
                   "escolhido, já com o fator líquido aplicado (SRS ×0,71).")
with c2:
    with st.container(border=True):
        st.metric("Página Investimentos", charts.fmt_moeda(tot["investimentos"]),
                  delta=charts.fmt_moeda(tot["diferenca"]))
        st.caption("Histórico **inteiro**: aporte + rendimento de todos os "
                   "produtos que já passaram pela carteira, inclusive os "
                   "liquidados, e sem o fator líquido.")

orfaos = _orfaos(hh)
if not orfaos.empty:
    orfaos = orfaos.copy()
    for c in ("aporte", "rendimento"):
        orfaos[c] = orfaos[c].astype(float)
    orfaos["derivado"] = orfaos["aporte"] + orfaos["rendimento"]
    st.markdown("#### Produtos fora da reconciliação")
    st.caption(
        "Têm movimento em lançamentos mas nenhuma categoria de patrimônio "
        "associada. Para produtos **liquidados** isso é o esperado — o histórico "
        "fica para o BI e eles saem da conta do presente. Para produtos "
        "**ativos**, é mapeamento faltando: enquanto não existir, eles não são "
        "auditados por esta página."
    )
    vis2 = orfaos.copy()
    vis2["Status"] = vis2["ativo"].map(lambda a: "🟢 Ativo" if a else "⚪ Liquidado")
    for c in ("aporte", "rendimento", "derivado"):
        vis2[c] = vis2[c].map(charts.fmt_moeda)
    vis2 = vis2[["produto", "Status", "aporte", "rendimento", "derivado"]]
    vis2.columns = ["Produto", "Status", "Aporte", "Rendimento", "Soma"]
    st.dataframe(vis2, use_container_width=True, hide_index=True)

    ativos_sem_mapa = orfaos[orfaos["ativo"] == True]  # noqa: E712
    if not ativos_sem_mapa.empty:
        nomes = ", ".join(ativos_sem_mapa["produto"].tolist())
        st.warning(
            f"**{nomes}** — produto ativo sem categoria de patrimônio associada. "
            "Enquanto o mapeamento não existir, erros neste produto passam "
            "despercebidos.", icon="⚠️")

# ── Como corrigir ─────────────────────────────────────────────────────────
with st.expander("Como corrigir uma divergência"):
    st.markdown(
        """
**A regra que vale sempre: documento manda.** Extrato, carta de resgate ou tela
do app da corretora ganham de qualquer número digitado de memória e de qualquer
conta derivada.

**🔺 Falta lançar** — o patrimônio observado é maior que aporte + rendimento.
Ou entrou dinheiro que não foi lançado, ou o produto rendeu mais do que está
registrado. Confira no extrato o total aportado; a diferença contra o
patrimônio é o rendimento.

**🔻 Sobra lançado** — aporte + rendimento passam do patrimônio. As duas causas
mais comuns:
1. **Transferência contada como aporte.** Fechou uma conta e mandou para outra: a
   chegada foi lançada como aporte novo e a saída não foi lançada em lugar
   nenhum. O aporte é a diferença agregada, não o valor bruto do depósito — se
   uma posição de 10 virou 12, o aporte novo é 2.
2. **Produto liquidado ainda mapeado.** Desmapeie de `produto_categoria_map` e
   marque `ativo = false`. Não apague os lançamentos: o histórico serve ao BI.

**Nunca calibre um lançamento até a conta fechar.** Escolher um valor para fazer
o resíduo dar zero e depois usar o resíduo zero como prova é circular — não
prova nada. Se não fecha com documento, o dado está faltando.
        """
    )
