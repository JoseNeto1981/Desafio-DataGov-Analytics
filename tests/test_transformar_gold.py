"""
Testes de transformar_gold.py.

Cobrem a construção das dimensões e, principalmente, dois testes de
regressão para bugs reais encontrados ao validar a primeira versão deste
script contra os dados de verdade:
  1. Chave de negócio da licitação precisa incluir a modalidade de compra.
  2. dim_produto precisa ser a união de Itens + Participantes.
"""

import pandas as pd

import transformar_gold as gold


# ----------------------------------------------------------------------------
# _classificar_documento
# ----------------------------------------------------------------------------

def test_classificar_documento():
    assert gold._classificar_documento("12345678000199") == "CNPJ"   # 14 dígitos
    assert gold._classificar_documento("12345678901") == "CPF"        # 11 dígitos
    assert gold._classificar_documento("ESTRANG0032850") == "ESTRANGEIRO"
    assert gold._classificar_documento("123") == "OUTRO"
    assert gold._classificar_documento(None) == "DESCONHECIDO"


# ----------------------------------------------------------------------------
# construir_dim_licitacao -- REGRESSÃO: chave composta precisa da modalidade
# ----------------------------------------------------------------------------

def test_dim_licitacao_mesmo_numero_e_ug_com_modalidades_diferentes_gera_duas_linhas():
    """
    Teste de regressão: encontramos 13 casos reais em que o mesmo par
    (Número Licitação, Código UG) se repete com Código Modalidade Compra
    diferente -- por exemplo, o mesmo número usado tanto para um Pregão
    quanto para uma Dispensa de Licitação na mesma UG.

    A primeira versão deste script deduplicava a dim_licitacao usando só
    (Número Licitação, Código UG), o que descartava uma das duas linhas
    por engano e fazia itens da licitação descartada se vincularem aos
    atributos (modalidade, situação, objeto) da licitação errada.
    """
    df = pd.DataFrame({
        "Número Licitação": ["000142023", "000142023"],
        "Código UG": ["100", "100"],
        "Código Modalidade Compra": ["6", "8"],   # Pregão vs. Dispensa
        "Número Processo": ["P1", "P2"],
        "Modalidade Compra": ["Pregão Eletrônico", "Dispensa de Licitação"],
        "Situação Licitação": ["Concluída", "Concluída"],
        "Objeto": ["Objeto A", "Objeto B"],
        "Valor Licitação": [1000.0, 2000.0],
    })

    dim = gold.construir_dim_licitacao(df)

    assert len(dim) == 2, (
        "Licitações com mesmo número/UG mas modalidades diferentes foram "
        "colapsadas em 1 linha -- verifique se a chave de deduplicação "
        "ainda inclui codigo_modalidade_compra."
    )
    assert set(dim["modalidade_compra"]) == {"Pregão Eletrônico", "Dispensa de Licitação"}


def test_dim_licitacao_duplicata_real_e_removida():
    linha = pd.DataFrame({
        "Número Licitação": ["1"], "Código UG": ["100"], "Código Modalidade Compra": ["6"],
        "Número Processo": ["P1"], "Modalidade Compra": ["Pregão"], "Situação Licitação": ["Concluída"],
        "Objeto": ["Objeto"], "Valor Licitação": [1000.0],
    })
    df = pd.concat([linha, linha], ignore_index=True)

    dim = gold.construir_dim_licitacao(df)

    assert len(dim) == 1


# ----------------------------------------------------------------------------
# construir_dim_produto -- REGRESSÃO: união de Itens + Participantes
# ----------------------------------------------------------------------------

def test_dim_produto_inclui_descricoes_que_so_existem_em_participantes():
    """
    Teste de regressão: 31 descrições de item, no conjunto de dados real,
    só aparecem na tabela de Participantes (não têm registro espelhado em
    Itens). A primeira versão deste script construía dim_produto só a
    partir de Itens, deixando essas linhas de fato_participacao com
    sk_produto nulo.
    """
    itens = pd.DataFrame({"Descrição": ["Produto A", "Produto B"]})
    participantes = pd.DataFrame({"Descrição Item Compra": ["Produto B", "Produto C (só em participantes)"]})

    dim = gold.construir_dim_produto(itens, participantes)

    descricoes = set(dim["descricao_item"])
    assert descricoes == {"Produto A", "Produto B", "Produto C (só em participantes)"}
    assert len(dim) == 3  # "Produto B" não deve aparecer duplicado


