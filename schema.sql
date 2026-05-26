-- =============================================================
-- APP 10 MILHÕES — SCHEMA PESSOAL (Módulo 1)
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

CREATE TABLE IF NOT EXISTS config_entradas (
    id                SERIAL PRIMARY KEY,
    quem              VARCHAR(50),
    natureza          VARCHAR(50) NOT NULL,
    tipo              VARCHAR(100) NOT NULL,
    categoria         VARCHAR(100),
    requer_comentario BOOLEAN DEFAULT FALSE
);

INSERT INTO config_entradas (quem, natureza, tipo, categoria, requer_comentario) VALUES
  ('Vinicius','Pessoal','Salário',NULL,FALSE),
  ('Juliana','Pessoal','Salário',NULL,FALSE),
  ('Vinicius','Pessoal','Reembolso',NULL,FALSE),
  ('Juliana','Pessoal','Reembolso',NULL,FALSE),
  ('Vinicius','Pessoal','Bônus',NULL,TRUE),
  ('Juliana','Pessoal','Bônus',NULL,TRUE),
  ('Vinicius','Profissional','Reembolso Sheares',NULL,TRUE),
  ('Vinicius','Profissional','Congresso',NULL,TRUE)
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS config_saidas (
    id          SERIAL PRIMARY KEY,
    natureza    VARCHAR(50)  NOT NULL,
    tipo        VARCHAR(100) NOT NULL,
    item        VARCHAR(100),
    -- ordem: usada em ORDER BY para controlar a posição visual da categoria nos selects.
    --        default 99 deixa novas categorias no final até serem ordenadas manualmente.
    ordem       INTEGER       DEFAULT 99,
    -- anual: marca categorias pagas em lump sum (uma vez por ano) — ex.: seguro saúde,
    --        imposto Juliana, seguro viagem. Atributo permanente da categoria.
    anual       BOOLEAN       DEFAULT FALSE,
    -- quitado_ano: registra em que ano essa categoria foi quitada. NULL = não quitada.
    --              Quando o app está em ano novo e quitado_ano != ano_corrente, a categoria
    --              volta a aparecer normalmente no BI (sem precisar de reset manual).
    quitado_ano INTEGER       NULL
);

-- Garante que bancos antigos (criados antes destas colunas) recebam a alteração
-- sem precisar dropar a tabela. ADD COLUMN IF NOT EXISTS é idempotente.
ALTER TABLE config_saidas ADD COLUMN IF NOT EXISTS ordem        INTEGER DEFAULT 99;
ALTER TABLE config_saidas ADD COLUMN IF NOT EXISTS anual        BOOLEAN DEFAULT FALSE;
ALTER TABLE config_saidas ADD COLUMN IF NOT EXISTS quitado_ano  INTEGER NULL;

-- Migra dados do esquema antigo (coluna quitado BOOLEAN) caso ela ainda exista.
-- Idempotente: se a coluna já foi removida, o DO bloco não faz nada.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'config_saidas' AND column_name = 'quitado'
    ) THEN
        EXECUTE 'UPDATE config_saidas
                    SET anual       = COALESCE(anual, FALSE) OR quitado,
                        quitado_ano = CASE WHEN quitado THEN 2026 ELSE quitado_ano END
                  WHERE quitado IS NOT NULL';
        EXECUTE 'ALTER TABLE config_saidas DROP COLUMN quitado';
    END IF;
END$$;

