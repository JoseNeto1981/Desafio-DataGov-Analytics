"""
Script de modelagem dimensional -> camada GOLD.

Lê os arquivos tratados da camada silver e monta um esquema estrela:
5 dimensões + 2 tabelas fato, prontas para carga no PostgreSQL (próxima
etapa do pipeline).

Grão de cada tabela fato (documentado aqui, não só no README, porque é
uma decisão que o próprio código precisa refletir):

  fato_item_licitacao: 1 linha = 1 item vencido dentro de 1 licitação.
    É o grão mais fino disponível com valor monetário associado --
    usado para responder as perguntas de ranking de produtos,
    fornecedores, evolução temporal, preço médio e anomalias.

  fato_participacao: 1 linha = 1 fornecedor disputando 1 item (tenha
    vencido ou não). Existe separada da fato_item porque perguntas
    sobre concorrência (quantos fornecedores disputaram, em quais
    estados há mais fornecedores atuando) precisam de quem participou,
    não só de quem venceu.

Configuração via variáveis de ambiente:
  SILVER_DIR - pasta de origem (padrão: silver)
  GOLD_DIR   - pasta de destino (padrão: gold)
"""

import logging
import os
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("transformar_gold")

SILVER_DIR = Path(os.environ.get("SILVER_DIR", "silver"))
GOLD_DIR = Path(os.environ.get("GOLD_DIR", "gold"))
GOLD_DIR.mkdir(exist_ok=True)

MESES_PT = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho",
    7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


def carregar_silver() -> dict:
    tabelas = {}
    for nome in ["licitacoes", "itens_licitacao", "participantes_licitacao"]:
        caminho = SILVER_DIR / f"{nome}.parquet"
        if not caminho.exists():
            raise FileNotFoundError(
                f"'{caminho}' não encontrado. Rode transformar_silver.py antes deste script."
            )
        tabelas[nome] = pd.read_parquet(caminho)
        logger.info("Carregado %s (%s linhas)", nome, len(tabelas[nome]))
    return tabelas


# --------------------------------------------------------------------------
# Construção das dimensões
# --------------------------------------------------------------------------

def construir_dim_tempo(licitacoes: pd.DataFrame) -> pd.DataFrame:
    datas = licitacoes["Data Resultado Compra"].dropna().dt.normalize().unique()
    dim = pd.DataFrame({"data": sorted(datas)})
    dim["sk_tempo"] = range(1, len(dim) + 1)
    dim["ano"] = dim["data"].dt.year
    dim["mes"] = dim["data"].dt.month
    dim["trimestre"] = dim["data"].dt.quarter
    dim["nome_mes"] = dim["mes"].map(MESES_PT)
    return dim[["sk_tempo", "data", "ano", "mes", "trimestre", "nome_mes"]]


def construir_dim_orgao(licitacoes: pd.DataFrame) -> pd.DataFrame:
    colunas = [
        "Código UG", "Nome UG", "Código Órgão", "Nome Órgão",
        "Código Órgão Superior", "Nome Órgão Superior", "UF", "Município",
    ]
    dim = licitacoes[colunas].drop_duplicates(subset=["Código UG"]).reset_index(drop=True)

    variacoes = licitacoes.groupby("Código UG")["Nome UG"].nunique()
    inconsistentes = (variacoes > 1).sum()
    if inconsistentes:
        logger.warning(
            "%s UG(s) aparecem com mais de um nome diferente entre os períodos "
            "— mantido o primeiro nome encontrado (critério simples, documentado aqui).",
            inconsistentes,
        )

    dim["sk_orgao"] = range(1, len(dim) + 1)
    dim = dim.rename(columns={
        "Código UG": "codigo_ug", "Nome UG": "nome_ug",
        "Código Órgão": "codigo_orgao", "Nome Órgão": "nome_orgao",
        "Código Órgão Superior": "codigo_orgao_superior", "Nome Órgão Superior": "nome_orgao_superior",
        "UF": "uf", "Município": "municipio",
    })
    return dim[["sk_orgao", "codigo_ug", "nome_ug", "codigo_orgao", "nome_orgao",
                "codigo_orgao_superior", "nome_orgao_superior", "uf", "municipio"]]


def construir_dim_fornecedor(itens: pd.DataFrame, participantes: pd.DataFrame) -> pd.DataFrame:
    de_itens = itens[["Código Vencedor", "Nome Vencedor", "tipo_documento_vencedor"]].rename(
        columns={"Código Vencedor": "codigo", "Nome Vencedor": "nome", "tipo_documento_vencedor": "tipo_documento"}
    )
    de_participantes = participantes[["Código Participante", "Nome Participante"]].rename(
        columns={"Código Participante": "codigo", "Nome Participante": "nome"}
    ).copy()
    de_participantes["tipo_documento"] = de_participantes["codigo"].apply(_classificar_documento)

    unificado = pd.concat([de_itens, de_participantes], ignore_index=True)
    unificado = unificado.dropna(subset=["codigo"])
    dim = unificado.drop_duplicates(subset=["codigo"]).reset_index(drop=True)
    dim["sk_fornecedor"] = range(1, len(dim) + 1)
    return dim[["sk_fornecedor", "codigo", "nome", "tipo_documento"]].rename(
        columns={"codigo": "codigo_fornecedor", "nome": "nome_fornecedor"}
    )


