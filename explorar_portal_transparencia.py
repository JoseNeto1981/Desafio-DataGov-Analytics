"""
Script de exploração da API de Dados do Portal da Transparência do Governo Federal.

Objetivo: validar esta fonte alternativa ANTES de decidir definitivamente
a arquitetura do pipeline, já que a API do PNCP se mostrou instável
durante os testes iniciais (ver explorar_pncp.py).

Endpoint principal explorado aqui: GET /api-de-dados/licitacoes
Autenticação: header "chave-api-dados" (chave gratuita via conta gov.br)
Formato de data: DD/MM/AAAA (⚠️ diferente do PNCP, que usa AAAAMMDD —
                 essa inconsistência entre fontes deve ser documentada
                 na camada de tratamento/silver do pipeline)

Documentação: https://api.portaldatransparencia.gov.br/swagger-ui/index.html
Cadastro de chave: https://portaldatransparencia.gov.br/api-de-dados/cadastrar-email
"""

import json
import logging
import os
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
logger = logging.getLogger("explorar_portal_transparencia")

BASE_URL = "https://api.portaldatransparencia.gov.br/api-de-dados"
LICITACOES_URL = f"{BASE_URL}/licitacoes"
OUTPUT_DIR = Path(__file__).parent / "amostras_raw_transparencia"
OUTPUT_DIR.mkdir(exist_ok=True)

# A chave NUNCA fica hardcoded no código — vem de variável de ambiente,
# carregada a partir do arquivo .env (requisito explícito do desafio:
# "configuração por variáveis de ambiente").
API_KEY = os.environ.get("PORTAL_TRANSPARENCIA_API_KEY")

TIMEOUT_SEGUNDOS = 30
MAX_TENTATIVAS = 3
ESPERA_ENTRE_TENTATIVAS = 3

# Alguns códigos de órgão conhecidos, só para o teste exploratório.
# 26000 = Ministério da Educação; 26439 = uma universidade federal (exemplo
# encontrado na documentação oficial). No pipeline real, essa lista viria
# de uma consulta prévia à tabela de órgãos, não hardcoded.
ORGAOS_TESTE = {
    26000: "Ministério da Educação",
    26439: "Órgão de exemplo (doc. oficial)",
}


def _carregar_dotenv_simples(caminho: Path = Path(".env")) -> None:
    """
    Carrega variáveis de um arquivo .env de forma manual, sem dependência
    externa (evita exigir 'pip install python-dotenv' só para isso).
    Se preferir, pode trocar por `from dotenv import load_dotenv`.
    """
    if not caminho.exists():
        return
    for linha in caminho.read_text().splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip())


@dataclass
class ResultadoConsulta:
    codigo_orgao: int
    pagina: int
    quantidade_nesta_pagina: int


def buscar_pagina(data_inicial: str, data_final: str, codigo_orgao: int, pagina: int) -> list:
    """
    Busca uma página de licitações. Retorna uma lista (a API do Portal da
    Transparência devolve diretamente um array JSON, sem envelope com
    totalRegistros/totalPaginas como o PNCP — outra diferença a documentar).
    """
    headers = {"chave-api-dados": API_KEY, "Accept": "application/json"}
    params = {
        "dataInicial": data_inicial,
        "dataFinal": data_final,
        "codigoOrgao": codigo_orgao,
        "pagina": pagina,
    }

    ultima_excecao = None
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            resposta = requests.get(
                LICITACOES_URL, headers=headers, params=params, timeout=TIMEOUT_SEGUNDOS
            )

            if resposta.status_code == 400:
                # Erro de parâmetro NÃO deve ser tentado de novo — é erro do
                # cliente, não instabilidade do servidor. Logamos o corpo da
                # resposta para entender o que a API espera.
                logger.error(
                    "400 Bad Request para órgão=%s página=%s. Corpo: %s",
                    codigo_orgao, pagina, resposta.text[:500],
                )
                return []

            if resposta.status_code == 403:
                logger.error(
                    "403 Forbidden — verifique se a chave da API está correta "
                    "e configurada em PORTAL_TRANSPARENCIA_API_KEY no .env"
                )
                return []

            resposta.raise_for_status()
            corpo = resposta.json()
            return corpo if isinstance(corpo, list) else []

        except requests.exceptions.RequestException as erro:
            ultima_excecao = erro
            logger.warning(
                "Tentativa %s/%s falhou para órgão=%s página=%s: %s",
                tentativa, MAX_TENTATIVAS, codigo_orgao, pagina, erro,
            )
            if tentativa < MAX_TENTATIVAS:
                time.sleep(ESPERA_ENTRE_TENTATIVAS * tentativa)

    logger.error(
        "Falha definitiva ao buscar órgão=%s página=%s após %s tentativas.",
        codigo_orgao, pagina, MAX_TENTATIVAS,
    )
    raise ultima_excecao


