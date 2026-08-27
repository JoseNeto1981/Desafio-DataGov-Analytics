-- ============================================================================
-- Perguntas de negócio -- DataGov Analytics
-- Todas as queries usam o esquema estrela definido em schema.sql.
-- Testadas contra a camada gold (ver README, seção 12, para os resultados
-- obtidos com o conjunto completo de dados).
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1. Quais são os 10 produtos ou serviços com maior valor total de compras?
-- ----------------------------------------------------------------------------
SELECT
    dp.descricao_item,
    SUM(fi.valor_item)      AS valor_total,
    COUNT(*)                AS quantidade_itens
FROM fato_item_licitacao fi
JOIN dim_produto dp ON fi.sk_produto = dp.sk_produto
GROUP BY dp.descricao_item
ORDER BY valor_total DESC
LIMIT 10;


-- ----------------------------------------------------------------------------
-- 2. Quais são os 10 fornecedores com maior volume financeiro?
-- ----------------------------------------------------------------------------
SELECT
    df.nome_fornecedor,
    df.codigo_fornecedor,
    df.tipo_documento,
    SUM(fi.valor_item)      AS valor_total
FROM fato_item_licitacao fi
JOIN dim_fornecedor df ON fi.sk_fornecedor = df.sk_fornecedor
GROUP BY df.nome_fornecedor, df.codigo_fornecedor, df.tipo_documento
ORDER BY valor_total DESC
LIMIT 10;


-- ----------------------------------------------------------------------------
-- 3. Qual estado brasileiro apresenta o maior volume financeiro em compras?
--    (ranking completo, não só o primeiro colocado, para dar contexto)
-- ----------------------------------------------------------------------------
SELECT
    do_.uf,
    SUM(fi.valor_item)      AS valor_total
FROM fato_item_licitacao fi
JOIN dim_orgao do_ ON fi.sk_orgao = do_.sk_orgao
WHERE do_.uf IS NOT NULL
GROUP BY do_.uf
ORDER BY valor_total DESC;


-- ----------------------------------------------------------------------------
-- 4. Como o volume financeiro de compras evoluiu ao longo do tempo?
-- ----------------------------------------------------------------------------
SELECT
    dt.ano,
    dt.mes,
    dt.nome_mes,
    SUM(fi.valor_item)      AS valor_total,
    COUNT(*)                AS quantidade_itens
FROM fato_item_licitacao fi
JOIN dim_tempo dt ON fi.sk_tempo = dt.sk_tempo
GROUP BY dt.ano, dt.mes, dt.nome_mes
ORDER BY dt.ano, dt.mes;


-- ----------------------------------------------------------------------------
-- 5. Qual é o preço médio dos produtos ou serviços?
--    Preço médio geral, e também por produto (para os itens mais recorrentes,
--    já que a média de um produto comprado só 1 vez não é muito informativa).
-- ----------------------------------------------------------------------------

-- Preço médio unitário geral, considerando todos os itens:
SELECT AVG(valor_unitario_item) AS preco_medio_geral
FROM fato_item_licitacao
WHERE valor_unitario_item IS NOT NULL;

-- Preço médio por produto (apenas produtos comprados 5+ vezes, para reduzir ruído):
SELECT
    dp.descricao_item,
    COUNT(*)                          AS quantidade_ocorrencias,
    AVG(fi.valor_unitario_item)       AS preco_medio,
    STDDEV(fi.valor_unitario_item)    AS desvio_padrao
FROM fato_item_licitacao fi
JOIN dim_produto dp ON fi.sk_produto = dp.sk_produto
WHERE fi.valor_unitario_item IS NOT NULL
GROUP BY dp.descricao_item
HAVING COUNT(*) >= 5
ORDER BY quantidade_ocorrencias DESC
LIMIT 20;


-- ----------------------------------------------------------------------------
-- 6. Quais órgãos públicos apresentam maior volume de compras?
-- ----------------------------------------------------------------------------
SELECT
    do_.nome_orgao,
    do_.nome_orgao_superior,
    do_.uf,
    SUM(fi.valor_item)      AS valor_total
FROM fato_item_licitacao fi
JOIN dim_orgao do_ ON fi.sk_orgao = do_.sk_orgao
GROUP BY do_.nome_orgao, do_.nome_orgao_superior, do_.uf
ORDER BY valor_total DESC
LIMIT 10;


-- ----------------------------------------------------------------------------
-- 7. Quais categorias de produtos ou serviços apresentam maior movimentação
--    financeira?
--    LIMITAÇÃO DOCUMENTADA: a fonte de dados não traz um catálogo de
--    categorias (como o CATMAT/CATSER do sistema Compras.gov.br) -- só a
--    descrição textual de cada item. Por isso, "categoria" aqui é tratada
--    no nível de produto/descrição -- na prática, equivalente à pergunta 1.
--    Ver seção "Limitações" e "Possíveis melhorias futuras" no README.
-- ----------------------------------------------------------------------------
SELECT
    dp.descricao_item       AS categoria_aproximada,
    SUM(fi.valor_item)      AS valor_total
