# DataGov Analytics — Plataforma de Dados de Compras Governamentais

> Projeto desenvolvido como parte de um desafio técnico de Engenharia de
> Dados. Constrói um pipeline de ponta a ponta sobre dados públicos de
> licitações do Governo Federal brasileiro: ingestão → bronze → silver →
> gold → data warehouse → análise.
>
> **Status:** em desenvolvimento. Este README é um documento vivo, atualizado
> conforme cada etapa do pipeline é construída.

---

## 1. Descrição do problema

Organizações que vendem para o setor público precisam analisar padrões de
compras governamentais (quem compra, o quê, por quanto, e como isso muda ao
longo do tempo), mas esses dados estão espalhados em fontes públicas com
formatos inconsistentes e não estruturados para análise direta.

## 2. Objetivo

Construir uma plataforma de dados capaz de: obter dados de fontes públicas,
armazená-los brutos, tratá-los e padronizá-los, validar sua qualidade,
disponibilizá-los em um modelo analítico, e responder perguntas de negócio
sobre compras públicas.

## 3. Fonte dos dados

### Decisão final: Portal da Transparência do Governo Federal

**Tentativas anteriores e por que foram descartadas** (documentado aqui de
propósito — faz parte do processo real de engenharia, não só o resultado
final):

1. **PNCP (Portal Nacional de Contratações Públicas)** — fonte mais
   completa (cobre todos os entes federativos), API REST sem necessidade de
   chave. Descartada como fonte principal após instabilidade confirmada e
   persistente durante o desenvolvimento (timeouts e erros 503 repetidos ao
   longo de várias horas, em dias diferentes). Relatos públicos da
   Transparência Brasil confirmam que essa instabilidade é estrutural, não
   pontual. Pode ser reavaliada como fonte secundária no futuro.
2. **API do Portal da Transparência com autenticação** — endpoint REST
   (`api.portaldatransparencia.gov.br`) com paginação, mais alinhado ao
   requisito técnico do desafio. Bloqueada durante o desenvolvimento por
   exigir conta gov.br nível Prata/Ouro, e o fluxo de autenticação retornou
   erro genérico mesmo após a elevação de nível. Fica como diferencial a
   destravar — a ingestão automatizada assume essa API quando disponível.

**Fonte usada agora:** download manual dos arquivos CSV em lote
(`portaldatransparencia.gov.br/download-de-dados/licitacoes`), sem
necessidade de autenticação. Gera 4 arquivos por período: `Licitação`,
`ItemLicitação`, `ParticipantesLicitação`, `EmpenhosRelacionados`.

**Período coberto:** os 4 meses disponíveis de 2024 (janeiro a abril — é o
ano mais recente disponibilizado nesse formato pelo portal).

## 4. Arquitetura

```text
Download manual (CSV)  →  dados_brutos/
                              ↓
                    ingestao_bronze.py
                              ↓
        bronze/<dataset>/ano=AAAA/mes=MM/*.csv  (+ manifesto JSON)
                              ↓
                    transformar_silver.py
                              ↓
              silver/<dataset>.parquet  (+ relatório de qualidade)
                              ↓
                    transformar_gold.py
                              ↓
        gold/dim_*.parquet + gold/fato_*.parquet  (esquema estrela)
                              ↓
                    carregar_postgres.py  (via COPY)
                              ↓
              PostgreSQL (Docker) — schema.sql aplicado
                              ↓
          perguntas_negocio.sql  →  [Dashboard — a construir]
```

## 5. Tecnologias utilizadas

| Tecnologia | Uso | Status |
|---|---|---|
| Python 3.14 | Scripts de ingestão e tratamento | ✅ em uso |
| pandas | Leitura, transformação e validação de dados | ✅ em uso |
| pyarrow | Escrita em formato Parquet (camada silver/gold) | ✅ em uso |
| requests | Chamadas HTTP (exploração de API) | ✅ em uso |
| PostgreSQL | Data warehouse analítico | ✅ em uso |
| Docker / Docker Compose | Ambiente reproduzível do banco | ✅ em uso |
| psycopg (v3) | Driver de conexão + carga via COPY | ✅ em uso |
| Apache Airflow | Orquestração do pipeline | ⏳ a construir |
| dbt | Modelos de transformação analítica | ⏳ a avaliar |
| Pytest | Testes automatizados | ⏳ a construir |
| Power BI | Dashboard analítico | ⏳ a construir |

## 6. Instruções de instalação

```bash
git clone <url-do-repositorio>
cd desafio-datagov
python -m venv venv
source venv/Scripts/activate   # Windows (Git Bash)
# ou: source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
cp .env.example .env           # e preencha as variáveis do Postgres
```

## 7. Instruções de execução

