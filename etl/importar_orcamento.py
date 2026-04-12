"""
ETL: Importa orcamento do Google Sheets (CSV) para PostgreSQL
Estrutura esperada do CSV:
  Col A: Natureza  (Pessoal, Profissional...)
  Col B: Tipo/Categoria
  Col C: Item (opcional, ignorado - orcamento e por categoria)
  Col D em diante: valores de Jan a Dez (12 colunas)

Uso: python etl/importar_orcamento.py orcamento.csv
     python etl/importar_orcamento.py orcamento.csv --reset
"""

import sys
import os
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "dbname":   os.getenv("DB_NAME", "app10milhoes"),
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}

MESES_NOMES = [
    "Janeiro","Fevereiro","Março","Abril","Maio","Junho",
    "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"
]

def clean(v):
    if v is None:
        return None
    s = str(v).strip()
    return None if s in ("", "nan", "None", "---") else s

def parse_valor(v):
    try:
        return float(str(v).replace(",","."))
    except:
        return 0.0

def encontrar_colunas_meses(cols):
    """
    Tenta identificar quais colunas correspondem aos 12 meses.
    Aceita nomes em portugues, ingles, ou simplesmente as 12 primeiras
    colunas numericas apos as colunas de categoria.
    """
    # Inclui variantes sem acentuacao (ex: Marco, Fevereiro com encoding diferente)
    meses_pt = [m.lower() for m in MESES_NOMES] + [
        "marco","fevereiro","setembro","outubro","novembro","dezembro"
    ]
    meses_en = ["jan","feb","mar","apr","may","jun",
                "jul","aug","sep","oct","nov","dec"]

    indices = []
    for i, c in enumerate(cols):
        cl = str(c).lower().strip()
        if cl in meses_pt or cl in meses_en or cl in [m[:3].lower() for m in MESES_NOMES]:
            indices.append(i)

    if len(indices) == 12:
        return indices

    # Fallback: pega as 12 primeiras colunas numericas depois das 2 primeiras
    indices = []
    for i, c in enumerate(cols):
        if i < 2:
            continue
        if str(c).lower() in ("total","orcado","realizado","%","ano","item"):
            continue
        indices.append(i)
        if len(indices) == 12:
            break

    return indices

def carregar_csv(filepath):
    for enc in ("utf-8","latin-1","cp1252"):
        try:
            df = pd.read_csv(filepath, encoding=enc, dtype=str)
            print("Encoding: " + enc)
            break
        except UnicodeDecodeError:
            continue
    df.dropna(how="all", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df

def processar_orcamento(df):
    cols = list(df.columns)
    print("Colunas detectadas: " + str(cols))

    col_indices_meses = encontrar_colunas_meses(cols)
    print("Colunas de meses (indices): " + str(col_indices_meses))

    if len(col_indices_meses) != 12:
        print("ERRO: Nao foi possivel identificar as 12 colunas de meses.")
        print("Verifique se o CSV tem colunas com nomes de meses (Janeiro, Fevereiro...)")
        sys.exit(1)

    rows = []
    puladas = 0

    for idx, row in df.iterrows():
        natureza = clean(row.iloc[0])
        tipo     = clean(row.iloc[1])

        # Pula linhas de cabecalho, total ou vazias
        if not natureza or not tipo:
            puladas += 1
            continue
        nat_lower = natureza.lower()
        tip_lower = tipo.lower()
        if nat_lower in ("natureza","total","") or tip_lower in ("tipo","total","categoria","item",""):
            puladas += 1
            continue

        for mes_idx, col_pos in enumerate(col_indices_meses):
            nro_mes = mes_idx + 1
            valor   = parse_valor(row.iloc[col_pos])
            if valor > 0:
                rows.append((natureza, tipo, None, nro_mes, 2026, valor))

    print(str(len(rows)) + " entradas de orcamento encontradas | " + str(puladas) + " linhas ignoradas")
    return rows

def inserir_orcamento(rows, limpar_antes=False):
    print("Conectando ao banco...")
    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    if limpar_antes:
        print("Limpando tabela orcamento...")
        cur.execute("TRUNCATE TABLE orcamento RESTART IDENTITY;")

    # Com TRUNCATE, insere direto sem ON CONFLICT
    sql = """
        INSERT INTO orcamento (natureza, tipo, item, nro_mes, ano, valor)
        VALUES %s
    """
    execute_values(cur, sql, rows, page_size=200)
    conn.commit()
    cur.close()
    conn.close()
    print(str(len(rows)) + " registros de orcamento inseridos!")

def main():
    if len(sys.argv) < 2:
        print("Uso: python etl/importar_orcamento.py orcamento.csv")
        sys.exit(1)

    filepath = sys.argv[1]
    limpar   = "--reset" in sys.argv

    if not Path(filepath).exists():
        print("Arquivo nao encontrado: " + filepath)
        sys.exit(1)

    print("Carregando " + filepath + "...")
    df   = carregar_csv(filepath)
    rows = processar_orcamento(df)

    if rows:
        inserir_orcamento(rows, limpar_antes=limpar)
    else:
        print("Nenhum dado valido encontrado. Verifique o formato do CSV.")

    print("ETL Orcamento concluido!")

if __name__ == "__main__":
    main()