def _classificar_documento(codigo) -> str:
    if pd.isna(codigo):
        return "DESCONHECIDO"
    codigo = str(codigo)
    if codigo.upper().startswith("ESTRANG"):
        return "ESTRANGEIRO"
    if len(codigo) == 14:
        return "CNPJ"
    if len(codigo) == 11:
        return "CPF"
    return "OUTRO"


def construir_dim_produto(itens: pd.DataFrame, participantes: pd.DataFrame) -> pd.DataFrame:
    # Construída a partir da união das duas tabelas -- algumas descrições
    # só aparecem em Participantes (o item teve disputa registrada, mas por
    # algum motivo não ficou com o mesmo registro espelhado em Itens).
    # Sem essa união, ~377 linhas de fato_participacao ficariam com
    # sk_produto nulo -- achado real ao validar a primeira versão deste script.
    de_itens = itens[["Descrição"]].rename(columns={"Descrição": "descricao_item"})
    de_participantes = participantes[["Descrição Item Compra"]].rename(
        columns={"Descrição Item Compra": "descricao_item"}
    )
    dim = pd.concat([de_itens, de_participantes], ignore_index=True).drop_duplicates().reset_index(drop=True)
    dim["sk_produto"] = range(1, len(dim) + 1)
    return dim[["sk_produto", "descricao_item"]]


def construir_dim_licitacao(licitacoes: pd.DataFrame) -> pd.DataFrame:
    colunas = [
        "Número Licitação", "Código UG", "Código Modalidade Compra", "Número Processo",
        "Modalidade Compra", "Situação Licitação", "Objeto", "Valor Licitação",
    ]
    # A chave de negócio precisa incluir a modalidade: encontramos 13 casos
    # em que o mesmo Número Licitação + Código UG se repete com modalidades
    # diferentes (ex.: "000142023" existe como Pregão E como Dispensa na
    # mesma UG). Sem a modalidade na chave, itens de uma licitação
    # acabariam vinculados aos atributos da outra por engano.
    chave = ["Número Licitação", "Código UG", "Código Modalidade Compra"]
    dim = licitacoes[colunas].drop_duplicates(subset=chave).reset_index(drop=True)
    dim["sk_licitacao"] = range(1, len(dim) + 1)
    return dim.rename(columns={
        "Número Licitação": "numero_licitacao", "Código UG": "codigo_ug",
        "Código Modalidade Compra": "codigo_modalidade_compra",
        "Número Processo": "numero_processo", "Modalidade Compra": "modalidade_compra",
        "Situação Licitação": "situacao_licitacao", "Objeto": "objeto", "Valor Licitação": "valor_licitacao",
    })[["sk_licitacao", "numero_licitacao", "codigo_ug", "codigo_modalidade_compra", "numero_processo",
        "modalidade_compra", "situacao_licitacao", "objeto", "valor_licitacao"]]


# --------------------------------------------------------------------------
# Construção das tabelas fato
# --------------------------------------------------------------------------

