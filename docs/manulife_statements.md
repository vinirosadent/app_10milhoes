# Manulife statements → módulo Investimentos do App 10M

Guia para processar os extratos (statements) Manulife do Vinicius e carregar no
banco do App 10M. Serve de referência pro Cowork e pro Claude do VS Code.

## 1. As 3 apólices (identifique SEMPRE pelo número da apólice)

| App | Policy Number | Plano | Prêmio | Início | produto_id (config_investimentos) |
|---|---|---|---|---|---|
| **Manu 2k** | `2450815802` | INVESTREADY - WEALTH (II) 20 YEARS FLEXI | 2.500/mês | 08/11/2021 (lump 30k + bônus 20.343) | **2** |
| **Manu 4k** | `2450918598` | INVESTREADY - WEALTH (II) 20 YEARS FLEXI | ~4.166,67/mês | 04/2022 (lump 50k + bônus ~40.567) | **1** |
| **Manu 1k** | `2451804649` | MANULIFE INVESTREADY (III) 10 YEARS FLEXI | 1.000/mês | 08/2024 (lump 12k) | **3** |

⚠️ 2k e 4k têm o **mesmo nome de plano** — só o **Policy Number** distingue.
Há outras apólices/investimentos no Excel do Vinicius (Smartwealth 2-5yrs, Manulink
SRS, Fidelity, DigiPortfolio…) que **não** fazem parte deste módulo — ignore.

## 2. Tipos de PDF

**(a) Monthly Statement of Account** — o que importa. Campos-chave:
- `Policy Number : <dígitos>`
- `Monthly Statement of Account as at <DD Mon YYYY>` → o mês de referência
- `Total Basic Premiums Paid To-Date (including any top-up premiums) $ <valor>` → prêmios acumulados
- `Account Value $ <valor>` → **VALOR DE MERCADO = fonte da verdade**
- `Total Dividends Distributed To-Date (excluding any re-invested dividends) $ <valor>` → se 0, todos os dividendos foram reinvestidos (estão DENTRO do Account Value)
- `Surrender Value $ <valor>` → valor se resgatar agora (bem menor que Account Value por causa do clawback do bônus)

**(b) Dividend Distribution Payout** (`DIVIDEND DISTRIBUTION PAYOUT` no topo) — aviso de
dividendo pago em CAIXA (não reinvestido). Campos: Policy Number, fundo, Ex Date,
`Distribution Amount S$<valor>`. Ex.: 4k pagou S$1.337,57 (ex-date 29/05/2026).

## 3. Modelo de dados do app (NÃO esquecer)

```
Patrimônio (valor de mercado) = Σ Aporte + Σ Rendimento   →  deve bater com o Account Value
Aporte      → lancamentos (tipo_geral='Investimento', categoria='Aporte fixo', item='Manu Xk', valor_real=0)
Rendimento  → investimentos_serie.rendimento (por produto_id, ano, nro_mes)  [pode ser ±, embute bônus/clawback/mercado/divid. reinvestido]
Dividendo   → investimentos_serie.dividendo  → INFORMATIVO; NÃO somar no patrimônio
              - reinvestido=TRUE  → já está dentro do rendimento/valor (não dobrar)
              - reinvestido=FALSE → dividendo em caixa (renda que saiu); a partir de ~jun/2026
```

Estes planos são ILP (insurance-linked) com **bônus de boas-vindas no arranque** (entra
como rendimento positivo grande no 1º mês) sujeito a **clawback** (por isso Surrender
Value << Account Value). **O Account Value do extrato é sempre a verdade** — não
reconstruir patrimônio por “rendimento mensal” digitado à mão (acumula erro).

## 4. Procedimento de carga (a cada novo statement)

Para cada apólice, ordene os statements por data. Tendo a base do mês anterior
(`prem_prev`, `val_prev` = Account Value do mês anterior; use o que já está no app):

```
aporte[m]     = premios[m]  − prem_prev
rendimento[m] = (account_value[m] − val_prev) − aporte[m]
```

- Insira `aporte[m]` em `lancamentos` (item = 'Manu 2k'/'4k'/'1k', ano, nro_mes, valor_real=0, observacao='Statement <ano>').
- Upsert `rendimento[m]` em `investimentos_serie` (ON CONFLICT … DO UPDATE).
- Avisos de payout (cash) → `investimentos_serie.dividendo` com `reinvestido=FALSE` no mês do pagamento.
- **Conferência:** o patrimônio do produto no mês (Σaporte + Σrendimento) deve igualar o **Account Value** do statement daquele mês. Se não bater, revise.

Premissas dos prêmios: 2k=2.500, 1k=1.000, 4k≈4.166,67/mês. Os prêmios postam por
volta do dia 10–22, então o statement “as at” de um mês pode ainda não conter o
prêmio daquele mês (lag) — o `aporte = Δpremios` resolve isso automaticamente.

## 5. Extração dos PDFs (sandbox)

```bash
pip install pdfplumber --break-system-packages
```
```python
import pdfplumber, re
with pdfplumber.open(f) as pdf:
    t = "\n".join((p.extract_text() or "") for p in pdf.pages[:3])
pol  = re.search(r"Policy Number\s*:?\s*(\d+)", t).group(1)
dt   = re.search(r"as at\s+(\d{1,2}\s+\w+\s+\d{4})", t)
prem = re.search(r"Total Basic Premiums Paid To-Date[^\$]*\$?\s*([\d,]+\.\d{2})", t)
val  = re.search(r"\bAccount Value\s*\$?\s*([\d,]+\.\d{2})", t)
payout = "DIVIDEND DISTRIBUTION PAYOUT" in t   # tipo (b)
```
Notas: `pdftoppm`/Read-como-imagem **não** está disponível no sandbox — use o texto do
pdfplumber. Alguns PDFs (payout) têm cabeçalho em 2 colunas; detecte pelo título.

## 6. Estado reconciliado (até mai/2026) — checkpoint

| Produto | Aportado | Rendimento | Patrimônio | Account Value (extrato mai/26) |
|---|---|---|---|---|
| Manu 1k | 22.000 | −784 | 21.216 | 21.216,20 |
| Manu 2k | 135.000 | 38.472 | 173.472 | 173.472,16 |
| Manu 4k | 208.335 | 48.887 | 257.222 | 257.220,99 |
| **TOTAL** | 365.335 | 86.575 | **451.910** | |

Base dez/2025 (validada com o Excel): 2k 122.500/23.027/145.527 · 4k 191.658/48.314/239.972 · 1k 17.000/1.906/18.906.
Pequenos ajustes "Ajuste reconciliacao Excel"/"residuo base" no banco cobrem
inconsistências do Excel — o **Account Value do extrato manda**.
