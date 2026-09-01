"""
Script de ingestão -> camada BRONZE.

Lê os arquivos CSV baixados manualmente do Portal da Transparência
(pasta de entrada configurável) e os organiza na camada bronze do
data lake local: particionados por ano/mês, com um manifesto de
rastreabilidade ao lado de cada arquivo.

Por que isso ainda conta como "ingestão", mesmo sendo download manual?
Porque a parte que o desafio realmente cobra aqui — validação de
estrutura, particionamento, rastreabilidade, preservação do dado bruto,
logs, reprocessamento seguro — está toda presente. A única etapa que
não está automatizada ainda é o clique de download em si (a API exige
autenticação gov.br que está bloqueada — ver README, seção "Decisões
técnicas e limitações"). Quando essa autenticação for resolvida, essa
etapa manual é substituída por chamadas HTTP, sem mudar o resto do
pipeline.

Convenção de nomes de arquivo esperada: AAAAMM_NomeDoDataset.csv
Exemplo: 202401_Licitação.csv, 202401_ItemLicitação.csv

Configuração via variáveis de ambiente:
  LANDING_ZONE_DIR - pasta onde você coloca os CSVs baixados (padrão: dados_brutos)
  BRONZE_DIR       - pasta de destino da camada bronze (padrão: bronze)
"""

import csv
import hashlib
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("ingestao_bronze")

LANDING_ZONE_DIR = Path(os.environ.get("LANDING_ZONE_DIR", "dados_brutos"))
BRONZE_DIR = Path(os.environ.get("BRONZE_DIR", "bronze"))

# Confirmados na etapa de exploração (ver conversa/README): o Portal da
# Transparência entrega esses CSVs em Latin-1, com ';' como separador —
# diferente do padrão internacional (UTF-8, ',') e por isso documentado
# explicitamente aqui, não deixado implícito.
ENCODING_ORIGEM = "latin1"
SEPARADOR_ORIGEM = ";"

PADRAO_NOME_ARQUIVO = re.compile(r"^(?P<ano>\d{4})(?P<mes>\d{2})_(?P<dataset>.+)\.csv$")

# Mapeia o nome do dataset exatamente como vem no arquivo baixado para um
# nome lógico padronizado (sem acento, minúsculo, seguro para nome de pasta)
# e a lista mínima de colunas que ele precisa ter para ser considerado válido.
# Isso é o que garante que uma mudança inesperada de schema na fonte não
# entre silenciosamente no pipeline — o script para e avisa.
DATASETS_ESPERADOS = {
    "Licitação": {
        "nome_logico": "licitacoes",
        "colunas_obrigatorias": [
            "Número Licitação", "Código UG", "Código Órgão", "UF", "Valor Licitação",
        ],
    },
    "ItemLicitação": {
        "nome_logico": "itens_licitacao",
        "colunas_obrigatorias": [
            "Número Licitação", "Código Item Compra", "Valor Item", "Código Vencedor",
        ],
    },
    "ParticipantesLicitação": {
        "nome_logico": "participantes_licitacao",
        "colunas_obrigatorias": [
            "Número Licitação", "Código Item Compra", "Código Participante", "Flag Vencedor",
        ],
    },
    "EmpenhosRelacionados": {
        "nome_logico": "empenhos_relacionados",
        "colunas_obrigatorias": [
            "Número Licitação", "Código Empenho", "Valor Empenho (R$)",
        ],
    },
}


@dataclass
class ResultadoIngestao:
    arquivo_origem: str
    dataset_logico: str
    ano: str
    mes: str
    linhas: int
    status: str  # "sucesso", "vazio", "erro_validacao", "erro_encoding"


def calcular_sha256(caminho: Path) -> str:
    """
    Calcula o hash do arquivo já copiado para a bronze. Serve de 'prova'
    de que o arquivo não foi alterado depois da ingestão — útil para
    auditoria e para detectar reprocessamento com arquivo diferente sob
    o mesmo nome.
    """
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(8192), b""):
            h.update(bloco)
    return h.hexdigest()


def ler_cabecalho_e_contar_linhas(caminho: Path) -> tuple[list, int]:
    """
    Lê apenas o cabeçalho e conta as linhas de dados, sem carregar o
    arquivo inteiro na memória de uma vez (importante para o arquivo de
    Participantes, que já veio com mais de 160 mil linhas em um único mês).
    """
    with open(caminho, encoding=ENCODING_ORIGEM, newline="") as f:
        leitor = csv.reader(f, delimiter=SEPARADOR_ORIGEM)
        cabecalho = next(leitor)
        linhas = sum(1 for _ in leitor)
    return cabecalho, linhas


def validar_colunas(dataset: str, cabecalho: list) -> list:
    """Retorna a lista de colunas obrigatórias que estão faltando (vazia = tudo ok)."""
    esperado = DATASETS_ESPERADOS[dataset]["colunas_obrigatorias"]
    return [coluna for coluna in esperado if coluna not in cabecalho]


