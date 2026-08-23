"""
Conexao e primitivas de acesso ao Postgres (Supabase) do App 10M.

Este e o unico ponto que abre conexao com o banco. Todos os modulos de
dominio (core/database.py e os futuros core/<modulo>.py) importam DAQUI as
funcoes query_df / execute e o helper _hh - em vez de cada um abrir conexao
por conta propria. Centralizar aqui deixa o resto do codigo focado em "qual
query", nao em "como conectar".

Conexao via TRANSACTION POOLER (porta 6543) + sslmode=require. A 5432 (Session
Pooler) era bloqueada por firewall apos conexoes em rajada; Transaction mode e o
recomendado pela Supabase para conexoes curtas (Streamlit Cloud) e funciona com o
padrao abre-conexao -> 1 query -> fecha deste app. Direct Connection nao e usada
(falha por IPv6 no host do Streamlit Cloud). As credenciais
vem do arquivo .env na raiz do projeto (local) / dos secrets (Streamlit Cloud).
"""

import os
import psycopg2
import pandas as pd
from dotenv import load_dotenv
from pathlib import Path

from core.auth import get_current_household_id

# Carrega .env da raiz do projeto (um nivel acima de core/).
load_dotenv(Path(__file__).parent.parent / ".env")

_db_host = os.getenv("DB_HOST", "localhost")

# Pooler do Supabase: usar porta 6543 (Transaction Pooler). A porta 5432
# (Session Pooler) e bloqueada por firewalls apos conexoes em rajada.
_db_port = (6543 if "pooler.supabase.com" in _db_host
            else int(os.getenv("DB_PORT", 5432)))

DB_CONFIG = {
    "host":     _db_host,
    "port":     _db_port,
    "dbname":   os.getenv("DB_NAME", "app10milhoes"),
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "sslmode":  "require",
}


def get_conn():
    """Abre uma conexao nova com o banco. Quem chama e responsavel por fechar."""
    return psycopg2.connect(**DB_CONFIG)


def query_df(sql, params=None):
    """
    Roda um SELECT e devolve o resultado como DataFrame do pandas.

    Usa o cursor do psycopg2 diretamente em vez de pd.read_sql_query. Dois
    motivos:

    1. O pandas so suporta oficialmente conexoes SQLAlchemy e emite um
       UserWarning a cada chamada quando recebe uma conexao DBAPI crua. Numa
       pagina com slider, que refaz 4 consultas por render, isso vira dezenas
       de avisos por interacao e polui o log do Streamlit Cloud.
    2. A conexao agora fecha em `finally`. Antes, se a query levantasse
       excecao (erro de SQL, timeout, queda de rede), o `conn.close()` nunca
       era alcancado e a conexao vazava. Com o Transaction Pooler (6543) e o
       padrao abre-1-query-fecha deste app, conexoes vazadas acumulam ate o
       pooler recusar novas - falha intermitente e dificil de diagnosticar.

    O resultado e identico ao de antes: e o mesmo caminho que o read_sql_query
    percorreria por baixo. DataFrame vazio preserva os nomes das colunas.

    `coerce_float=True` NAO e opcional. O psycopg2 devolve colunas `numeric`
    do Postgres como `Decimal`, e o read_sql_query aplicava essa coercao por
    padrao - era ela que transformava Decimal em float64. Sem o parametro, a
    coluna vira dtype `object` cheia de Decimal, e qualquer aritmetica que
    misture float com Decimal levanta TypeError. Isso quebrou a pagina de
    Investimentos em core/database.py:1039 (`.fillna(0.0)` sobre Decimal,
    seguido de cumsum). O sintoma e traicoeiro porque soma de Decimal com
    Decimal funciona: uma pagina passa hoje e falha depois, quando um float
    entra na conta.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            colunas = [d[0] for d in cur.description] if cur.description else []
            linhas = cur.fetchall() if cur.description else []
        return pd.DataFrame.from_records(linhas, columns=colunas, coerce_float=True)
    finally:
        conn.close()


def execute(sql, params=None):
    """
    Roda um INSERT/UPDATE/DELETE com commit. Nao devolve resultado.

    Em caso de excecao faz rollback antes de fechar. Sem isso, uma falha no
    meio da transacao deixava a conexao aberta E a transacao pendurada no
    pooler, que e pior do que o vazamento do query_df: segura locks.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _hh(household_id=None) -> int:
    """
    Resolve household_id: usa o explicito se passado, senao puxa do session_state.
    Levanta RuntimeError se nao houver usuario logado (vide core/auth.py).
    """
    if household_id is not None:
        return int(household_id)
    return get_current_household_id()
