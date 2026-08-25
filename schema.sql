-- ============================================================================
-- Data Warehouse -- DataGov Analytics
-- Esquema estrela: 5 dimensões + 2 tabelas fato.
--
-- Grão das tabelas fato (ver README, seção 9, para a justificativa completa):
--   fato_item_licitacao: 1 linha = 1 item vencido dentro de 1 licitação.
--   fato_participacao:   1 linha = 1 fornecedor disputando 1 item.
--
-- Este arquivo é montado como script de inicialização do container Postgres
-- (docker-compose.yml) -- roda automaticamente na primeira subida do banco,
-- contra um volume de dados vazio.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Dimensões
-- ----------------------------------------------------------------------------

CREATE TABLE dim_tempo (
    sk_tempo   INTEGER PRIMARY KEY,
    data       DATE NOT NULL UNIQUE,
    ano        SMALLINT NOT NULL,
    mes        SMALLINT NOT NULL,
    trimestre  SMALLINT NOT NULL,
    nome_mes   VARCHAR(20) NOT NULL
);

CREATE TABLE dim_orgao (
    sk_orgao               INTEGER PRIMARY KEY,
    codigo_ug               VARCHAR(20) NOT NULL UNIQUE,
    nome_ug                 VARCHAR(200),
    codigo_orgao             VARCHAR(20),
    nome_orgao               VARCHAR(200),
    codigo_orgao_superior    VARCHAR(20),
    nome_orgao_superior      VARCHAR(200),
    uf                       CHAR(2),
    municipio                VARCHAR(120)
);

CREATE TABLE dim_fornecedor (
    sk_fornecedor      INTEGER PRIMARY KEY,
    codigo_fornecedor  VARCHAR(20) NOT NULL UNIQUE,
    nome_fornecedor    VARCHAR(200),
    -- CNPJ, CPF, ESTRANGEIRO ou OUTRO (ver decisão documentada no README:
    -- código no padrão ESTRANG... é uma categoria legítima, não erro).
    tipo_documento      VARCHAR(20)
);

CREATE TABLE dim_produto (
    sk_produto       INTEGER PRIMARY KEY,
    descricao_item   TEXT NOT NULL
);

CREATE TABLE dim_licitacao (
    sk_licitacao               INTEGER PRIMARY KEY,
    numero_licitacao           VARCHAR(30) NOT NULL,
    codigo_ug                  VARCHAR(20) NOT NULL,
    -- Modalidade faz parte da chave de negócio: o mesmo par
    -- (numero_licitacao, codigo_ug) pode se repetir com modalidades
    -- diferentes -- achado real documentado no README, seção 9.
    codigo_modalidade_compra   VARCHAR(10) NOT NULL,
    numero_processo             VARCHAR(50),
    modalidade_compra           VARCHAR(60),
    situacao_licitacao          VARCHAR(60),
    objeto                       TEXT,
    valor_licitacao              NUMERIC(18, 2),
    UNIQUE (numero_licitacao, codigo_ug, codigo_modalidade_compra)
);

-- ----------------------------------------------------------------------------
-- Fatos
-- ----------------------------------------------------------------------------

CREATE TABLE fato_item_licitacao (
    sk_fato_item          BIGSERIAL PRIMARY KEY,
    sk_tempo              INTEGER REFERENCES dim_tempo(sk_tempo),
    sk_orgao              INTEGER REFERENCES dim_orgao(sk_orgao),
    sk_fornecedor         INTEGER REFERENCES dim_fornecedor(sk_fornecedor),
    sk_produto            INTEGER REFERENCES dim_produto(sk_produto),
    sk_licitacao          INTEGER REFERENCES dim_licitacao(sk_licitacao),
    quantidade_item       NUMERIC(18, 4),
    valor_item            NUMERIC(18, 4),
    valor_unitario_item   NUMERIC(18, 4)
);

CREATE TABLE fato_participacao (
    sk_fato_participacao  BIGSERIAL PRIMARY KEY,
    sk_licitacao          INTEGER REFERENCES dim_licitacao(sk_licitacao),
    sk_produto            INTEGER REFERENCES dim_produto(sk_produto),
    -- Permite NULL: 24 participantes com código inválido na origem
    -- (ex.: "-11") foram zerados na camada silver -- decisão documentada
    -- no README -- e não devem quebrar a carga por violação de FK.
    sk_fornecedor         INTEGER REFERENCES dim_fornecedor(sk_fornecedor),
    flag_vencedor         BOOLEAN
);

-- ----------------------------------------------------------------------------
-- Índices -- nas chaves estrangeiras dos fatos (aceleram os JOINs das
-- perguntas de negócio) e nas colunas mais usadas em filtro/agrupamento.
-- ----------------------------------------------------------------------------

CREATE INDEX idx_fato_item_tempo       ON fato_item_licitacao (sk_tempo);
CREATE INDEX idx_fato_item_orgao       ON fato_item_licitacao (sk_orgao);
CREATE INDEX idx_fato_item_fornecedor  ON fato_item_licitacao (sk_fornecedor);
CREATE INDEX idx_fato_item_produto     ON fato_item_licitacao (sk_produto);
CREATE INDEX idx_fato_item_licitacao   ON fato_item_licitacao (sk_licitacao);

CREATE INDEX idx_fato_part_licitacao   ON fato_participacao (sk_licitacao);
CREATE INDEX idx_fato_part_produto     ON fato_participacao (sk_produto);
CREATE INDEX idx_fato_part_fornecedor  ON fato_participacao (sk_fornecedor);

CREATE INDEX idx_dim_orgao_uf          ON dim_orgao (uf);
CREATE INDEX idx_dim_tempo_ano_mes     ON dim_tempo (ano, mes);