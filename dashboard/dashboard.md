# Dashboard — DataGov Analytics

> O arquivo `datagov.pbix` não é visualizável direto no GitHub (é um
> binário do Power BI). Em vez de screenshots individuais por página, o
> dashboard foi exportado como um único PDF (**[datagov.pdf](datagov.pdf)**),
> que o próprio GitHub já renderiza inline no navegador — sem precisar
> abrir nada.
>
> Para editar de verdade: baixe `datagov.pbix`, tenha o Postgres do
> projeto rodando (`docker compose up -d`), e abra no Power BI Desktop.
> Se pedir para atualizar a conexão, use as credenciais do seu `.env`.

---

## Página 1 — Visão Geral

**Conteúdo:** 5 cartões de KPI (Valor Total de Compras, Preço Médio
Unitário, Quantidade de Produtos, Quantidade de Fornecedores, Quantidade
de Licitações) + gráfico de linha com a evolução diária do valor de
compras ao longo dos 4 meses (jan-abr/2024).

**Principais números:**
- Valor total: **R$ 19,92 bilhões** (bate exatamente com a soma dos 4
  meses calculada via SQL: 6,01 + 5,41 + 7,47 + 1,03 bi)
- Preço médio unitário: **R$ 35.000,00**
- 7 mil produtos distintos, 11 mil fornecedores, 7 mil licitações

**Achado visual:** o gráfico de linha deixa clara a queda abrupta de
abril/2024 em relação aos 3 meses anteriores — consistente com a hipótese
de dados parciais nesse mês, documentada na seção de Limitações do README.

---

## Página 2 — Distribuição Geográfica

**Conteúdo:** gráfico de barras horizontais com o valor total de compras
por UF, ordenado do maior para o menor.

**Achado:** Distrito Federal lidera com folga (mais que o dobro do
segundo colocado, Rio de Janeiro) — esperado, dado que concentra sedes de
ministérios e órgãos federais.

---

## Página 3 — Fornecedores e Produtos

**Conteúdo:** dois gráficos de barras horizontais, Top 10 cada — um por
fornecedor, outro por produto/serviço, ambos por valor total de compras.

**Achados:**
- Fornecedor líder: **LCM Construção e Comércio S.A** (R$ 616,5 milhões)
- Produto líder: **Conservação/Manutenção/Restauração de Rodovia**
  (R$ 1,34 bilhão)

---

## Página 4 — Análise de Preços

**Conteúdo:** tabela navegável com produto, fornecedor e valor unitário
individual de cada compra.

**Uso:** permite consultar o preço pago em qualquer item específico do
conjunto de dados — útil para checagem pontual, além dos rankings
agregados das outras páginas.

---

## Página 5 — Anomalias de Preço

**Conteúdo:** tabela alimentada pela view `vw_anomalias_preco` do
PostgreSQL (não por uma medida DAX — ver decisão técnica abaixo), listando
itens cujo valor unitário excede a média do mesmo produto em mais de 2
desvios-padrão, ordenada do caso mais extremo para o menos extremo.

**Achado principal:** **HYDROSTEC Tecnologia e Equipamentos** vendeu uma
"Conexão Hidráulica" por R$ 2.175.000,00, quando a média desse item é
R$ 1.090,73 — **44,96 desvios-padrão** acima da média, o caso mais
extremo do conjunto de dados. Características mais consistentes com erro
de digitação na fonte (dígitos extras no valor) do que superfaturamento
real, mas sinalizado para investigação humana.

### Decisão técnica: por que uma view SQL, e não uma medida DAX

A regra de anomalia (2 desvios-padrão, mínimo 5 ocorrências por produto)
já estava definida e testada em `perguntas_negocio.sql` (perguntas 8 e
10). Reimplementar a mesma fórmula em DAX criaria duas versões da mesma
lógica de negócio, em lugares diferentes — risco real de divergência se o
critério for ajustado um dia e só um dos dois lados for atualizado. A
view `vw_anomalias_preco` (ver `vw_anomalias_preco.sql`) resolve isso: a
regra vive em um único lugar (o banco), e o Power BI só consome o
resultado já calculado, sem duplicar código.

### Nota de construção: exportação em PDF e largura de coluna

A primeira exportação para PDF cortou as colunas numéricas das tabelas
das páginas 4 e 5 (ficaram fora da largura da página). Corrigido
estreitando manualmente as colunas de texto e reduzindo o tamanho da
fonte da tabela antes de exportar de novo — um detalhe prático de quem
já tentou gerar documentação visual de um dashboard com tabelas largas.

---

## Resumo técnico

| Item | Detalhe |
|---|---|
| Fonte de dados | PostgreSQL (`datagov_dw`), modo de conexão: Importar |
| Tabelas usadas | 5 dimensões + 2 fatos (esquema estrela) + `vw_anomalias_preco` |
| Medidas DAX | 6, todas na tabela `Medidas` |
| Páginas | 5, organizadas por tema |
| Exportação | PDF único (`datagov.pdf`), todas as páginas |