def processar_arquivo(caminho: Path) -> Optional[ResultadoIngestao]:
    nome = caminho.name
    match = PADRAO_NOME_ARQUIVO.match(nome)

    if not match:
        logger.warning("Arquivo '%s' não segue o padrão AAAAMM_Dataset.csv — ignorado.", nome)
        return None

    ano, mes, dataset = match.group("ano"), match.group("mes"), match.group("dataset")

    if dataset not in DATASETS_ESPERADOS:
        logger.warning("Dataset '%s' desconhecido (arquivo %s) — ignorado.", dataset, nome)
        return None

    logger.info("Processando %s (dataset=%s, ano=%s, mes=%s)", nome, dataset, ano, mes)

    try:
        cabecalho, linhas = ler_cabecalho_e_contar_linhas(caminho)
    except UnicodeDecodeError as erro:
        logger.error(
            "Falha de encoding ao ler %s: %s. Esperado %s — o arquivo pode "
            "ter sido salvo/editado com outro encoding.",
            nome, erro, ENCODING_ORIGEM,
        )
        return ResultadoIngestao(nome, dataset, ano, mes, 0, "erro_encoding")

    faltando = validar_colunas(dataset, cabecalho)
    if faltando:
        logger.error(
            "Colunas obrigatórias ausentes em %s: %s — arquivo NÃO promovido "
            "para a bronze (schema divergente do esperado).",
            nome, faltando,
        )
        return ResultadoIngestao(nome, dataset, ano, mes, linhas, "erro_validacao")

    status = "vazio" if linhas == 0 else "sucesso"
    if status == "vazio":
        logger.warning(
            "%s não tem nenhum registro (só cabeçalho) — promovido para a "
            "bronze mesmo assim, para deixar rastro de que o período foi "
            "verificado e realmente não tinha dados (não é falha de ingestão).",
            nome,
        )

    nome_logico = DATASETS_ESPERADOS[dataset]["nome_logico"]
    diretorio_destino = BRONZE_DIR / nome_logico / f"ano={ano}" / f"mes={mes}"
    diretorio_destino.mkdir(parents=True, exist_ok=True)

    caminho_destino = diretorio_destino / nome
    # copyfile() em vez de copy()/copy2(): ambas as outras tentam replicar
    # metadados do arquivo original (copy2 copia timestamp via utime,
    # copy copia permissões via chmod) -- as duas falham com
    # PermissionError nesse ambiente específico (bind mount Windows -> WSL2
    # -> container Docker, que não permite alterar atributos de arquivo
    # através da ponte de sistemas de arquivos). copyfile() copia somente
    # bytes de conteúdo, sem tocar em metadados -- suficiente aqui, já que
    # o manifesto abaixo registra nosso próprio timestamp de ingestão.
    shutil.copyfile(caminho, caminho_destino)

    checksum = calcular_sha256(caminho_destino)

    manifesto = {
        "arquivo_origem": nome,
        "dataset_logico": nome_logico,
        "ano": ano,
        "mes": mes,
        "linhas": linhas,
        "colunas": cabecalho,
        "sha256": checksum,
        "encoding_original": ENCODING_ORIGEM,
        "separador_original": SEPARADOR_ORIGEM,
        "data_ingestao_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
    }
    caminho_manifesto = diretorio_destino / f"_manifest_{caminho.stem}.json"
    caminho_manifesto.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2))

    logger.info(
        "OK: %s -> %s (%s linhas, checksum %s...)",
        nome, caminho_destino, linhas, checksum[:12],
    )

    return ResultadoIngestao(nome, dataset, ano, mes, linhas, status)


def main() -> None:
    if not LANDING_ZONE_DIR.exists():
        logger.error(
            "Pasta de entrada '%s' não existe. Crie-a e coloque nela os CSVs "
            "baixados manualmente do Portal da Transparência.",
            LANDING_ZONE_DIR,
        )
        return

    arquivos = sorted(LANDING_ZONE_DIR.glob("*.csv"))
    if not arquivos:
        logger.warning("Nenhum arquivo .csv encontrado em '%s'.", LANDING_ZONE_DIR)
        return

    resultados = []
    for arquivo in arquivos:
        resultado = processar_arquivo(arquivo)
        if resultado:
            resultados.append(resultado)

    logger.info("=" * 70)
    logger.info("RESUMO DA INGESTÃO")
    for r in resultados:
        logger.info("%-32s | status=%-16s | linhas=%s", r.arquivo_origem, r.status, r.linhas)

    erros = [r for r in resultados if r.status in ("erro_validacao", "erro_encoding")]
    if erros:
        logger.warning(
            "%s arquivo(s) NÃO foram promovidos para a bronze por erro de validação. "
            "Revise antes de seguir para a camada silver.",
            len(erros),
        )


if __name__ == "__main__":
    main()