```bash
# 1. Baixe manualmente os CSVs de licitações em
#    portaldatransparencia.gov.br/download-de-dados/licitacoes
#    e coloque-os na pasta dados_brutos/ (mantendo o nome original,
#    padrão AAAAMM_NomeDataset.csv)

# 2. Rode a ingestão para a camada bronze
python ingestao_bronze.py

# 3. Rode o tratamento para a camada silver
python transformar_silver.py

# 4. Rode a modelagem dimensional para a camada gold
python transformar_gold.py

# 5. Suba o PostgreSQL via Docker (schema.sql roda automaticamente na
#    primeira inicialização do container)
docker compose up -d

# 6. Carregue a camada gold no banco
python carregar_postgres.py

# 7. Rode as perguntas de negócio (perguntas_negocio.sql) em qualquer
#    cliente SQL (DBeaver, psql, extensão do VS Code, etc.), conectando com
#    as credenciais do seu .env
```

## 8. Estrutura do projeto

```text
.
├── dados_brutos/              # CSVs baixados manualmente (não versionado)
├── bronze/                    # Dados brutos organizados e particionados (não versionado)
├── silver/                    # Dados tratados em Parquet (não versionado)
├── gold/                      # Esquema estrela em Parquet (não versionado)
├── ingestao_bronze.py         # Ingestão: dados_brutos/ -> bronze/
├── transformar_silver.py      # Tratamento: bronze/ -> silver/
├── transformar_gold.py        # Modelagem dimensional: silver/ -> gold/ (fato/dimensões)
├── docker-compose.yml         # Sobe o PostgreSQL
├── schema.sql                 # DDL do data warehouse (tabelas, PKs, FKs, índices)
├── carregar_postgres.py       # Carga da camada gold -> PostgreSQL (via COPY)
├── perguntas_negocio.sql      # As 10 perguntas de negócio do desafio, em SQL
├── explorar_pncp.py           # Script exploratório da API do PNCP (descontinuada como fonte principal)
├── explorar_portal_transparencia.py  # Script exploratório da API do Portal da Transparência (bloqueada por autenticação)
├── requirements.txt
├── .env.example                # Modelo de variáveis de ambiente (copiar para .env)
├── .gitignore
└── README.md
```

## 9. Modelo de dados

Esquema estrela com 5 dimensões e 2 tabelas fato, construído a partir da
camada silver (`transformar_gold.py`) e materializado no PostgreSQL via
`schema.sql` + `carregar_postgres.py`.

### Grão das tabelas fato

- **`fato_item_licitacao`**: 1 linha = 1 item vencido dentro de 1 licitação.
  É o grão mais fino disponível com valor monetário associado.
- **`fato_participacao`**: 1 linha = 1 fornecedor disputando 1 item (tenha
  vencido ou não). Necessária porque perguntas sobre concorrência (quantos
  disputaram, em quais estados há mais fornecedores atuando) precisam de
  quem participou, não só de quem venceu.

### Dimensões

| Dimensão | Grão | Por que existe |
|---|---|---|
| `dim_tempo` | 1 data | Evolução temporal do volume de compras (pergunta 4) |
| `dim_orgao` | 1 Unidade Gestora | Estado, órgão, município (perguntas 3, 6, 9) |
| `dim_fornecedor` | 1 fornecedor (união de vencedores + participantes) | Ranking e análise de preços por fornecedor (perguntas 2, 8) |
| `dim_produto` | 1 descrição de item distinta (união de itens + participantes) | Ranking de produtos/serviços (perguntas 1, 7) |
| `dim_licitacao` | 1 licitação | Contexto do processo (modalidade, situação, objeto) |

### Decisão de modelagem importante: chave composta da licitação

A princípio, `Número Licitação` + `Código UG` parecia suficiente para
identificar uma licitação de forma única. Ao validar os dados, encontramos
**13 casos** em que essa combinação se repete com `Modalidade Compra`
diferente (ex.: o número `000142023` existe tanto como Pregão quanto como
Dispensa de Licitação, na mesma UG). A chave de negócio correta é
`Número Licitação` + `Código UG` + `Código Modalidade Compra` — sem isso,
itens de uma licitação seriam vinculados por engano aos atributos da outra.

### Decisão de modelagem: união de fontes para `dim_fornecedor` e `dim_produto`

Nem todo item que aparece na tabela de Participantes tem um registro
espelhado idêntico na tabela de Itens (31 descrições de produto e alguns
fornecedores só existem em um dos dois). Por isso, as duas dimensões são
construídas como união das duas fontes — evita que `fato_participacao`
fique com chaves estrangeiras nulas por um item que só foi "visto" do lado
da disputa, não do lado do vencedor.

