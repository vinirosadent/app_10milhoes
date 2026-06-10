-- =============================================================
-- APP 10 MILHÕES — SCHEMA (Etapa 3: multi-usuario)
-- =============================================================
--
-- Modelo de isolamento: tabela `households` agrupa usuarios que compartilham
-- os mesmos dados. Cada household tem 2+ usuarios (login bcrypt em `usuarios`)
-- e e dono exclusivo de suas linhas em lancamentos, orcamento, config_saidas
-- e config_entradas (coluna household_id NOT NULL com FK). Tabelas globais
-- (meses, formas_pagamento, households) sao compartilhadas entre todos.
--
-- RLS habilitada em todas as tabelas como rede de seguranca defensiva — o
-- isolamento real e feito no codigo (filtro household_id em core/database.py)
-- porque o app usa psycopg2 com role que tem BYPASSRLS. As policies abaixo
-- bloqueiam o role 'anon' (defesa contra vazamento de anon key) e abrem
-- leitura publica nas globais.
--
-- Este arquivo e VERSAO DE DOCUMENTACAO — em producao foi montado via
-- migrations (vide pasta migrations no Supabase ou MCP list_migrations).
-- =============================================================

CREATE TABLE IF NOT EXISTS meses (
    nro   INTEGER PRIMARY KEY,
    nome  VARCHAR(20) NOT NULL
);

INSERT INTO meses (nro, nome) VALUES
  (1,'Janeiro'),(2,'Fevereiro'),(3,'Março'),(4,'Abril'),
  (5,'Maio'),(6,'Junho'),(7,'Julho'),(8,'Agosto'),
  (9,'Setembro'),(10,'Outubro'),(11,'Novembro'),(12,'Dezembro')
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS formas_pagamento (
    id   SERIAL PRIMARY KEY,
    nome VARCHAR(50) UNIQUE NOT NULL
);

INSERT INTO formas_pagamento (nome) VALUES
  ('Débito em conta'),('Dinheiro'),('Cartão')
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────
-- HOUSEHOLDS — agrupa usuarios que compartilham dados.
-- IDs hardcoded (1=Admin, 2=Ladroes) por simplicidade do backfill inicial.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS households (
    id        SERIAL PRIMARY KEY,
    nome      VARCHAR(50) UNIQUE NOT NULL,
    -- membros: nomes que aparecem no select "quem" do form Lancamentos.
    -- No modelo de 2 logins, Admin e usado por Vinicius+Juliana e Ladron
    -- por Ricardo+Josi — esses nomes vivem aqui, nao em usuarios (que so
    -- guarda os 2 LOGINS, nao as 4 pessoas que usam o app).
    membros   TEXT[]      DEFAULT ARRAY[]::TEXT[],
    -- Modulo de investimentos (pagina 04, aportes/dividendos/total guardado).
    -- Feature por household: TRUE so para Admin (migration
    -- add_investimentos_modulo). Ladroes nem veem a pagina.
    investimentos_ativo BOOLEAN NOT NULL DEFAULT FALSE,
    criado_em TIMESTAMP DEFAULT NOW()
);

