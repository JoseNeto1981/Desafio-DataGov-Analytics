"""
Script de tratamento -> camada SILVER.

Lê os arquivos da camada bronze (todos os períodos disponíveis), aplica
as regras de tratamento e padronização, e grava o resultado em Parquet
na camada silver -- um arquivo consolidado por dataset (não mais um por
mês), já que a partir daqui os dados são tratados como um conjunto
único e coerente, pronto para as camadas seguintes.

Cada execução também grava um relatório de qualidade em JSON, contando
exatamente quantos registros foram afetados por cada regra. Isso é o
que permite documentar, com números reais, as decisões de tratamento
pedidas na seção 8 do desafio -- em vez de descrever as regras em
prosa sem evidência do impacto real nos dados.

Todas as regras abaixo foram definidas depois de inspecionar os dados
reais (ver conversa/README), não escritas "no escuro":
  - UF com valor "-3" encontrado nos dados -> não é um estado válido
  - Código Participante "-11" encontrado -> sentinela inválido
  - Código Participante "ESTRANG0032850" etc -> categoria legítima
    (fornecedor estrangeiro, sem CNPJ/CPF -- não deve ser tratado como erro)
  - ~2% dos itens vêm sem Código Item Compra -> preenchido com chave
    substituta sequencial, sinalizada em coluna própria

Configuração via variáveis de ambiente:
  BRONZE_DIR - pasta de origem (padrão: bronze)
  SILVER_DIR - pasta de destino (padrão: silver)
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("transformar_silver")

BRONZE_DIR = Path(os.environ.get("BRONZE_DIR", "bronze"))
SILVER_DIR = Path(os.environ.get("SILVER_DIR", "silver"))
SILVER_DIR.mkdir(exist_ok=True)

ENCODING_ORIGEM = "latin1"
SEPARADOR_ORIGEM = ";"

# As 26 UFs + Distrito Federal -- qualquer outro valor na coluna UF é
# considerado inválido e tratado (ver função tratar_licitacoes).
UFS_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
    "MT", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}

PADRAO_CODIGO_NUMERICO = re.compile(r"^\d+$")
PADRAO_CODIGO_ESTRANGEIRO = re.compile(r"^ESTRANG", re.IGNORECASE)


@dataclass
class RelatorioQualidade:
    dataset: str
    linhas_entrada: int = 0
    linhas_saida: int = 0
    duplicados_removidos: int = 0
    valores_negativos_removidos: int = 0
    uf_invalida_corrigida: int = 0
    codigo_item_gerado: int = 0
    participante_invalido_corrigido: int = 0
    participante_estrangeiro: int = 0
    datas_invalidas: int = 0

    def como_dict(self) -> dict:
        return self.__dict__


# --------------------------------------------------------------------------
# Funções auxiliares de conversão (reaproveitadas entre datasets)
# --------------------------------------------------------------------------

def converter_valor_brl(serie: pd.Series) -> pd.Series:
    """Converte string em formato brasileiro ('1.234,56' ou '1234,56') para float."""
    return (
        serie.astype(str)
        .str.replace(".", "", regex=False)   # remove separador de milhar
        .str.replace(",", ".", regex=False)  # vírgula decimal -> ponto
        .astype(float)
    )


def converter_data_br(serie: pd.Series) -> pd.Series:
    """Converte string DD/MM/AAAA para datetime, preservando nulos como NaT."""
    return pd.to_datetime(serie, format="%d/%m/%Y", errors="coerce")


def padronizar_texto(serie: pd.Series) -> pd.Series:
    """Remove espaços extras nas pontas e colapsa espaços duplos no meio."""
    return serie.astype(str).str.strip().str.replace(r"\s+", " ", regex=True)


def carregar_bronze(nome_logico: str) -> pd.DataFrame:
    """
    Carrega e concatena todos os arquivos de um dataset na bronze,
    independente de quantos períodos (ano/mês) existirem. Adiciona
    colunas de origem para rastreabilidade dentro da própria silver.
    """
    caminho_dataset = BRONZE_DIR / nome_logico
    if not caminho_dataset.exists():
        logger.warning("Dataset '%s' não encontrado na bronze — pulando.", nome_logico)
        return pd.DataFrame()

    arquivos = sorted(caminho_dataset.glob("ano=*/mes=*/*.csv"))
    if not arquivos:
        logger.warning("Nenhum arquivo encontrado para '%s' na bronze.", nome_logico)
        return pd.DataFrame()

    partes = []
    for arquivo in arquivos:
        df_parte = pd.read_csv(
            arquivo, encoding=ENCODING_ORIGEM, sep=SEPARADOR_ORIGEM,
            dtype=str,  # tudo como string na leitura -- conversão de tipo é explícita e controlada abaixo
        )
        # ano/mes extraídos do caminho particionado, não do nome do arquivo,
        # para casar com a estrutura que o script de ingestão já criou.
        df_parte["_ano_particao"] = arquivo.parent.parent.name.split("=")[1]
        df_parte["_mes_particao"] = arquivo.parent.name.split("=")[1]
        partes.append(df_parte)
        logger.info("Carregado %s (%s linhas)", arquivo, len(df_parte))

    return pd.concat(partes, ignore_index=True)


# --------------------------------------------------------------------------
# Tratamento por dataset
# --------------------------------------------------------------------------

def tratar_licitacoes(df: pd.DataFrame) -> tuple[pd.DataFrame, RelatorioQualidade]:
    rel = RelatorioQualidade(dataset="licitacoes", linhas_entrada=len(df))

    for coluna in ["Nome UG", "Modalidade Compra", "Objeto", "Situação Licitação",
                    "Nome Órgão Superior", "Nome Órgão", "Município"]:
        df[coluna] = padronizar_texto(df[coluna])

    df["UF"] = df["UF"].astype(str).str.strip().str.upper()
    uf_invalida = ~df["UF"].isin(UFS_VALIDAS)
    rel.uf_invalida_corrigida = int(uf_invalida.sum())
    if rel.uf_invalida_corrigida:
        logger.warning(
            "%s registro(s) com UF inválida (ex.: %s) — valor zerado, "
            "linha mantida (o restante do registro continua útil).",
            rel.uf_invalida_corrigida, df.loc[uf_invalida, "UF"].unique()[:5].tolist(),
        )
    df.loc[uf_invalida, "UF"] = pd.NA

    df["Valor Licitação"] = converter_valor_brl(df["Valor Licitação"])
    negativos = df["Valor Licitação"] < 0
    rel.valores_negativos_removidos = int(negativos.sum())
    if rel.valores_negativos_removidos:
        logger.warning(
            "%s licitação(ões) com Valor Licitação negativo — removida(s).",
            rel.valores_negativos_removidos,
        )
    df = df.loc[~negativos].copy()

    df["Data Resultado Compra"] = converter_data_br(df["Data Resultado Compra"])
    df["Data Abertura"] = converter_data_br(df["Data Abertura"])
    # Data Abertura nula é esperado (nem toda modalidade tem sessão de
    # abertura pública, ex.: inexigibilidade) — não é tratada como erro.

    antes = len(df)
    df = df.drop_duplicates()
    rel.duplicados_removidos = antes - len(df)

    rel.linhas_saida = len(df)
    return df, rel


def tratar_itens(df: pd.DataFrame) -> tuple[pd.DataFrame, RelatorioQualidade]:
    rel = RelatorioQualidade(dataset="itens_licitacao", linhas_entrada=len(df))

    df["Descrição"] = padronizar_texto(df["Descrição"])
    df["Nome Vencedor"] = padronizar_texto(df["Nome Vencedor"])

    df["Valor Item"] = converter_valor_brl(df["Valor Item"])
    negativos = df["Valor Item"] < 0
    rel.valores_negativos_removidos = int(negativos.sum())
    df = df.loc[~negativos].copy()

    df["Quantidade Item"] = pd.to_numeric(df["Quantidade Item"], errors="coerce")

    df["Código Vencedor"] = df["Código Vencedor"].astype(str).str.strip()
    df["tipo_documento_vencedor"] = df["Código Vencedor"].apply(
        lambda v: "CNPJ" if len(v) == 14 else ("CPF" if len(v) == 11 else "OUTRO")
    )

    # IMPORTANTE: a deduplicação acontece ANTES de gerar a chave substituta
    # para Código Item Compra. Se gerássemos a chave primeiro, cada linha
    # ganharia um valor diferente (baseado no índice) e duplicatas reais
    # (mesma licitação, mesmo item, mesmo valor, ambas sem código de origem)
    # deixariam de ser detectadas como duplicatas — foi exatamente isso que
    # aconteceu na primeira versão deste script, corrigido após conferir
    # os números do relatório de qualidade contra uma checagem manual.
    antes = len(df)
    df = df.drop_duplicates()
    rel.duplicados_removidos = antes - len(df)

    codigo_ausente = df["Código Item Compra"].isna()
    rel.codigo_item_gerado = int(codigo_ausente.sum())
    if rel.codigo_item_gerado:
        logger.warning(
            "%s item(ns) sem Código Item Compra na origem — chave substituta "
            "gerada (padrão SEM_CODIGO_<índice>) para preservar o registro "
            "sem quebrar a integridade referencial com Participantes.",
            rel.codigo_item_gerado,
        )
    df["codigo_item_gerado"] = codigo_ausente
    df.loc[codigo_ausente, "Código Item Compra"] = [
        f"SEM_CODIGO_{i}" for i in df.loc[codigo_ausente].index
    ]

    rel.linhas_saida = len(df)
    return df, rel


def tratar_participantes(df: pd.DataFrame) -> tuple[pd.DataFrame, RelatorioQualidade]:
    rel = RelatorioQualidade(dataset="participantes_licitacao", linhas_entrada=len(df))

    df["Nome Participante"] = padronizar_texto(df["Nome Participante"])
    df["Código Participante"] = df["Código Participante"].astype(str).str.strip()

    eh_numerico = df["Código Participante"].str.match(PADRAO_CODIGO_NUMERICO)
    eh_estrangeiro = df["Código Participante"].str.match(PADRAO_CODIGO_ESTRANGEIRO)
    invalido = ~eh_numerico & ~eh_estrangeiro

    rel.participante_estrangeiro = int(eh_estrangeiro.sum())
    rel.participante_invalido_corrigido = int(invalido.sum())
    if rel.participante_invalido_corrigido:
        logger.warning(
            "%s participante(s) com código em formato não reconhecido "
            "(nem numérico, nem padrão ESTRANG...) — valor zerado, linha mantida.",
            rel.participante_invalido_corrigido,
        )
    df.loc[invalido, "Código Participante"] = pd.NA

    df["flag_vencedor"] = df["Flag Vencedor"].str.strip().str.upper().eq("SIM")
    df = df.drop(columns=["Flag Vencedor"])

    antes = len(df)
    df = df.drop_duplicates()
    rel.duplicados_removidos = antes - len(df)

    rel.linhas_saida = len(df)
    return df, rel


def tratar_empenhos(df: pd.DataFrame) -> tuple[pd.DataFrame, RelatorioQualidade]:
    rel = RelatorioQualidade(dataset="empenhos_relacionados", linhas_entrada=len(df))

    if len(df) == 0:
        logger.info("Nenhum empenho no período disponível — mantendo schema vazio na silver.")
        rel.linhas_saida = 0
        return df, rel

    df["Valor Empenho (R$)"] = converter_valor_brl(df["Valor Empenho (R$)"])
    df["Data Emissão Empenho"] = converter_data_br(df["Data Emissão Empenho"])

    antes = len(df)
    df = df.drop_duplicates()
    rel.duplicados_removidos = antes - len(df)

    rel.linhas_saida = len(df)
    return df, rel


# --------------------------------------------------------------------------
# Orquestração
# --------------------------------------------------------------------------

PIPELINE = {
    "licitacoes": tratar_licitacoes,
    "itens_licitacao": tratar_itens,
    "participantes_licitacao": tratar_participantes,
    "empenhos_relacionados": tratar_empenhos,
}


def main() -> None:
    relatorios = []

    for nome_logico, funcao_tratamento in PIPELINE.items():
        logger.info("=" * 70)
        logger.info("Processando dataset: %s", nome_logico)

        df_bruto = carregar_bronze(nome_logico)
        if df_bruto.empty and nome_logico != "empenhos_relacionados":
            logger.warning("Sem dados para '%s' — pulando tratamento.", nome_logico)
            continue

        df_tratado, relatorio = funcao_tratamento(df_bruto)
        relatorios.append(relatorio)

        caminho_saida = SILVER_DIR / f"{nome_logico}.parquet"
        df_tratado.to_parquet(caminho_saida, index=False)
        logger.info(
            "Salvo %s (%s -> %s linhas após tratamento)",
            caminho_saida, relatorio.linhas_entrada, relatorio.linhas_saida,
        )

    caminho_relatorio = SILVER_DIR / "_relatorio_qualidade.json"
    caminho_relatorio.write_text(
        json.dumps([r.como_dict() for r in relatorios], ensure_ascii=False, indent=2)
    )

    logger.info("=" * 70)
    logger.info("RELATÓRIO DE QUALIDADE")
    for r in relatorios:
        logger.info(
            "%-28s | entrada=%-7s saida=%-7s duplicados=%-5s neg=%-4s uf_invalida=%-4s "
            "item_gerado=%-4s part_invalido=%-4s part_estrangeiro=%s",
            r.dataset, r.linhas_entrada, r.linhas_saida, r.duplicados_removidos,
            r.valores_negativos_removidos, r.uf_invalida_corrigida,
            r.codigo_item_gerado, r.participante_invalido_corrigido, r.participante_estrangeiro,
        )
    logger.info("Relatório completo salvo em %s", caminho_relatorio)


if __name__ == "__main__":
    main()