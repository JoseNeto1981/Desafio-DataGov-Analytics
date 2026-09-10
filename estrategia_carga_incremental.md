# Estratégia de Carga Incremental

> Entrega do desafio adicional (seção 22 do desafio original): definir uma
> estratégia de carga incremental (processar diariamente só o que é novo
> ou mudou, sem reprocessar todo o histórico) e explicar como garantir a
> consistência dos dados caso o pipeline falhe no meio da execução.
>
> Este documento descreve a estratégia **proposta**. A implementação atual
> do pipeline (ver README) faz reprocessamento completo em cada execução —
> uma decisão consciente para esta fase do projeto, explicada na seção
> final deste documento. O objetivo aqui é mostrar que a estratégia foi
> pensada e seria viável de implementar, não fingir que já está em produção.

---

## 1. Por que o pipeline atual não é incremental, hoje

| Etapa | Comportamento atual | Por que isso impede incrementalidade |
|---|---|---|
| Ingestão (bronze) | Processa cada arquivo baixado manualmente, mas o download em si é mensal e manual — não há como filtrar "só o que mudou desde ontem" numa fonte que só publica lotes mensais | Sem uma fonte com granularidade diária (API com filtro de data), "diário" não tem o que buscar de novo todo dia |
| Tratamento (silver) | Lê **todos** os arquivos da bronze e sobrescreve os parquet inteiros a cada execução | Reprocessa histórico completo mesmo quando só 1 dia de dado é novo |
| Modelagem (gold) | Gera chaves substitutas sequenciais (`range(1, N+1)`) do zero, a cada execução | Se só dados novos fossem adicionados, as chaves de **tudo** mudariam — quebra referências já gravadas no banco |
| Carga (Postgres) | `TRUNCATE` + `COPY` completo | Apaga e recarrega a tabela inteira, mesmo pra adicionar poucas linhas novas |

Essas quatro coisas precisam mudar juntas para uma versão incremental de
verdade funcionar — não é uma mudança isolada em um único lugar.

---

## 2. Estratégia proposta, camada por camada

### 2.1. Pré-requisito: uma fonte com granularidade diária

A estratégia abaixo pressupõe a API do Portal da Transparência com
autenticação (`api.portaldatransparencia.gov.br`), que já foi explorada
neste projeto (ver README, seção 3) e permite filtrar por `dataInicial`/
`dataFinal`. Sem uma fonte que aceite filtro de data, "carga incremental
diária" não tem o que buscar — o CSV em lote mensal usado hoje não
permite pedir "só o dia de ontem".

### 2.2. Ingestão (bronze): watermark por período

Manter uma **tabela de controle** (`controle_execucao`, no próprio
Postgres ou um arquivo de estado simples) registrando o último período
(dia) processado com sucesso. Cada execução diária:

1. Lê o último `data_processada` da tabela de controle.
2. Busca na API só o intervalo entre esse valor e "ontem" (a execução de
   hoje processa os dados até ontem, para trabalhar com um dia já
   fechado/estável na fonte).
3. Ao final, com sucesso, atualiza `data_processada` para o novo valor.

Isso já existe parcialmente no projeto: a estrutura de partição
`bronze/<dataset>/ano=AAAA/mes=MM/` poderia evoluir para incluir
`dia=DD/`, e o manifesto de ingestão (`_manifest_*.json`, já existente)
serve de registro de "isso já foi processado" — só falta o controle de
qual período buscar da fonte.

### 2.3. Tratamento (silver): merge em vez de sobrescrita

Em vez de ler toda a bronze e sobrescrever o parquet da silver:

1. Processar só as partições `dia=DD/` novas (identificadas pelo
   controle acima).
2. Aplicar as mesmas regras de tratamento já existentes (`tratar_*`) —
   essas funções não mudam, só passam a operar num lote menor.
3. Fazer **merge** com a silver existente por chave natural (`Número
   Licitação` + `Código UG` + `Código Modalidade Compra` [+ `Código Item
   Compra`, para itens]) — registros com a mesma chave natural são
   atualizados (o caso de uma licitação que mudou de status, por
   exemplo); chaves novas são inseridas.

### 2.4. Modelagem (gold): chaves substitutas estáveis

Este é o ponto mais delicado. A solução: mover a geração de chave
substituta para um mecanismo **buscar-ou-criar** (upsert), em vez de
recriar do zero:

- Cada dimensão passa a ter uma tabela/arquivo de **mapeamento
  persistente** entre chave natural (ex.: `codigo_fornecedor`) e chave
  substituta (`sk_fornecedor`), que só **cresce** — nunca é recriada.
- Ao processar um novo lote: para cada chave natural, verifica se já
  existe no mapeamento. Se sim, reaproveita a mesma `sk_*`. Se não,
  cria uma nova (próximo número disponível) e adiciona ao mapeamento.
- Na prática, a forma mais simples de implementar isso é deixar o
  próprio Postgres gerar essas chaves via `SERIAL`/`BIGSERIAL` com
  `INSERT ... ON CONFLICT (chave_natural) DO UPDATE ... RETURNING sk_*`
  — o banco já resolve o "buscar-ou-criar" atomicamente, sem precisar
  reimplementar isso em Python.
