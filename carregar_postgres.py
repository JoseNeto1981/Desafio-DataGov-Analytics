"""
Script de carga -> POSTGRESQL (Data Warehouse).

Lê os arquivos Parquet da camada gold e carrega no PostgreSQL, na ordem
correta: dimensões primeiro, tabelas fato depois (respeitando as chaves
estrangeiras definidas em schema.sql).

Usa o comando nativo COPY do Postgres (via psycopg) em vez de INSERTs em
lote. Diferença prática: com to_sql()/INSERT, cada lote de linhas é uma
ida-e-volta de rede + confirmação de escrita; com COPY, os dados trafegam
como um fluxo contínuo em um único comando. Para as ~683 mil linhas de
fato deste projeto, isso reduziu a carga de ~13 minutos para poucos
segundos -- o gargalo original era o método de carga, não o volume de
dados em si nem o hardware da máquina.

Cada execução TRUNCATE + COPY nas tabelas de destino -- ou seja, é segura
para reprocessamento: rodar de novo não duplica dados, apenas substitui o
conteúdo pela versão mais recente da camada gold.

Configuração via variáveis de ambiente (mesmas usadas pelo docker-compose.yml):
  POSTGRES_HOST     - padrão: localhost
  POSTGRES_PORT     - padrão: 5432
  POSTGRES_USER     - padrão: datagov
  POSTGRES_PASSWORD - padrão: datagov
  POSTGRES_DB       - padrão: datagov_dw
  GOLD_DIR          - padrão: gold
"""

import io
import logging
import os
import time
from pathlib import Path

import pandas as pd
import psycopg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("carregar_postgres")


def _carregar_dotenv_simples(caminho: Path = Path(".env")) -> None:
    if not caminho.exists():
        return
    for linha in caminho.read_text().splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip())


GOLD_DIR = Path(os.environ.get("GOLD_DIR", "gold"))

TABELAS_DIMENSAO = ["dim_tempo", "dim_orgao", "dim_fornecedor", "dim_produto", "dim_licitacao"]
TABELAS_FATO = ["fato_item_licitacao", "fato_participacao"]

# Colunas de data que precisam ser formatadas explicitamente como AAAA-MM-DD
# antes do COPY -- evita ambiguidade de formato entre o texto que o pandas
# gera por padrão (com horário embutido) e o tipo DATE do Postgres.
COLUNAS_DE_DATA = {"dim_tempo": ["data"]}


def _conectar():
    _carregar_dotenv_simples()
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        user=os.environ.get("POSTGRES_USER", "datagov"),
        password=os.environ.get("POSTGRES_PASSWORD", "datagov"),
        dbname=os.environ.get("POSTGRES_DB", "datagov_dw"),
    )


def truncar_tabelas(conexao, tabelas: list[str]) -> None:
    with conexao.cursor() as cursor:
        for tabela in tabelas:
            cursor.execute(f"TRUNCATE TABLE {tabela} RESTART IDENTITY CASCADE")
            logger.info("Tabela '%s' truncada.", tabela)
    conexao.commit()


def copiar_tabela(conexao, nome_tabela: str) -> int:
    caminho_parquet = GOLD_DIR / f"{nome_tabela}.parquet"
    if not caminho_parquet.exists():
        logger.warning("Arquivo '%s' não encontrado — tabela '%s' ficará vazia.", caminho_parquet, nome_tabela)
        return 0

    df = pd.read_parquet(caminho_parquet)

    # Colunas de chave estrangeira (prefixo sk_) que contenham algum valor
    # nulo são lidas pelo pandas como float64 (ex.: 5125.0 em vez de 5125),
    # porque o tipo inteiro "normal" do pandas não suporta nulos. O Postgres
    # rejeita "5125.0" numa coluna INTEGER. Convertendo para o tipo Int64
    # (inteiro anulável do pandas, com I maiúsculo) o COPY recebe o número
    # sem casa decimal quando existe, e vazio (NULL) quando não existe.
    # Achado real ao testar a carga de fato_participacao, que tem 24 linhas
    # com sk_fornecedor nulo (participantes com código inválido -- ver
    # decisão documentada na camada silver).
    for coluna in df.columns:
        if coluna.startswith("sk_") and pd.api.types.is_float_dtype(df[coluna]):
            df[coluna] = df[coluna].astype("Int64")

    for coluna in COLUNAS_DE_DATA.get(nome_tabela, []):
        df[coluna] = pd.to_datetime(df[coluna]).dt.strftime("%Y-%m-%d")

    buffer = io.StringIO()
    df.to_csv(buffer, index=False, header=False, na_rep="")
    buffer.seek(0)

    colunas = ", ".join(df.columns)
    comando_copy = f"COPY {nome_tabela} ({colunas}) FROM STDIN WITH (FORMAT csv, NULL '')"

    with conexao.cursor() as cursor:
        with cursor.copy(comando_copy) as copy:
            copy.write(buffer.read())
    conexao.commit()

    logger.info("Carregado '%s': %s linhas (via COPY).", nome_tabela, len(df))
    return len(df)


def main() -> None:
    try:
        conexao = _conectar()
        logger.info("Conexão com o PostgreSQL confirmada.")
    except Exception as erro:
        logger.error(
            "Não foi possível conectar ao PostgreSQL: %s. "
            "Confirme que o container está no ar (docker compose up -d) "
            "e que as variáveis de ambiente estão corretas.",
            erro,
        )
        return

    inicio = time.monotonic()

    logger.info("=" * 70)
    logger.info("Limpando tabelas (na ordem: fatos, depois dimensões)...")
    truncar_tabelas(conexao, list(reversed(TABELAS_FATO)) + list(reversed(TABELAS_DIMENSAO)))

    logger.info("=" * 70)
    logger.info("Carregando dimensões...")
    total_dimensoes = sum(copiar_tabela(conexao, tabela) for tabela in TABELAS_DIMENSAO)

    logger.info("=" * 70)
    logger.info("Carregando fatos...")
    total_fatos = sum(copiar_tabela(conexao, tabela) for tabela in TABELAS_FATO)

    conexao.close()
    duracao = time.monotonic() - inicio

    logger.info("=" * 70)
    logger.info(
        "Carga concluída em %.1fs: %s linhas em dimensões, %s linhas em fatos.",
        duracao, total_dimensoes, total_fatos,
    )


if __name__ == "__main__":
    main()
    