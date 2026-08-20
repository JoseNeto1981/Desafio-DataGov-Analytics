"""
Script de exploração da API de Consulta do PNCP (Portal Nacional de Contratações Públicas).

Objetivo: validar a fonte de dados ANTES de desenhar a arquitetura do pipeline.
Este NÃO é o código de ingestão final — é um script exploratório para responder:

  - A API responde de forma estável?
  - Como funciona a paginação na prática (quantas páginas, quantos registros por página)?
  - Quais campos realmente vêm no JSON de resposta?
  - Qual o volume de dados para uma janela de tempo pequena?
  - Quais modalidades de contratação existem e quais trazem mais registros?

Endpoint oficial: GET https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao
Parâmetros obrigatórios: dataInicial (AAAAMMDD), dataFinal (AAAAMMDD),
                         codigoModalidadeContratacao (int), pagina (int, começa em 1)
Autenticação: não é necessária (endpoint de consulta é público)

Documentação: https://www.gov.br/pncp/pt-br/acesso-a-informacao/manuais
"""

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import requests

# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("explorar_pncp")

BASE_URL_CONSULTA = "https://pncp.gov.br/api/consulta"
BASE_URL = f"{BASE_URL_CONSULTA}/v1/contratacoes/publicacao"
# Endpoint mais leve, usado só para checar se a API está no ar antes de
# gastar tempo/tentativas no endpoint pesado de contratações.
HEALTHCHECK_URL = f"{BASE_URL_CONSULTA}/v1/atas"
OUTPUT_DIR = Path(__file__).parent / "amostras_raw"
OUTPUT_DIR.mkdir(exist_ok=True)

# Principais códigos de modalidade de contratação (tabela de domínio do PNCP).
# Vale a pena rodar o script para mais de um código, pois a API não permite
# consultar "todas as modalidades" em uma única chamada.
MODALIDADES = {
    6: "Pregão Eletrônico",
    8: "Dispensa de Licitação",
    9: "Inexigibilidade",
}

TIMEOUT_SEGUNDOS = 30
MAX_TENTATIVAS = 3
ESPERA_ENTRE_TENTATIVAS = 3  # segundos, crescente a cada retry (backoff)
TAMANHO_PAGINA_MAXIMO = 50  # teto documentado para /v1/contratacoes/publicacao


def api_esta_disponivel() -> bool:
    """
    Faz uma checagem rápida em um endpoint leve (/v1/atas) antes de tentar
    o endpoint pesado de contratações. Evita gastar todas as tentativas de
    retry em um endpoint lento quando a API inteira já está fora do ar.
    """
    hoje = time.strftime("%Y%m%d")
    params = {"dataInicial": hoje, "dataFinal": hoje, "pagina": 1}
    try:
        resposta = requests.get(HEALTHCHECK_URL, params=params, timeout=10)
        # Mesmo um 204 (sem conteúdo) ou 400 de validação indicam que a API
        # está respondendo — o que importa aqui é não ter erro de conexão/timeout/5xx.
        disponivel = resposta.status_code < 500
        logger.info(
            "Health-check em /v1/atas: status %s (%s)",
            resposta.status_code, "API respondendo" if disponivel else "API indisponível",
        )
        return disponivel
    except requests.exceptions.RequestException as erro:
        logger.warning("Health-check falhou: %s", erro)
        return False


@dataclass
class ResultadoConsulta:
    modalidade: int
    pagina: int
    total_registros: int
    total_paginas: int
    quantidade_nesta_pagina: int


def buscar_pagina(data_inicial: str, data_final: str, codigo_modalidade: int, pagina: int) -> dict:
    """
    Busca uma página de resultados na API do PNCP, com retry simples em caso
    de erro de comunicação (timeout, 5xx, erro de conexão).
    """
    params = {
        "dataInicial": data_inicial,
        "dataFinal": data_final,
        "codigoModalidadeContratacao": codigo_modalidade,
        "pagina": pagina,
        "tamanhoPagina": TAMANHO_PAGINA_MAXIMO,
    }

    ultima_excecao = None
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            resposta = requests.get(BASE_URL, params=params, timeout=TIMEOUT_SEGUNDOS)

            # A API retorna 204 quando a página não tem conteúdo (fim da paginação)
            if resposta.status_code == 204:
                logger.info(
                    "Página %s (modalidade %s) sem conteúdo (204) — fim da paginação.",
                    pagina, codigo_modalidade,
                )
                return {}

            resposta.raise_for_status()
            return resposta.json()

        except requests.exceptions.RequestException as erro:
            ultima_excecao = erro
            logger.warning(
                "Tentativa %s/%s falhou para modalidade=%s pagina=%s: %s",
                tentativa, MAX_TENTATIVAS, codigo_modalidade, pagina, erro,
            )
            if tentativa < MAX_TENTATIVAS:
                time.sleep(ESPERA_ENTRE_TENTATIVAS * tentativa)

    logger.error(
        "Falha definitiva ao buscar modalidade=%s pagina=%s após %s tentativas.",
        codigo_modalidade, pagina, MAX_TENTATIVAS,
    )
    raise ultima_excecao