def explorar_orgao(
    data_inicial: str, data_final: str, codigo_orgao: int, max_paginas: int = 3
) -> list[ResultadoConsulta]:
    nome_orgao = ORGAOS_TESTE.get(codigo_orgao, "desconhecido")
    logger.info(
        "Explorando órgão %s (%s) no período %s a %s",
        codigo_orgao, nome_orgao, data_inicial, data_final,
    )

    resultados = []
    pagina = 1

    while pagina <= max_paginas:
        registros = buscar_pagina(data_inicial, data_final, codigo_orgao, pagina)

        if not registros:
            logger.info(
                "Página %s (órgão %s) sem registros — fim da paginação ou período vazio.",
                pagina, codigo_orgao,
            )
            break

        if pagina == 1:
            caminho_amostra = OUTPUT_DIR / f"orgao_{codigo_orgao}_pagina_{pagina}.json"
            caminho_amostra.write_text(json.dumps(registros, ensure_ascii=False, indent=2))
            logger.info("Amostra bruta salva em %s", caminho_amostra)
            logger.info(
                "Campos disponíveis no primeiro registro: %s",
                sorted(registros[0].keys()) if registros else "nenhum",
            )

        resultados.append(
            ResultadoConsulta(
                codigo_orgao=codigo_orgao,
                pagina=pagina,
                quantidade_nesta_pagina=len(registros),
            )
        )

        logger.info(
            "Órgão %s | página %s | %s registros nesta página",
            codigo_orgao, pagina, len(registros),
        )

        # Como esta API não informa totalPaginas, usamos uma heurística comum:
        # se a página veio com menos registros que o tamanho padrão de página,
        # provavelmente é a última. Ajuste TAMANHO_PADRAO_PAGINA se necessário
        # após ver o volume real retornado.
        TAMANHO_PADRAO_PAGINA = 15  # valor típico documentado para esta API
        if len(registros) < TAMANHO_PADRAO_PAGINA:
            break

        pagina += 1
        time.sleep(0.5)

    return resultados


def main() -> None:
    _carregar_dotenv_simples()

    global API_KEY
    API_KEY = os.environ.get("PORTAL_TRANSPARENCIA_API_KEY")

    if not API_KEY:
        logger.error(
            "PORTAL_TRANSPARENCIA_API_KEY não encontrada. "
            "Crie um arquivo .env com a linha: PORTAL_TRANSPARENCIA_API_KEY=sua_chave"
        )
        return

    # Formato DD/MM/AAAA, conforme documentação desta API (diferente do PNCP!)
    data_inicial = "01/06/2026"
    data_final = "30/06/2026"

    resumo_geral = []

    for codigo_orgao in ORGAOS_TESTE:
        try:
            resultados = explorar_orgao(data_inicial, data_final, codigo_orgao)
            resumo_geral.extend(resultados)
        except requests.exceptions.RequestException:
            logger.error("Órgão %s ficou indisponível — seguindo para o próximo.", codigo_orgao)
            continue

    logger.info("=" * 60)
    logger.info("RESUMO DA EXPLORAÇÃO")
    for r in resumo_geral:
        logger.info(
            "Órgão %-6s | página %s | %s registros",
            r.codigo_orgao, r.pagina, r.quantidade_nesta_pagina,
        )


if __name__ == "__main__":
    main()
