-- ============================================================================
-- View: vw_anomalias_preco
--
-- Reaproveita exatamente o critério estatístico já validado em
-- perguntas_negocio.sql (perguntas 8 e 10): um item é considerado anomalia
-- quando seu valor unitário excede a média do produto em mais de 2
-- desvios-padrão (produtos com menos de 5 ocorrências são excluídos, por
-- desvio-padrão de amostra pequena não ser confiável).
--
-- Por que uma VIEW, e não recalcular isso em DAX no Power BI: a regra de
-- negócio (o que conta como "anomalia") já está definida e testada aqui, em
-- SQL. Reimplementar a mesma fórmula em DAX criaria duas versões da mesma
-- lógica em lugares diferentes -- se o critério mudar um dia (ex.: de 2
-- para 3 desvios-padrão), seria fácil esquecer de atualizar um dos dois,
-- e os dois lados divergirem silenciosamente. Com a view, o Power BI
-- (ou qualquer outra ferramenta) só CONSOME um resultado já pronto -- uma
-- única fonte de verdade para a regra.
--
-- Uso no Power BI: importar esta view como uma tabela normal (aparece na
-- lista de tabelas do Postgres, junto com as 7 do esquema estrela). Não
-- precisa de nenhuma medida DAX adicional para identificar as anomalias --
-- a tabela já vem filtrada e ordenada.
-- ============================================================================

CREATE OR REPLACE VIEW vw_anomalias_preco AS
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
    ep.media                                                    AS preco_medio_produto,
    ROUND(((fi.valor_unitario_item - ep.media) / NULLIF(ep.desvio_padrao, 0))::numeric, 2) AS desvios_acima_da_media
FROM fato_item_licitacao fi
JOIN estatisticas_produto ep ON fi.sk_produto = ep.sk_produto
JOIN dim_fornecedor df ON fi.sk_fornecedor = df.sk_fornecedor
JOIN dim_produto dp ON fi.sk_produto = dp.sk_produto
WHERE fi.valor_unitario_item > ep.media + 2 * ep.desvio_padrao
ORDER BY desvios_acima_da_media DESC;