INSERT INTO households (id, nome, membros) VALUES
  (1, 'Admin',   ARRAY['Juliana','Vinicius']::TEXT[]),
  (2, 'Ladrões', ARRAY['Josi','Ricardo']::TEXT[])
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────
-- USUARIOS — login real bcrypt (Etapa 3, modelo de 2 logins).
-- Apenas 2 rows: Admin (household 1) e Ladron (household 2) — cada login e
-- compartilhado entre 2 pessoas (Vin+Jul no Admin, Ric+Josi no Ladron). Quem
-- fez o gasto vem da coluna `quem` em lancamentos, populada via households.membros.
-- email = chave de login. password_hash = bcrypt 60 chars.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS usuarios (
    id            SERIAL PRIMARY KEY,
    nome          VARCHAR(50) NOT NULL UNIQUE,
    email         VARCHAR(120) UNIQUE,
    password_hash VARCHAR(60),
    papel         VARCHAR(20) DEFAULT 'membro',
    tipo          VARCHAR(20) DEFAULT 'permanente',
    ativo         BOOLEAN DEFAULT TRUE,
    household_id  INTEGER REFERENCES households(id),
    criado_em     TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usuarios_email ON usuarios(email) WHERE email IS NOT NULL;

CREATE TABLE IF NOT EXISTS config_entradas (
    id                SERIAL PRIMARY KEY,
    quem              VARCHAR(50),
    natureza          VARCHAR(50) NOT NULL,
    tipo              VARCHAR(100) NOT NULL,
    categoria         VARCHAR(100),
    requer_comentario BOOLEAN DEFAULT FALSE,
    household_id      INTEGER REFERENCES households(id)
);

CREATE TABLE IF NOT EXISTS config_saidas (
    id           SERIAL PRIMARY KEY,
    natureza     VARCHAR(50)  NOT NULL,
    tipo         VARCHAR(100) NOT NULL,
    item         VARCHAR(100),
    ordem        INTEGER       DEFAULT 99,
    anual        BOOLEAN       DEFAULT FALSE,
    quitado_ano  INTEGER       NULL,
    household_id INTEGER       REFERENCES households(id)
);

CREATE INDEX IF NOT EXISTS idx_cfgs_household ON config_saidas(household_id);
CREATE INDEX IF NOT EXISTS idx_cfge_household ON config_entradas(household_id);

CREATE TABLE IF NOT EXISTS orcamento (
    id            SERIAL PRIMARY KEY,
    natureza      VARCHAR(50)   NOT NULL,
    tipo          VARCHAR(100)  NOT NULL,
    item          VARCHAR(100),
    nro_mes       INTEGER REFERENCES meses(nro),
    ano           INTEGER       NOT NULL,
    valor         NUMERIC(12,2) DEFAULT 0,
    household_id  INTEGER       REFERENCES households(id),
    -- UNIQUE estendido com household_id — sem isso, Admin e Ladroes nao podem
    -- ter o mesmo (natureza, tipo, item, mes) cadastrado em paralelo.
    UNIQUE (household_id, natureza, tipo, item, nro_mes, ano)
);

CREATE INDEX IF NOT EXISTS idx_orc_household_ano ON orcamento(household_id, ano);

CREATE TABLE IF NOT EXISTS lancamentos (
    id            SERIAL PRIMARY KEY,
    data          DATE          NOT NULL,
    mes           VARCHAR(20),
    ano           INTEGER,
    quem          VARCHAR(50),
    tipo_geral    VARCHAR(20),
    natureza      VARCHAR(50),
    quem_resp     VARCHAR(50),
    categoria     VARCHAR(100),
    item          VARCHAR(100),
    valor         NUMERIC(12,2),
    pagamento     VARCHAR(50),
    observacao    TEXT,
    valor_real    NUMERIC(12,2),
    nro_mes       INTEGER REFERENCES meses(nro),
    criado_em     TIMESTAMP DEFAULT NOW(),
    household_id  INTEGER REFERENCES households(id)
);

-- Convencao do modulo de INVESTIMENTOS (sem tabela de movimentos propria —
-- os registros vivem em lancamentos):
--   tipo_geral='Investimento' + categoria 'Aporte fixo'/'Aporte variável'/
--   'Saldo inicial' (item = produto; valor_real=0 pois aporte e realocacao
--   conta->corretora, nao saida) e dividendos como tipo_geral='Entrada' +
--   categoria 'Dividendos' (caem na conta = renda real do mes).

CREATE INDEX IF NOT EXISTS idx_lan_ano               ON lancamentos(ano);
CREATE INDEX IF NOT EXISTS idx_lan_mes               ON lancamentos(nro_mes);
CREATE INDEX IF NOT EXISTS idx_lan_quem              ON lancamentos(quem);
CREATE INDEX IF NOT EXISTS idx_lan_tipo              ON lancamentos(tipo_geral);
CREATE INDEX IF NOT EXISTS idx_lan_natureza          ON lancamentos(natureza);
CREATE INDEX IF NOT EXISTS idx_lan_categoria         ON lancamentos(categoria);
CREATE INDEX IF NOT EXISTS idx_lan_household_ano_mes ON lancamentos(household_id, ano, nro_mes);

-- ─────────────────────────────────────────────────────────────
-- CONFIG_INVESTIMENTOS — produtos de investimento do modulo (pagina 04).
-- tipo='fixo': valor mensal imutavel (ex.: 'Manu 4k' -> 4166.00), entra no
--              botao de registro em lote do mes.
-- tipo='variavel': so o nome e cadastrado; o valor e digitado a cada aporte
--              avulso (investimentos sem mensalidade fixa).
-- Mudar valor_fixo NAO reescreve aportes ja registrados (valor historico
-- fica gravado no lancamento).
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS config_investimentos (
    id           SERIAL PRIMARY KEY,
    nome         VARCHAR(100)  NOT NULL,
    valor_fixo   NUMERIC(12,2) NOT NULL DEFAULT 0,
    tipo         VARCHAR(10)   NOT NULL DEFAULT 'fixo'
                 CHECK (tipo IN ('fixo','variavel')),
    ativo        BOOLEAN       NOT NULL DEFAULT TRUE,
    ordem        INTEGER       DEFAULT 99,
    -- data_inicio: mes em que o plano comecou a aportar. Usado para gerar a
    -- serie historica de aportes (valor_fixo constante desde o inicio).
    data_inicio  DATE,
    household_id INTEGER       NOT NULL REFERENCES households(id),
    criado_em    TIMESTAMP     DEFAULT NOW(),
    UNIQUE (household_id, nome)
);

CREATE INDEX IF NOT EXISTS idx_cfginv_household ON config_investimentos(household_id);

-- ─────────────────────────────────────────────────────────────
-- INVESTIMENTOS_SERIE — serie mensal por produto de RENDIMENTO e DIVIDENDO.
-- Vive FORA de `lancamentos` de proposito:
--   rendimento = valorizacao da carteira no mes (pode ser + ou -), NAO e caixa;
--   dividendo  = renda do investimento acompanhada no modulo — NAO entra nas
--                Entradas do Dashboard (evita inflar a poupanca de 2026).
-- Patrimonio = (saldo inicial + Σ aportes de lancamentos) + Σ rendimento daqui.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS investimentos_serie (
    id           SERIAL        PRIMARY KEY,
    household_id INTEGER       NOT NULL REFERENCES households(id),
    produto_id   INTEGER       NOT NULL REFERENCES config_investimentos(id),
    ano          INTEGER       NOT NULL,
    nro_mes      INTEGER       NOT NULL REFERENCES meses(nro),
    rendimento   NUMERIC(12,2) NOT NULL DEFAULT 0,
    dividendo    NUMERIC(12,2) NOT NULL DEFAULT 0,
    criado_em    TIMESTAMP     DEFAULT NOW(),
    UNIQUE (household_id, produto_id, ano, nro_mes)
);

CREATE INDEX IF NOT EXISTS idx_invserie_hh ON investimentos_serie(household_id, ano, nro_mes);

-- ─────────────────────────────────────────────────────────────
-- RLS — defesa em profundidade. O isolamento real e por codigo (filtro
-- household_id em core/database.py). RLS aqui bloqueia 'anon' (PostgREST
-- publico) e libera leitura nas tabelas globais.
-- ─────────────────────────────────────────────────────────────
ALTER TABLE meses             ENABLE ROW LEVEL SECURITY;
ALTER TABLE formas_pagamento  ENABLE ROW LEVEL SECURITY;
ALTER TABLE config_entradas   ENABLE ROW LEVEL SECURITY;
ALTER TABLE config_saidas     ENABLE ROW LEVEL SECURITY;
ALTER TABLE orcamento         ENABLE ROW LEVEL SECURITY;
ALTER TABLE lancamentos       ENABLE ROW LEVEL SECURITY;
ALTER TABLE usuarios          ENABLE ROW LEVEL SECURITY;
ALTER TABLE households        ENABLE ROW LEVEL SECURITY;
ALTER TABLE config_investimentos ENABLE ROW LEVEL SECURITY;
ALTER TABLE investimentos_serie  ENABLE ROW LEVEL SECURITY;