- Tabelas fato passam a receber só os registros do novo período
  (`INSERT`, não substituição), usando as chaves obtidas no passo acima.

### 2.5. Carga (Postgres): UPSERT em vez de TRUNCATE

- **Dimensões:** `INSERT ... ON CONFLICT (chave_natural) DO UPDATE SET
  ...` — atualiza atributos se a linha já existe (ex.: nome de um
  fornecedor foi corrigido na fonte), insere se é nova.
- **Fatos:** `INSERT` apenas dos registros do período novo. Para o caso
  de a fonte **corrigir retroativamente** um período já carregado
  (aconteceu de verdade neste projeto — abril apareceu com volume
  parcial, sujeito a complementação depois), a carga desse período
  específico usa `DELETE WHERE periodo = X` seguido de `INSERT` — apaga
  e recarrega só a partição daquele período, não a tabela inteira.

### 2.6. Orquestração (Airflow): `schedule_interval` diário + parâmetro de execução

A DAG já criada (`dags/pipeline_compras_publicas.py`) tem hoje
`schedule=None` (execução manual), justamente porque a ingestão depende
de download manual. Com uma fonte de API diária, mudaria para
`schedule="@daily"`, e cada task passaria a receber a data de execução do
Airflow (`data_interval_start`/`data_interval_end`) como parâmetro,
processando exclusivamente aquele dia — o mesmo mecanismo de
"backfill" do Airflow permite reprocessar manualmente um dia específico
do passado, se necessário, sem tocar nos demais.

---

## 3. Garantindo consistência se o pipeline falhar no meio da execução

Quatro mecanismos, combinados:

### 3.1. Escrita atômica de arquivos

Ao gravar qualquer arquivo (bronze, silver, gold), escrever primeiro num
caminho temporário e só **renomear** para o nome final depois que a
escrita terminar por completo (`os.replace(tmp, destino)` — uma operação
atômica no sistema de arquivos). Se o processo cair no meio da escrita,
o arquivo temporário incompleto fica órfão, mas o arquivo "oficial"
anterior nunca é corrompido nem fica parcialmente escrito.

### 3.2. Transações no Postgres

A carga de um período no banco (dimensões + fatos daquele dia) deve
acontecer dentro de uma única transação (`BEGIN` ... `COMMIT`). Se
qualquer etapa falhar no meio, o `ROLLBACK` automático desfaz tudo o que
já tinha sido escrito nessa transação — o banco nunca fica com "meio
dia" de dados carregados.

### 3.3. Idempotência ponta a ponta

Cada etapa deve poder ser **re-executada em cima do mesmo período sem
duplicar nada**:
- Ingestão: manifesto já registra checksum — reprocessar o mesmo arquivo
  simplesmente sobrescreve o mesmo destino, sem duplicar.
- Silver/Gold: merge por chave natural (seção 2.3/2.4) já é idempotente
  por definição — processar o mesmo dia duas vezes não cria linhas
  duplicadas, só atualiza as mesmas.
- Carga: `ON CONFLICT DO UPDATE` (dimensões) e `DELETE`+`INSERT` por
  período (fatos) também são idempotentes.

Isso é o que permite ao Airflow simplesmente **tentar de novo** (retry)
uma task que falhou por causa transitória (rede, timeout), sem risco de
duplicar dados — mecanismo que já existe na DAG atual e foi validado na
prática durante o desenvolvimento (ver README, seção 11).

### 3.4. Tabela de controle de execução (log de execução)

Uma tabela simples (`controle_execucao`) registrando, por período
processado: status (`iniciado`, `sucesso`, `falha`), timestamp de início
e fim, e quantidade de linhas afetadas. Isso permite:
- Saber exatamente até onde o pipeline avançou com sucesso, sem precisar
  inspecionar logs manualmente.
- Um período marcado como `falha` pode ser identificado automaticamente
  e reprocessado (pelo próprio Airflow, via retry, ou manualmente),
  sem arriscar reprocessar períodos que já deram certo.
- Servir de base para alertas (ex.: notificar se um período ficar
  `iniciado` por muito tempo sem virar `sucesso` ou `falha` — sinal de
  processo travado).

### 3.5. Dependência entre tasks (já implementado)

A ordem `ingestao_bronze >> transformar_silver >> transformar_gold >>
testes_qualidade >> carregar_postgres`, já existente na DAG, garante que
uma falha numa etapa impede as seguintes de rodar — dados incompletos ou
malformados nunca avançam para a próxima camada, muito menos chegam ao
banco de produção.

---

## 4. Por que isso não foi implementado no código desta versão do projeto

Decisão consciente, não limitação técnica: reestruturar `transformar_gold.py`
e `carregar_postgres.py` para o padrão incremental (chaves estáveis via
banco, UPSERT em vez de TRUNCATE) é um esforço real, e o benefício prático
nesta fase do projeto é baixo — a fonte de dados atual é atualizada
manualmente, em lotes mensais, não diariamente, então não há "dados novos
todo dia" para processar de forma incremental de verdade ainda. A
estratégia acima fica documentada e pronta para ser implementada quando
(1) a API autenticada do Portal da Transparência for destravada (ver
README, seção 16, Limitações) e (2) o volume de dados justificar o custo
de reprocessar o histórico completo a cada execução.