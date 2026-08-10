"""
Pagina de PROJECOES do App 10M — o modulo "para onde estou indo".

Responde as tres perguntas de planejamento que o resto do app nao respondia:

  1. Quando eu chego na meta, no ritmo atual?
  2. Quanto eu tenho na data-alvo?
  3. Quanto eu preciso aportar por mes pra chegar la?

Sao a MESMA equacao resolvida em variaveis diferentes (a formula esta em
core/projecoes.py, testada isolada). Aqui so tem UI: ler parametros, montar os
controles, desenhar.

Decisoes de leitura que valem lembrar:

  - A projecao parte do patrimonio INVESTIVEL, nao do total. O apartamento e
    patrimonio, mas nao da pra viver de 4% dele sem vender — projeta-lo junto
    inflaria a meta com dinheiro que nao esta disponivel.
  - Sempre DUAS linhas: o piso (retorno 0%, so o que voce aporta) e o cenario
    escolhido no slider. O piso nao tem como ser otimista demais; se a meta cai
    dentro dele, ela nao depende do mercado.
  - O ritmo de aporte soma TUDO (Manulife, IBKR, DigiPortfolio, SRS), inclusive
    resgates com sinal negativo — e o fluxo liquido que importa.
  - O fim do pagamento do apartamento (ago/2026) liberou caixa mensal. Isso so
    vira aporte se for REDIRECIONADO, entao e um controle explicito na tela, nao
    uma premissa escondida.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from core import charts
from core.auth import get_current_household_id
from core.projecoes import (
    get_parametros, set_parametro, get_patrimonio_detalhado,
    get_categorias_faltantes, get_aportes_mensais, ritmo_aporte,
    get_dividendos_mensais, yield_dividendos,
    get_esforco_por_ano, comparar_periodos,
    projetar, valor_em, meses_ate_meta, aporte_necessario,
    meses_entre, somar_meses, formatar_prazo,
)

st.set_page_config(page_title="Projeções", page_icon="🔭", layout="wide")

PLOTLY_CFG = {"displayModeBar": False, "displaylogo": False}

C_HIST  = "#1D4FD7"   # historico realizado
C_PISO  = "#94A3B8"   # projecao com retorno 0% (piso)
C_CEN   = "#059669"   # projecao com o retorno escolhido
C_META  = "#DC2626"   # linha da meta

st.title("🔭 Projeções")
st.caption("Para onde o patrimônio vai no ritmo atual — e o que muda se o ritmo mudar.")

# ── Leitura cacheada ──────────────────────────────────────────────────────
# core/db.py abre e FECHA uma conexao por query, e nao ha cache em lugar nenhum.
# Como Streamlit re-executa a pagina inteira a cada movimento de slider ou
# toggle, arrastar um controle dispararia dezenas de conexoes no Transaction
# Pooler do Supabase — que ja derrubou a conexao em teste
# (server closed the connection unexpectedly).
# Os wrappers abaixo guardam o resultado por 5 minutos: sao leituras que NAO
# mudam enquanto o usuario mexe nos controles, entao o custo cai de 6 idas ao
# banco por interacao para 1 por sessao.
#
# CADA WRAPPER RECEBE `hh` (household) COMO PRIMEIRO ARGUMENTO — e obrigatorio,
# nao e enfeite. st.cache_data e um cache GLOBAL do servidor, compartilhado
# entre todas as sessoes; a chave e (funcao + argumentos). Se o household fosse
# resolvido dentro da funcao (via session_state), dois households colidiriam na
# MESMA entrada e o segundo a renderizar veria os dados do primeiro. Passar o
# household como argumento separa as entradas e, de quebra, torna a query
# explicita. Nunca cachear leitura multi-tenant sem o tenant na assinatura.
#
# O cache mora AQUI, e nao em core/projecoes.py, para aquele modulo continuar
# importavel e testavel sem o runtime do Streamlit.
@st.cache_data(ttl=300, show_spinner=False)
def _par(hh):
    return get_parametros(household_id=hh)


@st.cache_data(ttl=300, show_spinner=False)
def _pat(hh):
    return get_patrimonio_detalhado(household_id=hh)


@st.cache_data(ttl=300, show_spinner=False)
def _aportes(hh):
    return get_aportes_mensais(household_id=hh)


@st.cache_data(ttl=300, show_spinner=False)
def _faltantes(hh, ano, mes):
    return get_categorias_faltantes(ano, mes, household_id=hh)


@st.cache_data(ttl=300, show_spinner=False)
def _dividendos(hh):
    return get_dividendos_mensais(household_id=hh)


@st.cache_data(ttl=300, show_spinner=False)
def _esforco(hh):
    return get_esforco_por_ano(household_id=hh)


# ── Dados base ────────────────────────────────────────────────────────────
hh       = get_current_household_id()
par      = _par(hh)
df_pat   = _pat(hh)
df_ap    = _aportes(hh)
df_div   = _dividendos(hh)

if df_pat.empty:
    st.info("Ainda não há patrimônio registrado. Preencha ao menos um mês em "
            "**Patrimônio** para a projeção ter de onde partir. 🚀")
    st.stop()

ultimo       = df_pat.iloc[-1]
ano_ref      = int(ultimo["ano"])
mes_ref      = int(ultimo["nro_mes"])
investivel   = float(ultimo["investivel"])
nao_invest   = float(ultimo["nao_investivel"])
total_pat    = float(ultimo["total"])
rotulo_ref   = f"{ultimo['mes']}/{ano_ref}"

# ── Com ou sem o apartamento ──────────────────────────────────────────────
# Le a MESMA chave de session_state da pagina de Patrimonio (`incluir_imovel`),
# entao as duas telas nunca discordam: o usuario decide uma vez.
# COM imovel  -> projeta o patrimonio total. Responde "quanto eu vou ter",
#                tratando o apartamento como reserva de valor.
# SEM imovel  -> projeta so o investivel. Responde "com quanto eu posso contar",
#                que e a leitura correta para independencia financeira: nao da
#                pra viver de 4% ao ano de um imovel de uso sem vende-lo.
tem_imovel = nao_invest > 0
if tem_imovel:
    st.toggle(
        "Incluir apartamento na projeção",
        key="incluir_imovel",
        value=st.session_state.get("incluir_imovel", True),
        help="Ligado: projeta o patrimônio total. Desligado: projeta só o "
             "investível. A escolha vale também na página de Patrimônio.",
    )
incluir_imovel = tem_imovel and bool(st.session_state.get("incluir_imovel", True))

# BASE da projecao e de todas as contas de meta desta pagina.
base_proj  = total_pat if incluir_imovel else investivel
col_base   = "total" if incluir_imovel else "investivel"
rotulo_base = "Patrimônio total" if incluir_imovel else "Patrimônio investível"

# Aviso de mes em aberto: so categorias ATIVAS sem lancamento contam como
# pendencia (categoria encerrada nao e buraco). Se o ultimo mes estiver
# incompleto, o ponto de partida esta rebaixado e a projecao inteira sai baixa.
faltantes = _faltantes(hh, ano_ref, mes_ref)
if faltantes:
    st.warning(
        f"**{rotulo_ref} ainda não está fechado** — falta lançar: "
        + ", ".join(faltantes)
        + ". A projeção parte deste mês, então os números abaixo saem subestimados."
    )

# ── Controles ─────────────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("##### Quanto eu vou investir por mês")
    st.caption("O histórico serve de ponto de partida — o número final é sua decisão.")

    c1, c2 = st.columns([1, 2])
    with c1:
        janela = st.radio("Referência", [12, 24], horizontal=True,
                          key="proj_janela",
                          format_func=lambda x: f"{x} meses",
                          help="Janela do histórico usada como sugestão. Meses sem "
                               "aporte contam como zero.")
    ritmo_base = ritmo_aporte(df_ap, ano_ref, mes_ref, janela)

    # O number_input com `key` ignora o `value` a partir do 2o rerun (mesma
    # armadilha do st.radio). Sem reancorar, trocar 12<->24 meses nao mudaria o
    # campo e a "sugestao" viraria letra morta. Entao: quando a JANELA muda,
    # reescrevemos a chave com o ritmo novo. Edicao manual do usuario e
    # preservada ate ele trocar de janela outra vez.
    if st.session_state.get("_proj_janela_ant") != janela:
        st.session_state["_proj_janela_ant"] = janela
        st.session_state["proj_aporte"] = float(round(ritmo_base, 2))
    with c2:
        aporte_base = st.number_input(
            "Aporte mensal planejado (SGD)", min_value=0.0, step=250.0,
            key="proj_aporte",
            help=f"Sugestão pelo histórico de {janela} meses: "
                 f"{charts.fmt_moeda(ritmo_base)}/mês. Edite livremente — esta é "
                 "a variável que você de fato controla.")
    if abs(aporte_base - ritmo_base) > 1:
        _dif = aporte_base - ritmo_base
        st.caption(f"{charts.fmt_moeda(abs(_dif))}/mês "
                   f"{'acima' if _dif > 0 else 'abaixo'} do seu ritmo dos últimos "
                   f"{janela} meses ({charts.fmt_moeda(ritmo_base)}).")

# ── Fontes adicionais de aporte ───────────────────────────────────────────
div_mes = ritmo_aporte(df_div, ano_ref, mes_ref, 12, coluna="dividendo")
with st.container(border=True):
    st.markdown("##### Somar mais alguma coisa?")
    f1, f2 = st.columns(2)

    with f1:
        liberado_par = float(par.get("apto_liberado_mensal", 0.0))
        usar_lib = st.toggle(
            f"Valor liberado do apartamento ({charts.fmt_moeda(liberado_par)}/mês)",
            value=False,
            help="O pagamento do apartamento terminou em ago/2026. Esse dinheiro "
                 "só vira patrimônio se for redirecionado para investimento.")
        pct_lib = st.slider("Quanto dele vai para investimento", 0, 100, 100, 5,
                            format="%d%%", disabled=not usar_lib) / 100.0

    with f2:
        # Os dividendos hoje SAEM da carteira (reinvestido=FALSE), entao nao estao
        # no patrimonio nem no rendimento. Reinvesti-los e uma DECISAO, e o efeito
        # dela merece ficar visivel em vez de embutido numa premissa.
        usar_div = st.toggle(
            f"Reinvestir dividendos ({charts.fmt_moeda(div_mes)}/mês)",
            value=False, disabled=div_mes <= 0,
            help="Hoje os dividendos saem em dinheiro e não voltam para a "
                 "carteira. Ligue para simular o efeito de reinvesti-los.")
        pct_div = st.slider("Quanto dos dividendos é reinvestido", 0, 100, 100, 5,
                            format="%d%%", disabled=not usar_div) / 100.0

aporte_extra_apto = liberado_par * pct_lib if usar_lib else 0.0
aporte_extra_div  = div_mes * pct_div if usar_div else 0.0
aporte_extra      = aporte_extra_apto + aporte_extra_div
aporte_mes        = aporte_base + aporte_extra

# ── Retorno assumido ──────────────────────────────────────────────────────
_yield = yield_dividendos(div_mes, base_proj)
with st.container(border=True):
    st.markdown("##### Retorno assumido")
    retorno = st.slider(
        "Retorno anual", 0.0, 8.0,
        float(par.get("retorno_padrao", 0.03)) * 100.0, 0.5, format="%.1f%%",
        help="Aplicado sobre o saldo, então compõe. O gráfico mostra sempre "
             "também a linha de 0% como piso.") / 100.0
    st.caption(
        f"Informe a **valorização**, não o retorno total: a taxa incide só sobre o "
        f"saldo, e seus dividendos saem da carteira. Eles rendem hoje cerca de "
        f"**{_yield*100:.1f}% ao ano**, "
        + ("e estão sendo somados como aporte acima."
           if usar_div else
           "e não estão embutidos nesta taxa.")
        + f" Um retorno total de mercado de 6% equivale a "
          f"~{max(0.0, 6.0 - _yield*100):.1f}% aqui."
    )

if aporte_extra > 0:
    st.caption(
        f"Aporte usado na projeção: **{charts.fmt_moeda(aporte_mes)}/mês** "
        f"= {charts.fmt_moeda(aporte_base)} planejado"
        + (f" + {charts.fmt_moeda(aporte_extra_apto)} do apartamento" if aporte_extra_apto else "")
        + (f" + {charts.fmt_moeda(aporte_extra_div)} de dividendos" if aporte_extra_div else "")
        + "."
    )

# ── Meta (valor + data) ───────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("##### Meta")
    m1, m2, m3 = st.columns([1.2, 1, 1])
    with m1:
        meta = st.number_input("Patrimônio-alvo (SGD)", min_value=0, step=50_000,
                               value=int(par.get("meta_patrimonio", 2_000_000)))
    meta_data = str(par.get("meta_data") or "2032-12")
    try:
        ma, mm = int(meta_data.split("-")[0]), int(meta_data.split("-")[1])
    except (ValueError, IndexError):
        ma, mm = 2032, 12
    with m2:
        # max(ano_ref, ma): se a data-alvo salva ficar para tras (o tempo passa),
        # value < min_value levanta excecao no Streamlit e derruba a pagina.
        ano_alvo = st.number_input("Ano-alvo", min_value=ano_ref, max_value=2100,
                                   value=max(ano_ref, ma))
    with m3:
        mes_alvo = st.selectbox("Mês-alvo", list(range(1, 13)), index=mm - 1,
                                format_func=lambda x: charts.MESES_PT[x - 1])
    if st.button("💾 Salvar meta como padrão", use_container_width=False):
        set_parametro("meta_patrimonio", valor=float(meta))
        set_parametro("meta_data", valor_texto=f"{int(ano_alvo)}-{int(mes_alvo):02d}")
        set_parametro("retorno_padrao", valor=float(retorno))
        _par.clear()   # o cache de 5 min guardaria a meta antiga ate expirar
        st.success("Meta e retorno salvos como padrão.")

horizonte = max(0, meses_entre(ano_ref, mes_ref, int(ano_alvo), int(mes_alvo)))

# ── KPIs ──────────────────────────────────────────────────────────────────
st.markdown("### Onde estou")
k1, k2, k3, k4 = st.columns(4)
with k1:
    charts.card_kpi(rotulo_base, base_proj,
                    ajuda=f"Último mês fechado: {rotulo_ref}. É esta a base da projeção.")
with k2:
    charts.card_kpi("Imóvel (não investível)", nao_invest,
                    ajuda=("Está somado na base acima." if incluir_imovel else
                           "Fora da base acima — o toggle está desligado.")
                    + " Patrimônio real, mas não financia aposentadoria sem venda.")
with k3:
    # delta vai como NUMERO: card_kpi ja formata (eh_moeda=True por padrao).
    # Passar string pronta fazia fmt_moeda rodar em cima de texto, engolir o
    # ValueError e devolver "S$ 0".
    charts.card_kpi("Aporte mensal projetado", aporte_mes,
                    delta=aporte_extra if aporte_extra else None,
                    ajuda=f"Ritmo real dos últimos {janela} meses: "
                          f"{charts.fmt_moeda(ritmo_base)}/mês. O delta, quando "
                          "aparece, é o que você mandou somar (apartamento e/ou "
                          "dividendos).")
with k4:
    falta = max(0.0, meta - base_proj)
    charts.card_kpi("Falta para a meta", falta,
                    ajuda=f"Meta de {charts.fmt_moeda(meta)}.")

# ── As tres perguntas ─────────────────────────────────────────────────────
st.markdown("### As três perguntas")
q1, q2, q3 = st.columns(3)

with q1:
    with st.container(border=True):
        st.markdown("**Quando eu chego na meta?**")
        m_piso = meses_ate_meta(base_proj, aporte_mes, 0.0, meta)
        m_cen  = meses_ate_meta(base_proj, aporte_mes, retorno, meta)
        for rot, mm_, cor in (("Piso (0%)", m_piso, C_PISO), (f"A {retorno*100:.1f}%", m_cen, C_CEN)):
            quando = ""
            if mm_:
                aa, m2_ = somar_meses(ano_ref, mes_ref, mm_)
                quando = f" · {charts.MESES_ABREV[m2_-1]}/{aa}"
            st.markdown(f"<span style='color:{cor};font-weight:700'>{rot}</span><br>"
                        f"<span style='font-size:1.25rem'>{formatar_prazo(mm_)}</span>"
                        f"<span style='color:#64748B'>{quando}</span>",
                        unsafe_allow_html=True)

with q2:
    with st.container(border=True):
        st.markdown(f"**Quanto eu tenho em {charts.MESES_ABREV[int(mes_alvo)-1]}/{int(ano_alvo)}?**")
        v_piso = valor_em(base_proj, aporte_mes, 0.0, horizonte)
        v_cen  = valor_em(base_proj, aporte_mes, retorno, horizonte)
        st.markdown(f"<span style='color:{C_PISO};font-weight:700'>Piso (0%)</span><br>"
                    f"<span style='font-size:1.25rem'>{charts.fmt_moeda(v_piso)}</span><br>"
                    f"<span style='color:{C_CEN};font-weight:700'>A {retorno*100:.1f}%</span><br>"
                    f"<span style='font-size:1.25rem'>{charts.fmt_moeda(v_cen)}</span>",
                    unsafe_allow_html=True)

with q3:
    with st.container(border=True):
        st.markdown("**Quanto preciso aportar por mês?**")
        a_piso = aporte_necessario(base_proj, meta, 0.0, horizonte)
        a_cen  = aporte_necessario(base_proj, meta, retorno, horizonte)
        if a_piso is None:
            st.write("Defina uma data-alvo no futuro.")
        else:
            st.markdown(f"<span style='color:{C_PISO};font-weight:700'>Piso (0%)</span><br>"
                        f"<span style='font-size:1.25rem'>{charts.fmt_moeda(a_piso)}/mês</span><br>"
                        f"<span style='color:{C_CEN};font-weight:700'>A {retorno*100:.1f}%</span><br>"
                        f"<span style='font-size:1.25rem'>{charts.fmt_moeda(a_cen)}/mês</span>",
                        unsafe_allow_html=True)
            folga = aporte_mes - a_cen
            st.caption(
                f"Você aporta {charts.fmt_moeda(aporte_mes)}/mês — "
                + (f"**{charts.fmt_moeda(folga)} acima** do necessário. ✅"
                   if folga >= 0 else
                   f"**{charts.fmt_moeda(abs(folga))} abaixo** do necessário.")
            )

# ── Grafico: historico + duas projecoes ───────────────────────────────────
st.markdown("### Trajetória")

hist = df_pat[["periodo", col_base]].copy()
meses_plot = max(horizonte, 1)
proj_piso = projetar(base_proj, aporte_mes, 0.0, meses_plot)
proj_cen  = projetar(base_proj, aporte_mes, retorno, meses_plot)
datas_proj = pd.date_range(hist["periodo"].iloc[-1] + pd.DateOffset(months=1),
                           periods=meses_plot, freq="MS")

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=hist["periodo"], y=hist[col_base], name="Realizado",
    mode="lines", line=dict(color=C_HIST, width=2.5),
    hovertemplate="%{x|%b/%Y}<br>Realizado: %{y:,.0f}<extra></extra>"))
# As projecoes comecam no ultimo ponto real pra linha nao "pular".
fig.add_trace(go.Scatter(
    x=[hist["periodo"].iloc[-1]] + list(datas_proj), y=[base_proj] + proj_piso,
    name="Projeção · piso (0%)", mode="lines",
    line=dict(color=C_PISO, width=2, dash="dot"),
    hovertemplate="%{x|%b/%Y}<br>Piso: %{y:,.0f}<extra></extra>"))
fig.add_trace(go.Scatter(
    x=[hist["periodo"].iloc[-1]] + list(datas_proj), y=[base_proj] + proj_cen,
    name=f"Projeção · {retorno*100:.1f}%", mode="lines",
    line=dict(color=C_CEN, width=2.5, dash="dash"),
    hovertemplate="%{x|%b/%Y}<br>Projetado: %{y:,.0f}<extra></extra>"))
fig.add_hline(y=meta, line=dict(color=C_META, width=1.5, dash="dot"),
              annotation_text=f"Meta {charts.fmt_moeda(meta)}",
              annotation_position="top left")
charts.aplicar_tema(fig, altura=420)
st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CFG)
st.caption(
    f"Parte de {charts.fmt_moeda(base_proj)} ({rotulo_base.lower()} em {rotulo_ref}) "
    f"e soma {charts.fmt_moeda(aporte_mes)}/mês. A linha pontilhada cinza é só o "
    "dinheiro aportado, sem nenhum retorno — o piso."
    + ("" if incluir_imovel else " O imóvel está fora.")
)

# ── Comparador anual ──────────────────────────────────────────────────────
st.markdown("### Estou investindo mais ou menos que antes?")
cmp_ = comparar_periodos(df_ap, ano_ref, mes_ref)
if cmp_:
    b1, b2 = st.columns(2)
    with b1:
        with st.container(border=True):
            st.markdown(f"**Jan–{charts.MESES_ABREV[mes_ref-1]} de {cmp_['ytd_ano']} "
                        f"vs {cmp_['ytd_ano_anterior']}**")
            v = cmp_["ytd_var"]
            st.markdown(f"<span style='font-size:1.5rem;font-weight:700'>"
                        f"{charts.fmt_moeda(cmp_['ytd'])}</span> "
                        f"<span style='color:{'#059669' if (v or 0) >= 0 else '#DC2626'};"
                        f"font-weight:700'>{('%+.1f%%' % v) if v is not None else '—'}</span><br>"
                        f"<span style='color:#64748B'>antes: "
                        f"{charts.fmt_moeda(cmp_['ytd_anterior'])}</span>",
                        unsafe_allow_html=True)
            st.caption("Mesma quantidade de meses dos dois lados — ano parcial não "
                       "vira queda artificial.")
    with b2:
        with st.container(border=True):
            st.markdown("**Últimos 12 meses vs 12 anteriores**")
            v = cmp_["rolling12_var"]
            st.markdown(f"<span style='font-size:1.5rem;font-weight:700'>"
                        f"{charts.fmt_moeda(cmp_['rolling12'])}</span> "
                        f"<span style='color:{'#059669' if (v or 0) >= 0 else '#DC2626'};"
                        f"font-weight:700'>{('%+.1f%%' % v) if v is not None else '—'}</span><br>"
                        f"<span style='color:#64748B'>antes: "
                        f"{charts.fmt_moeda(cmp_['rolling12_anterior'])}</span>",
                        unsafe_allow_html=True)
            st.caption("Leitura de ritmo: não depende de onde o calendário cortou.")

# ── Esforco real por ano (financeiro + imovel) ────────────────────────────
st.markdown("### Quanto eu realmente guardei por ano")
esf = _esforco(hh)
if not esf.empty and esf["total"].abs().sum() > 0:
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(x=esf["ano"].astype(str), y=esf["financeiro"],
                          name="Investimentos", marker_color=C_HIST,
                          hovertemplate="<b>%{x}</b><br>Investimentos: %{y:,.0f}<extra></extra>"))
    fig2.add_trace(go.Bar(x=esf["ano"].astype(str), y=esf["imovel"],
                          name="Apartamento", marker_color=charts.COR_INVESTIMENTO,
                          hovertemplate="<b>%{x}</b><br>Apartamento: %{y:,.0f}<extra></extra>"))
    fig2.update_layout(barmode="stack")
    charts.aplicar_tema(fig2, altura=340)
    st.plotly_chart(fig2, use_container_width=True, config=PLOTLY_CFG)
    st.caption(
        "O pagamento do apartamento era poupança, não despesa — somá-lo mostra a "
        "capacidade real de guardar dinheiro. O valor do imóvel sai do próprio "
        "patrimônio registrado (a diferença entre dois meses é o desembolso do mês)."
    )
    with st.expander("Ver tabela"):
        tab = esf.copy()
        for c in ("financeiro", "imovel", "total"):
            tab[c] = tab[c].map(lambda v: charts.fmt_moeda(v))
        tab.columns = ["Ano", "Investimentos", "Apartamento", "Total"]
        st.dataframe(tab, use_container_width=True, hide_index=True)
else:
    st.info("Sem aportes registrados ainda.")
