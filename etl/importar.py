"""
ETL: Importa lancamentos do Google Sheets (CSV) para PostgreSQL
Uso: python etl/importar.py lancamentos.csv
     python etl/importar.py lancamentos.csv --reset
"""

import sys
import os
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from pathlib import Path
from datetime import date

load_dotenv(Path(__file__).parent.parent / ".env")

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "dbname":   os.getenv("DB_NAME", "app10milhoes"),
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "sslmode":  "require",
}

MESES_MAP = {
    "janeiro":1,"fevereiro":2,"marco":3,"marco":3,"abril":4,
    "maio":5,"junho":6,"julho":7,"agosto":8,
    "setembro":9,"outubro":10,"novembro":11,"dezembro":12
}

def clean(v):
    if v is None:
        return None
    s = str(v).strip()
    return None if s in ("", "---", "N/A", "nan", "None") else s

def parse_valor(v):
    if v is None or str(v).strip() in ("", "nan", "None"):
        return 0.0
    return float(str(v).replace(",", "."))

def parse_date(v):
    try:
        return pd.to_datetime(v).date()
    except:
        return None

def inferir_nro_mes(mes_str, nro_mes_raw):
    try:
        n = int(float(str(nro_mes_raw)))
        if 1 <= n <= 12:
            return n
    except:
        pass
    if mes_str:
        return MESES_MAP.get(mes_str.lower().strip(), None)
    return None

def carregar_arquivo(filepath):
    print("Carregando " + filepath + "...")
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            df = pd.read_csv(filepath, encoding=enc, dtype=str)
            print("   Encoding: " + enc)
            break
        except UnicodeDecodeError:
            continue
    df.dropna(how="all", inplace=True)
    df.reset_index(drop=True, inplace=True)
    print("   " + str(len(df)) + " linhas encontradas.")
    return df

def normalizar_colunas(df):
    cols = list(df.columns)
    print("   Colunas: " + str(cols))

    quem_idx = [i for i, c in enumerate(cols) if str(c).strip().lower() == "quem"]
    if len(quem_idx) >= 2:
        cols[quem_idx[0]] = "quem_lancador"
        cols[quem_idx[1]] = "quem_resp"
    elif len(quem_idx) == 1:
        cols[quem_idx[0]] = "quem_lancador"

    df.columns = cols

    rename_map = {
        "data": "data",
        "mes": "mes",
        "ano": "ano",
        "tipo": "tipo_geral",
        "natureza": "natureza",
        "categoria": "categoria",
        "item": "item",
        "valor": "valor",
        "pagamento": "pagamento",
        "observacao": "observacao",
        "observacao": "observacao",
        "valor real": "valor_real",
        "nro mes": "nro_mes",
        "nro_mes": "nro_mes",
    }
    df.columns = [rename_map.get(c.strip().lower(), c.strip().lower()) for c in df.columns]
    return df

MESES_NOME = {
    1:"Janeiro",2:"Fevereiro",3:"Março",4:"Abril",
    5:"Maio",6:"Junho",7:"Julho",8:"Agosto",
    9:"Setembro",10:"Outubro",11:"Novembro",12:"Dezembro"
}

def processar_linhas(df):
    rows = []
    erros = 0

    for idx, row in df.iterrows():
        try:
            # nro_mes e' a fonte de verdade — ignora coluna "mes"
            nro_mes    = inferir_nro_mes(None, row.get("nro_mes"))
            mes_str    = MESES_NOME.get(nro_mes) if nro_mes else None
            data       = parse_date(row.get("data"))
            valor      = parse_valor(row.get("valor"))
            tipo_geral = clean(row.get("tipo_geral", ""))

            if data is None and valor == 0:
                continue
            if data is None:
                data = date.today()
            if not nro_mes:
                print("   Linha " + str(idx+2) + " ignorada: nro_mes invalido")
                erros += 1
                continue

            valor_real_raw = row.get("valor_real")
            if clean(valor_real_raw):
                valor_real = parse_valor(valor_real_raw)
            else:
                valor_real = valor if (tipo_geral or "").lower() == "entrada" else -valor

            rows.append((
                data,
                mes_str,  # sempre derivado do nro_mes
                int(float(row.get("ano", 2026) or 2026)),
                clean(row.get("quem_lancador")),
                tipo_geral,
                clean(row.get("natureza")),
                clean(row.get("quem_resp", row.get("quem_lancador"))),
                clean(row.get("categoria")),
                clean(row.get("item")),
                valor,
                clean(row.get("pagamento")),
                clean(row.get("observacao")),
                valor_real,
                nro_mes,
            ))
        except Exception as e:
            print("   Linha " + str(idx+2) + " ignorada: " + str(e))
            erros += 1

    print("   " + str(len(rows)) + " linhas validas | " + str(erros) + " ignoradas")
    return rows

def inserir_no_banco(rows, limpar_antes=False):
    print("Conectando ao banco...")
    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    if limpar_antes:
        print("   Limpando tabela lancamentos...")
        cur.execute("TRUNCATE TABLE lancamentos RESTART IDENTITY;")

    sql = (
        "INSERT INTO lancamentos "
        "(data, mes, ano, quem, tipo_geral, natureza, quem_resp, "
        "categoria, item, valor, pagamento, observacao, valor_real, nro_mes) "
        "VALUES %s"
    )

    execute_values(cur, sql, rows, page_size=500)
    conn.commit()
    cur.close()
    conn.close()
    print("   " + str(len(rows)) + " registros inseridos com sucesso!")

def main():
    if len(sys.argv) < 2:
        print("Uso: python etl/importar.py lancamentos.csv")
        sys.exit(1)

    filepath  = sys.argv[1]
    limpar    = "--reset" in sys.argv

    if not Path(filepath).exists():
        print("Arquivo nao encontrado: " + filepath)
        sys.exit(1)

    df   = carregar_arquivo(filepath)
    df   = normalizar_colunas(df)
    rows = processar_linhas(df)

    if rows:
        inserir_no_banco(rows, limpar_antes=limpar)
    else:
        print("Nenhum dado valido encontrado.")

    print("ETL concluido!")

if __name__ == "__main__":
    main()