INSERT INTO config_saidas (natureza, tipo, item) VALUES
  ('Pessoal','Mercado',NULL),
  ('Pessoal','Transporte',NULL),
  ('Pessoal','Saúde',NULL),
  ('Pessoal','Beleza',NULL),
  ('Pessoal','Singtel',NULL),
  ('Pessoal','Piano',NULL),
  ('Pessoal','Imposto Vinicius',NULL),
  ('Pessoal','Imposto Juliana',NULL),
  ('Pessoal','Seguro Viagem',NULL),
  ('Pessoal','Seguro Saúde',NULL),
  ('Pessoal','Outros',NULL),
  ('Pessoal','Gasto Brasil',NULL),
  ('Pessoal','Lazer','Ingressos'),
  ('Pessoal','Lazer','F&B'),
  ('Pessoal','Vestuário','Essencial'),
  ('Pessoal','Vestuário','Não Essencial'),
  ('Pessoal','Viagem','Alimentação'),
  ('Pessoal','Viagem','Transporte'),
  ('Pessoal','Viagem','Ingressos'),
  ('Pessoal','Viagem','Hotel'),
  ('Pessoal','Viagem','Passagem'),
  ('Pessoal','Viagem','Outros'),
  ('Pessoal','Presentes',NULL),
  ('Pessoal','Subscrições','Disney+'),
  ('Pessoal','Subscrições','ChatGPT'),
  ('Pessoal','Subscrições','Gemini'),
  ('Pessoal','Subscrições','Dropbox'),
  ('Pessoal','Subscrições','Amazon Prime'),
  ('Pessoal','Subscrições','Spotify'),
  ('Pessoal','Subscrições','YouTube'),
  ('Pessoal','Subscrições','Outros'),
  ('Profissional','Congresso','Passagem'),
  ('Profissional','Congresso','Hotel'),
  ('Profissional','Congresso','Ingresso'),
  ('Profissional','Congresso','Transporte'),
  ('Profissional','Congresso','Inscrição'),
  ('Profissional','Congresso','Anuidade'),
  ('Profissional','Sheares',NULL)
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS orcamento (
    id       SERIAL PRIMARY KEY,
    natureza VARCHAR(50)   NOT NULL,
    tipo     VARCHAR(100)  NOT NULL,
    item     VARCHAR(100),
    nro_mes  INTEGER REFERENCES meses(nro),
    ano      INTEGER       NOT NULL,
    valor    NUMERIC(12,2) DEFAULT 0,
    UNIQUE (natureza, tipo, item, nro_mes, ano)
);

CREATE TABLE IF NOT EXISTS lancamentos (
    id         SERIAL PRIMARY KEY,
    data       DATE          NOT NULL,
    mes        VARCHAR(20),
    ano        INTEGER,
    quem       VARCHAR(50),
    tipo_geral VARCHAR(20),
    natureza   VARCHAR(50),
    quem_resp  VARCHAR(50),
    categoria  VARCHAR(100),
    item       VARCHAR(100),
    valor      NUMERIC(12,2),
    pagamento  VARCHAR(50),
    observacao TEXT,
    valor_real NUMERIC(12,2),
    nro_mes    INTEGER REFERENCES meses(nro),
    criado_em  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lan_ano       ON lancamentos(ano);
CREATE INDEX IF NOT EXISTS idx_lan_mes       ON lancamentos(nro_mes);
CREATE INDEX IF NOT EXISTS idx_lan_quem      ON lancamentos(quem);
CREATE INDEX IF NOT EXISTS idx_lan_tipo      ON lancamentos(tipo_geral);
CREATE INDEX IF NOT EXISTS idx_lan_natureza  ON lancamentos(natureza);
CREATE INDEX IF NOT EXISTS idx_lan_categoria ON lancamentos(categoria);

CREATE TABLE IF NOT EXISTS usuarios (
    id        SERIAL PRIMARY KEY,
    nome      VARCHAR(50) NOT NULL UNIQUE,
    papel     VARCHAR(20) DEFAULT 'membro',
    tipo      VARCHAR(20) DEFAULT 'permanente',
    ativo     BOOLEAN DEFAULT TRUE,
    criado_em TIMESTAMP DEFAULT NOW()
);

INSERT INTO usuarios (nome, papel, tipo, ativo) VALUES
  ('Vinicius', 'admin', 'permanente', TRUE),
  ('Juliana',  'membro','permanente', TRUE)
ON CONFLICT DO NOTHING;