# ----------------------------------------------------------------------------
# construir_dim_tempo / construir_dim_orgao / construir_dim_fornecedor
# ----------------------------------------------------------------------------

def test_dim_tempo_uma_linha_por_data_distinta():
    df = pd.DataFrame({
        "Data Resultado Compra": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-02-15", None]),
    })
    dim = gold.construir_dim_tempo(df)

    assert len(dim) == 2  # datas distintas, nulo ignorado
    assert set(dim["mes"]) == {1, 2}


def test_dim_fornecedor_uniao_de_vencedores_e_participantes_sem_duplicar_codigo():
    itens = pd.DataFrame({
        "Código Vencedor": ["11111111000100"], "Nome Vencedor": ["Fornecedor A"],
        "tipo_documento_vencedor": ["CNPJ"],
    })
    participantes = pd.DataFrame({
        "Código Participante": ["11111111000100", "22222222000100"],  # o primeiro repete o vencedor
        "Nome Participante": ["Fornecedor A", "Fornecedor B"],
    })

    dim = gold.construir_dim_fornecedor(itens, participantes)

    assert len(dim) == 2  # código repetido não gera 2 linhas
    assert set(dim["codigo_fornecedor"]) == {"11111111000100", "22222222000100"}


# ----------------------------------------------------------------------------
# construir_fato_item -- integridade referencial fim a fim
# ----------------------------------------------------------------------------

def test_fato_item_sem_nulos_nas_chaves_estrangeiras_com_dados_consistentes():
    licitacoes = pd.DataFrame({
        "Número Licitação": ["1"], "Código UG": ["100"], "Código Modalidade Compra": ["6"],
        "Número Processo": ["P1"], "Modalidade Compra": ["Pregão"], "Situação Licitação": ["Concluída"],
        "Objeto": ["Objeto"], "Valor Licitação": [1000.0],
        "Data Resultado Compra": pd.to_datetime(["2024-01-01"]),
        "Código UG_dup": ["100"],  # placeholder, sobrescrito abaixo
    })
    licitacoes = licitacoes.drop(columns=["Código UG_dup"])
    licitacoes["Nome UG"] = "UG Teste"
    licitacoes["Código Órgão"] = "20"
    licitacoes["Nome Órgão"] = "Órgão Teste"
    licitacoes["Código Órgão Superior"] = "10"
    licitacoes["Nome Órgão Superior"] = "Órgão Sup"
    licitacoes["UF"] = "DF"
    licitacoes["Município"] = "Brasília"

    itens = pd.DataFrame({
        "Número Licitação": ["1"], "Código UG": ["100"], "Código Modalidade Compra": ["6"],
        "Código Item Compra": ["1"], "Descrição": ["Produto Teste"],
        "Valor Item": [100.0], "Quantidade Item": [10],
        "Código Vencedor": ["11111111000100"], "Nome Vencedor": ["Fornecedor A"],
        "tipo_documento_vencedor": ["CNPJ"], "codigo_item_gerado": [False],
    })

    dim_tempo = gold.construir_dim_tempo(licitacoes)
    dim_orgao = gold.construir_dim_orgao(licitacoes)
    dim_fornecedor = gold.construir_dim_fornecedor(itens, pd.DataFrame({"Código Participante": [], "Nome Participante": []}))
    dim_produto = gold.construir_dim_produto(itens, pd.DataFrame({"Descrição Item Compra": []}))
    dim_licitacao = gold.construir_dim_licitacao(licitacoes)

    fato = gold.construir_fato_item(itens, licitacoes, dim_tempo, dim_orgao, dim_fornecedor, dim_produto, dim_licitacao)

    assert len(fato) == 1
    colunas_fk = ["sk_tempo", "sk_orgao", "sk_fornecedor", "sk_produto", "sk_licitacao"]
    assert fato[colunas_fk].isnull().sum().sum() == 0