def construir_fato_item(
    itens: pd.DataFrame, licitacoes: pd.DataFrame, dim_tempo, dim_orgao, dim_fornecedor, dim_produto, dim_licitacao
) -> pd.DataFrame:
    contexto = licitacoes[["Número Licitação", "Código UG", "Data Resultado Compra"]].drop_duplicates(
        subset=["Número Licitação", "Código UG"]
    )

    fato = itens.merge(contexto, on=["Número Licitação", "Código UG"], how="left", indicator=True)
    sem_licitacao = (fato["_merge"] == "left_only").sum()
    if sem_licitacao:
        logger.warning(
            "%s item(ns) não encontraram a licitação correspondente na tabela de licitações "
            "— descartados da fato (quebra de integridade referencial que não deveria ocorrer "
            "dentro do mesmo período de origem; investigar se voltar a acontecer com mais dados).",
            sem_licitacao,
        )
    fato = fato[fato["_merge"] == "both"].drop(columns=["_merge"])

    fato = fato.merge(
        dim_tempo[["sk_tempo", "data"]],
        left_on=fato["Data Resultado Compra"].dt.normalize(), right_on="data", how="left",
    ).drop(columns=["data"])

    fato = fato.merge(
        dim_orgao[["sk_orgao", "codigo_ug"]], left_on="Código UG", right_on="codigo_ug", how="left"
    ).drop(columns=["codigo_ug"])

    fato = fato.merge(
        dim_fornecedor[["sk_fornecedor", "codigo_fornecedor"]],
        left_on="Código Vencedor", right_on="codigo_fornecedor", how="left",
    ).drop(columns=["codigo_fornecedor"])

    fato = fato.merge(
        dim_produto, left_on="Descrição", right_on="descricao_item", how="left"
    ).drop(columns=["descricao_item"])

    fato = fato.merge(
        dim_licitacao[["sk_licitacao", "numero_licitacao", "codigo_ug", "codigo_modalidade_compra"]],
        left_on=["Número Licitação", "Código UG", "Código Modalidade Compra"],
        right_on=["numero_licitacao", "codigo_ug", "codigo_modalidade_compra"], how="left",
    ).drop(columns=["numero_licitacao", "codigo_ug", "codigo_modalidade_compra"])

    fato["valor_unitario_item"] = (fato["Valor Item"] / fato["Quantidade Item"]).where(
        fato["Quantidade Item"] > 0
    )
    qtd_sem_unitario = fato["valor_unitario_item"].isna().sum()
    if qtd_sem_unitario:
        logger.info(
            "%s item(ns) sem valor unitário calculável (quantidade zero ou nula) "
            "— campo fica nulo, mas a linha é mantida (valor total ainda é válido).",
            qtd_sem_unitario,
        )

    fato = fato.rename(columns={"Quantidade Item": "quantidade_item", "Valor Item": "valor_item"})
    return fato[[
        "sk_tempo", "sk_orgao", "sk_fornecedor", "sk_produto", "sk_licitacao",
        "quantidade_item", "valor_item", "valor_unitario_item",
    ]]


def construir_fato_participacao(
    participantes: pd.DataFrame, dim_fornecedor, dim_produto, dim_licitacao
) -> pd.DataFrame:
    fato = participantes.merge(
        dim_fornecedor[["sk_fornecedor", "codigo_fornecedor"]],
        left_on="Código Participante", right_on="codigo_fornecedor", how="left",
    ).drop(columns=["codigo_fornecedor"])

    fato = fato.merge(
        dim_produto, left_on="Descrição Item Compra", right_on="descricao_item", how="left"
    ).drop(columns=["descricao_item"])

    fato = fato.merge(
        dim_licitacao[["sk_licitacao", "numero_licitacao", "codigo_ug", "codigo_modalidade_compra"]],
        left_on=["Número Licitação", "Código UG", "Código Modalidade Compra"],
        right_on=["numero_licitacao", "codigo_ug", "codigo_modalidade_compra"], how="left",
    ).drop(columns=["numero_licitacao", "codigo_ug", "codigo_modalidade_compra"])

    return fato[["sk_licitacao", "sk_produto", "sk_fornecedor", "flag_vencedor"]]


# --------------------------------------------------------------------------
# Orquestração
# --------------------------------------------------------------------------

def main() -> None:
    tabelas = carregar_silver()
    licitacoes = tabelas["licitacoes"]
    itens = tabelas["itens_licitacao"]
    participantes = tabelas["participantes_licitacao"]

    logger.info("=" * 70)
    logger.info("Construindo dimensões...")
    dim_tempo = construir_dim_tempo(licitacoes)
    dim_orgao = construir_dim_orgao(licitacoes)
    dim_fornecedor = construir_dim_fornecedor(itens, participantes)
    dim_produto = construir_dim_produto(itens, participantes)
    dim_licitacao = construir_dim_licitacao(licitacoes)

    for nome, dim in [
        ("dim_tempo", dim_tempo), ("dim_orgao", dim_orgao), ("dim_fornecedor", dim_fornecedor),
        ("dim_produto", dim_produto), ("dim_licitacao", dim_licitacao),
    ]:
        caminho = GOLD_DIR / f"{nome}.parquet"
        dim.to_parquet(caminho, index=False)
        logger.info("Salvo %s (%s linhas)", caminho, len(dim))

    logger.info("=" * 70)
    logger.info("Construindo tabelas fato...")
    fato_item = construir_fato_item(itens, licitacoes, dim_tempo, dim_orgao, dim_fornecedor, dim_produto, dim_licitacao)
    fato_participacao = construir_fato_participacao(participantes, dim_fornecedor, dim_produto, dim_licitacao)

    for nome, fato in [("fato_item_licitacao", fato_item), ("fato_participacao", fato_participacao)]:
        caminho = GOLD_DIR / f"{nome}.parquet"
        fato.to_parquet(caminho, index=False)
        logger.info("Salvo %s (%s linhas)", caminho, len(fato))

    logger.info("=" * 70)
    logger.info("Camada gold construída com sucesso em '%s'.", GOLD_DIR)


if __name__ == "__main__":
    main()