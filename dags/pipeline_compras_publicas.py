"""
DAG do pipeline DataGov Analytics.

Orquestra as etapas do pipeline na ordem: ingestão (bronze) -> tratamento
(silver) -> modelagem (gold) -> testes automatizados (portão de qualidade)
-> carga no PostgreSQL.

Por que os testes ficam DEPOIS da modelagem e ANTES da carga: são testes
unitários das funções de transformação (com dados sintéticos, não os dados
reais gerados no run) -- não dependem da ordem em relação a bronze/silver/
gold. Colocá-los como portão antes da carga é uma decisão deliberada: se um
teste falhar (por exemplo, alguém alterou uma regra de tratamento e quebrou
uma regra de qualidade sem perceber), a task de carga nunca roda, e dados
potencialmente errados não chegam ao data warehouse.

Por que schedule=None (execução manual): a etapa de ingestão ainda depende
de um download manual dos CSVs (ver README, seção 3 -- a API autenticada
que permitiria automação completa está bloqueada). Agendar uma execução
diária automática não faria sentido enquanto essa dependência manual
existir. Ver seção 22 do desafio original (carga incremental) para a
estratégia de evolução futura.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

DIRETORIO_PROJETO = "/opt/airflow/project"

argumentos_padrao = {
    "owner": "datagov-analytics",
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
    "email_on_failure": False,
}

with DAG(
    dag_id="pipeline_compras_publicas",
    description="Ingestão -> Silver -> Gold -> Testes -> Carga no PostgreSQL",
    default_args=argumentos_padrao,
    schedule=None,  # execução manual -- ver docstring acima
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["datagov", "compras-publicas"],
) as dag:

    tarefa_ingestao = BashOperator(
        task_id="ingestao_bronze",
        bash_command=f"cd {DIRETORIO_PROJETO} && python ingestao_bronze.py",
    )

    tarefa_silver = BashOperator(
        task_id="transformar_silver",
        bash_command=f"cd {DIRETORIO_PROJETO} && python transformar_silver.py",
    )

    tarefa_gold = BashOperator(
        task_id="transformar_gold",
        bash_command=f"cd {DIRETORIO_PROJETO} && python transformar_gold.py",
    )

    tarefa_testes = BashOperator(
        task_id="testes_qualidade",
        bash_command=f"cd {DIRETORIO_PROJETO} && pytest tests/ -v",
    )

    tarefa_carga = BashOperator(
        task_id="carregar_postgres",
        bash_command=f"cd {DIRETORIO_PROJETO} && python carregar_postgres.py",
    )

    tarefa_ingestao >> tarefa_silver >> tarefa_gold >> tarefa_testes >> tarefa_carga