FROM fato_item_licitacao fi
JOIN dim_produto dp ON fi.sk_produto = dp.sk_produto
GROUP BY dp.descricao_item
ORDER BY valor_total DESC
LIMIT 10;


-- ----------------------------------------------------------------------------
-- 8. Quais fornecedores apresentam preços significativamente superiores à
--    média observada para determinado produto ou serviço?
--
--    CRITÉRIO DE ANOMALIA (documentar no README): um item é considerado
--    "significativamente acima da média" quando seu valor unitário excede
--    a média do produto em mais de 2 desvios-padrão -- critério estatístico
--    padrão (equivalente a ~95% de confiança sob distribuição aproximadamente
--    normal). Produtos com menos de 5 ocorrências são excluídos: desvio-padrão
--    de amostras muito pequenas não é confiável.
-- ----------------------------------------------------------------------------
WITH estatisticas_produto AS (
    SELECT
        sk_produto,
        AVG(valor_unitario_item)      AS media,
        STDDEV(valor_unitario_item)   AS desvio_padrao,
        COUNT(*)                       AS quantidade_ocorrencias
    FROM fato_item_licitacao
    WHERE valor_unitario_item IS NOT NULL
    GROUP BY sk_produto
    HAVING COUNT(*) >= 5
)
SELECT
    df.nome_fornecedor,
    dp.descricao_item,
    fi.valor_unitario_item,
    ep.media                                                   AS preco_medio_produto,
    ROUND(((fi.valor_unitario_item - ep.media) / NULLIF(ep.desvio_padrao, 0))::numeric, 2) AS desvios_acima_da_media
FROM fato_item_licitacao fi
JOIN estatisticas_produto ep ON fi.sk_produto = ep.sk_produto
JOIN dim_fornecedor df ON fi.sk_fornecedor = df.sk_fornecedor
JOIN dim_produto dp ON fi.sk_produto = dp.sk_produto
WHERE fi.valor_unitario_item > ep.media + 2 * ep.desvio_padrao
ORDER BY desvios_acima_da_media DESC
LIMIT 30;


-- ----------------------------------------------------------------------------
-- 9. Quais estados apresentam maior quantidade de fornecedores?
--    Interpretado como: em quantos fornecedores distintos disputaram
--    licitações de órgãos sediados em cada estado (via fato_participacao,
--    que registra todos os participantes, não só os vencedores).
-- ----------------------------------------------------------------------------
SELECT
    do_.uf,
    COUNT(DISTINCT fp.sk_fornecedor)   AS quantidade_fornecedores_distintos
FROM fato_participacao fp
JOIN dim_licitacao dl ON fp.sk_licitacao = dl.sk_licitacao
JOIN dim_orgao do_ ON dl.codigo_ug = do_.codigo_ug
WHERE do_.uf IS NOT NULL
GROUP BY do_.uf
ORDER BY quantidade_fornecedores_distintos DESC;


-- ----------------------------------------------------------------------------
-- 10. Existem possíveis anomalias de preço que deveriam ser investigadas?
--     Mesmo critério estatístico da pergunta 8 (> 2 desvios-padrão acima da
--     média do produto), mas listando os REGISTROS individuais mais extremos
--     para investigação pontual, com contexto completo (órgão, data, fornecedor).
-- ----------------------------------------------------------------------------
WITH estatisticas_produto AS (
    SELECT
        sk_produto,
        AVG(valor_unitario_item)      AS media,
        STDDEV(valor_unitario_item)   AS desvio_padrao,
        COUNT(*)                       AS quantidade_ocorrencias
    FROM fato_item_licitacao
    WHERE valor_unitario_item IS NOT NULL
    GROUP BY sk_produto
    HAVING COUNT(*) >= 5
)
SELECT
    dt.data,
    do_.nome_orgao,
    do_.uf,
    df.nome_fornecedor,
    dp.descricao_item,
    fi.valor_unitario_item,
    ep.media                                                    AS preco_medio_produto,
    ROUND(((fi.valor_unitario_item - ep.media) / NULLIF(ep.desvio_padrao, 0))::numeric, 2) AS desvios_acima_da_media
FROM fato_item_licitacao fi
JOIN estatisticas_produto ep ON fi.sk_produto = ep.sk_produto
JOIN dim_fornecedor df ON fi.sk_fornecedor = df.sk_fornecedor
JOIN dim_produto dp ON fi.sk_produto = dp.sk_produto
JOIN dim_orgao do_ ON fi.sk_orgao = do_.sk_orgao
LEFT JOIN dim_tempo dt ON fi.sk_tempo = dt.sk_tempo
WHERE fi.valor_unitario_item > ep.media + 2 * ep.desvio_padrao
ORDER BY desvios_acima_da_media DESC
LIMIT 20;