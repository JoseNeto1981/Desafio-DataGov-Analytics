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
                         [gold — a construir]
                              ↓
                  [PostgreSQL / DW — a construir]
                              ↓
                    [SQL + Dashboard — a construir]
```

## 5. Tecnologias utilizadas

| Tecnologia | Uso | Status |
|---|---|---|
| Python 3.14 | Scripts de ingestão e tratamento | ✅ em uso |
| pandas | Leitura, transformação e validação de dados | ✅ em uso |
| pyarrow | Escrita em formato Parquet (camada silver) | ✅ em uso |
| requests | Chamadas HTTP (exploração de API) | ✅ em uso |
| PostgreSQL | Data warehouse analítico | ⏳ a construir |
| Docker | Ambiente reproduzível | ⏳ a construir |
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
```

## 8. Estrutura do projeto

```text
.
├── dados_brutos/              # CSVs baixados manualmente (não versionado)
├── bronze/                    # Dados brutos organizados e particionados (não versionado)
├── silver/                    # Dados tratados em Parquet (não versionado)
├── ingestao_bronze.py         # Ingestão: dados_brutos/ -> bronze/
├── transformar_silver.py      # Tratamento: bronze/ -> silver/
├── explorar_pncp.py           # Script exploratório da API do PNCP (descontinuada como fonte principal)
├── explorar_portal_transparencia.py  # Script exploratório da API do Portal da Transparência (bloqueada por autenticação)
├── requirements.txt
├── .gitignore
└── README.md
```

## 9. Modelo de dados

*A construir — grão da tabela fato e modelo dimensional serão documentados
aqui na próxima etapa.*

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

## 11. Regras de Data Quality

*A expandir na etapa de testes automatizados (Pytest).* Validações já
implementadas na ingestão (bronze): verificação de colunas obrigatórias por
dataset, arquivo rejeitado se schema divergir do esperado.

## 12. Perguntas de negócio

*A responder após a construção da camada gold e do data warehouse.*

## 13. Resultados obtidos

*A preencher.*

## 14. Limitações

- API do PNCP apresentou instabilidade persistente durante o
  desenvolvimento — não utilizada como fonte principal (ver seção 3).
- API do Portal da Transparência com autenticação não pôde ser
  destravada durante o desenvolvimento (erro genérico de autenticação
  mesmo após elevação de nível da conta gov.br) — ingestão atual depende
  de download manual dos arquivos CSV.
- Dados limitados aos 4 meses disponíveis de 2024 no formato de download em
  lote usado.
- `EmpenhosRelacionados` sem dados no período analisado — execução
  financeira (empenhado x pago) não pôde ser cruzada com as licitações.

## 15. Possíveis melhorias futuras

- Destravar a API do Portal da Transparência e automatizar a ingestão
  (elimina a etapa manual de download).
- Reavaliar o PNCP como fonte secundária/complementar quando estabilizar.
- Estender a cobertura temporal além dos 4 meses atuais.
- Implementar carga incremental diária (ver desafio adicional).