def explorar_modalidade(
    data_inicial: str, data_final: str, codigo_modalidade: int, max_paginas: int = 3
) -> list[ResultadoConsulta]:
    """
    Percorre algumas páginas de uma modalidade específica, salva uma amostra
    bruta em disco (simulando o que seria a camada bronze) e retorna metadados
    de cada página consultada.
    """
    nome_modalidade = MODALIDADES.get(codigo_modalidade, "desconhecida")
    logger.info(
        "Explorando modalidade %s (%s) no período %s a %s",
        codigo_modalidade, nome_modalidade, data_inicial, data_final,
    )

    resultados = []
    pagina = 1

    while pagina <= max_paginas:
        corpo = buscar_pagina(data_inicial, data_final, codigo_modalidade, pagina)

        if not corpo:
            break

        registros = corpo.get("data", [])
        total_registros = corpo.get("totalRegistros", 0)
        total_paginas = corpo.get("totalPaginas", 0)

        # Salva a resposta bruta da primeira página de cada modalidade como amostra
        # (equivalente a um arquivo bronze, mas fora do fluxo definitivo do pipeline)
        if pagina == 1:
            caminho_amostra = OUTPUT_DIR / f"modalidade_{codigo_modalidade}_pagina_{pagina}.json"
            caminho_amostra.write_text(json.dumps(corpo, ensure_ascii=False, indent=2))
            logger.info("Amostra bruta salva em %s", caminho_amostra)

        resultados.append(
            ResultadoConsulta(
                modalidade=codigo_modalidade,
                pagina=pagina,
                total_registros=total_registros,
                total_paginas=total_paginas,
                quantidade_nesta_pagina=len(registros),
            )
        )

        logger.info(
            "Modalidade %s | página %s/%s | %s registros nesta página | %s registros no total",
            codigo_modalidade, pagina, total_paginas, len(registros), total_registros,
        )

        if pagina >= total_paginas:
            break

        pagina += 1
        time.sleep(0.5)  # respeito básico a rate limit, mesmo sem limite documentado

    return resultados


def inspecionar_campos(codigo_modalidade: int) -> None:
    """Imprime as chaves do primeiro registro salvo, para mapear o schema real."""
    caminho_amostra = OUTPUT_DIR / f"modalidade_{codigo_modalidade}_pagina_1.json"
    if not caminho_amostra.exists():
        return

    corpo = json.loads(caminho_amostra.read_text())
    registros = corpo.get("data", [])
    if not registros:
        logger.info("Nenhum registro para inspecionar na modalidade %s", codigo_modalidade)
        return

    primeiro_registro = registros[0]
    logger.info(
        "Campos disponíveis no registro de contratação (modalidade %s): %s",
        codigo_modalidade, sorted(primeiro_registro.keys()),
    )


def main() -> None:
    # Janela pequena de teste: uma semana é suficiente para validar volume e schema
    data_inicial = "20260801"
    data_final = "20260807"

    logger.info("Checando disponibilidade da API antes de iniciar...")
    if not api_esta_disponivel():
        logger.error(
            "API do PNCP parece estar fora do ar agora. "
            "Confira o status em https://statuslicitacoes.com.br/api-pncp antes de tentar de novo."
        )
        return

    resumo_geral = []

    for codigo_modalidade in MODALIDADES:
        try:
            resultados = explorar_modalidade(data_inicial, data_final, codigo_modalidade)
            resumo_geral.extend(resultados)
            inspecionar_campos(codigo_modalidade)
        except requests.exceptions.RequestException:
            logger.error("Modalidade %s ficou indisponível — seguindo para a próxima.", codigo_modalidade)
            continue

    logger.info("=" * 60)
    logger.info("RESUMO DA EXPLORAÇÃO")
    for r in resumo_geral:
        logger.info(
            "Modalidade %-5s | página %s | %s/%s registros totais",
            r.modalidade, r.pagina, r.quantidade_nesta_pagina, r.total_registros,
        )


if __name__ == "__main__":
    main()