## 10. Decisões técnicas e regras de tratamento

Todas as regras abaixo foram definidas depois de inspecionar os dados reais
(não escritas antecipadamente "no escuro"). Números referem-se à amostra de
janeiro/2024, usada durante o desenvolvimento — o relatório de qualidade
gerado em `silver/_relatorio_qualidade.json` traz os números reais para o
conjunto completo de dados.

| Regra | Achado real | Decisão |
|---|---|---|
| Encoding do CSV | Arquivos vêm em ISO-8859-1 (Latin-1), não UTF-8 | Encoding explícito na leitura |
| Separador do CSV | `;`, não `,` | Separador explícito na leitura |
| Números decimais | Formato brasileiro (`1234,56`) | Convertido para `float` |
| UF inválida | 34 registros com `UF = "-3"` | Campo zerado, linha mantida (resto do registro é útil) |
| Item sem código de origem | 90 registros sem `Código Item Compra` | Chave substituta gerada (`SEM_CODIGO_N`), sinalizada em coluna própria |
| Código de participante inválido | 216 registros com valores como `-11` | Campo zerado, linha mantida |
| Fornecedor estrangeiro | Códigos no padrão `ESTRANG...` | **Não tratado como erro** — categoria legítima (sem CNPJ/CPF), sinalizada em coluna própria |
| Duplicados exatos | 6 em Itens, 192 em Participantes | Removidos |
| Valores negativos | 0 encontrados na amostra | Regra de remoção implementada preventivamente |
| `EmpenhosRelacionados` vazio | 0 registros em janeiro/2024 | Mantido na pipeline com schema vazio (não é falha — período realmente não teve empenho vinculado) |
| Chave estrangeira nula em COPY | Colunas `sk_*` com nulos viravam `5125.0` em vez de `5125` no CSV gerado pelo pandas, rejeitado pelo Postgres | Conversão explícita para o tipo `Int64` (inteiro anulável) antes do `COPY` |

### Otimização de carga: INSERT em lote vs. COPY

A primeira versão de `carregar_postgres.py` usava `pandas.to_sql()` (INSERTs
em lote). Para o volume completo de 4 meses (~213 mil linhas de fato), isso
levava mais de 13 minutos. Investigação mostrou que o gargalo era o método
de carga (uma "viagem" de rede/confirmação por lote), não o volume de dados
em si nem o hardware da máquina — carregar as dimensões (bem menores) levava
segundos, então a demora não era proporcional ao poder de processamento.
Reescrito para usar o comando nativo `COPY` do Postgres (via `psycopg`),
reduzindo o tempo total de carga para poucos segundos.

## 11. Regras de Data Quality

*A expandir na etapa de testes automatizados (Pytest).* Validações já
implementadas:
- **Ingestão (bronze):** verificação de colunas obrigatórias por dataset,
  arquivo rejeitado se schema divergir do esperado.
- **Tratamento (silver):** relatório de qualidade com contagem de nulos
  corrigidos, duplicados removidos, valores negativos e inconsistências de
  identificador, por dataset (`silver/_relatorio_qualidade.json`).
- **Análise (gold/SQL):** detecção estatística de anomalias de preço
  (perguntas 8 e 10 — ver critério abaixo).

## 12. Perguntas de negócio

Todas as queries estão em `perguntas_negocio.sql`. Resultados abaixo com o
conjunto completo de dados (4 meses, janeiro a abril de 2024).

**1. Top 10 produtos/serviços por valor total:**
Lidera "Conservação/Manutenção/Restauração de Rodovia", com R$ 1,34 bilhão
em 26 itens — seguido de "Obras Civis de Pavimentação Asfáltica" (R$ 850,8
milhões) e "Serviço Engenharia" (R$ 778,0 milhões, mas com 1.985 itens,
maior pulverização).

**2. Top 10 fornecedores por volume financeiro:**
LCM Construção e Comércio S.A lidera com R$ 616,5 milhões, seguida de V.F.
Gomes Construtora (R$ 453,7 mi) e HPE Automotores do Brasil (R$ 453,5 mi).

**3. Estado com maior volume financeiro:**
Distrito Federal, com R$ 7,43 bilhões — mais que o dobro do segundo
colocado (Rio de Janeiro, R$ 3,03 bi). Esperado, dado que concentra sedes
de ministérios e órgãos federais.

**4. Evolução temporal:**

| Mês | Valor total | Qtd. itens |
|---|---|---|
| Janeiro | R$ 6,01 bi | 53.237 |
| Fevereiro | R$ 5,41 bi | 49.824 |
| Março | R$ 7,47 bi | 55.748 |
| Abril | R$ 1,03 bi | 16.852 |

