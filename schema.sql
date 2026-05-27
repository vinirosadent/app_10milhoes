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

CREATE INDEX IF NOT EXISTS idx_lan_ano               ON lancamentos(ano);
CREATE INDEX IF NOT EXISTS idx_lan_mes               ON lancamentos(nro_mes);
CREATE INDEX IF NOT EXISTS idx_lan_quem              ON lancamentos(quem);
CREATE INDEX IF NOT EXISTS idx_lan_tipo              ON lancamentos(tipo_geral);
CREATE INDEX IF NOT EXISTS idx_lan_natureza          ON lancamentos(natureza);
CREATE INDEX IF NOT EXISTS idx_lan_categoria         ON lancamentos(categoria);
CREATE INDEX IF NOT EXISTS idx_lan_household_ano_mes ON lancamentos(household_id, ano, nro_mes);

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
