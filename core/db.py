"""
Conexao e primitivas de acesso ao Postgres (Supabase) do App 10M.

Este e o unico ponto que abre conexao com o banco. Todos os modulos de
dominio (core/database.py e os futuros core/<modulo>.py) importam DAQUI as
funcoes query_df / execute e o helper _hh — em vez de cada um abrir conexao
por conta propria. Centralizar aqui deixa o resto do codigo focado em "qual
query", nao em "como conectar".

Conexao via SESSION POOLER + sslmode=require (decisao fixa do projeto — Direct
Connection falha por IPv6 no host onde o Streamlit Cloud roda). As credenciais
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
    """Roda um SELECT e devolve o resultado como DataFrame do pandas."""
    conn = get_conn()
    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()
    return df


def execute(sql, params=None):
    """Roda um INSERT/UPDATE/DELETE com commit. Nao devolve resultado."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


def _hh(household_id=None) -> int:
    """
    Resolve household_id: usa o explicito se passado, senao puxa do session_state.
    Levanta RuntimeError se nao houver usuario logado (vide core/auth.py).
    """
    if household_id is not None:
        return int(household_id)
    return get_current_household_id()