Queda acentuada em abril (valor e quantidade de itens caem juntos, na
mesma proporção aproximada) — indício de que abril pode ter dados parciais
na fonte, não necessariamente uma queda real de compras. Investigar se
mais dados de abril foram publicados depois da extração.

**5. Preço médio dos produtos/serviços:**
R$ 35.002,08 por item (média geral). Por produto individual, ver a query
completa — produtos com poucas ocorrências têm médias pouco confiáveis
estatisticamente, por isso a query filtra produtos com 5+ compras.

**6. Órgãos com maior volume de compras:**
Companhia de Desenvolvimento dos Vales do São Francisco (R$ 1,51 bi),
Polícia Rodoviária Federal (R$ 1,38 bi) e Ministério da Saúde (R$ 1,08 bi)
lideram — todos vinculados a órgãos sediados no DF.

**7. Categorias com maior movimentação financeira:**
*Limitação documentada*: a fonte não traz um catálogo de categorias
(tipo CATMAT/CATSER) — apenas descrição textual do item. Resultado
equivalente à pergunta 1.

**8. Fornecedores com preços significativamente acima da média:**
Critério: valor unitário acima de 2 desvios-padrão da média do produto
(produtos com 5+ ocorrências). O caso mais extremo: HYDROSTEC Tecnologia e
Equipamentos vendendo uma "Conexão Hidráulica" por R$ 2.175.000,00, quando
a média desse item é R$ 1.090,73 (~44,96 desvios-padrão acima — ver
pergunta 10 para discussão).

**9. Estados com maior quantidade de fornecedores distintos:**
RJ lidera com 6.001 fornecedores distintos disputando licitações,
seguido de MG (3.084) e DF (2.940) — RJ ultrapassa até o DF nesse
critério, ao contrário do que se veria olhando só valor financeiro (Q3).

**10. Possíveis anomalias de preço:**
O mesmo caso da pergunta 8 (HYDROSTEC / Conexão Hidráulica, ~45
desvios-padrão) é o mais extremo do conjunto. Tem características mais
consistentes com **erro de digitação na fonte** (ex.: dígitos extras no
valor) do que superfaturamento real — mas fica sinalizado para
investigação humana, que é justamente o objetivo de uma regra de anomalia:
apontar candidatos, não emitir veredito automático.

## 13. Resultados obtidos

O pipeline processa com sucesso 4 meses de dados de licitações federais
(~215 mil linhas nas camadas silver/gold, ~213 mil linhas de fato no data
warehouse), evidenciando padrões coerentes com o esperado (DF concentrando
volume financeiro por sediar órgãos federais, RJ liderando em diversidade
de fornecedores) e identificando pelo menos um caso concreto de possível
erro de digitação nos dados de origem através da regra estatística de
anomalia — validando que o pipeline não só processa os dados, mas gera
achados acionáveis.

## 14. Limitações

- API do PNCP apresentou instabilidade persistente durante o
  desenvolvimento — não utilizada como fonte principal (ver seção 3).
- API do Portal da Transparência com autenticação não pôde ser
  destravada durante o desenvolvimento (erro genérico de autenticação
  mesmo após elevação de nível da conta gov.br) — ingestão atual depende
  de download manual dos arquivos CSV.
- Dados limitados aos 4 meses disponíveis de 2024 no formato de download em
  lote usado. Abril, em particular, parece ter volume de dados parcial
  (queda desproporcional de valor e quantidade de itens — ver pergunta 4).
- `EmpenhosRelacionados` sem dados no período analisado — execução
  financeira (empenhado x pago) não pôde ser cruzada com as licitações.
- Sem catálogo de categorias (tipo CATMAT/CATSER) na fonte usada — a
  pergunta de negócio sobre "categorias" foi respondida no nível de produto.
- Detecção de anomalias de preço é estatística (desvio-padrão), não
  semântica — não distingue erro de digitação de superfaturamento real;
  ambos requerem investigação humana adicional.

## 15. Possíveis melhorias futuras

- Destravar a API do Portal da Transparência e automatizar a ingestão
  (elimina a etapa manual de download).
- Reavaliar o PNCP como fonte secundária/complementar quando estabilizar.
- Estender a cobertura temporal além dos 4 meses atuais.
- Implementar carga incremental diária (ver desafio adicional).
- Cruzar com um catálogo de categorias (CATMAT/CATSER) para responder a
  pergunta 7 de forma mais fiel à intenção original.
- Testes automatizados (Pytest) cobrindo ingestão, tratamento e regras de
  qualidade.
- Orquestração via Apache Airflow, substituindo a execução manual dos
  scripts em sequência.
- Dashboard (Power BI ou equivalente) consumindo as queries de
  `perguntas_negocio.sql`.