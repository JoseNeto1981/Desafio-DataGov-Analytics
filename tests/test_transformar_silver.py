"""
Testes de transformar_silver.py.

Cobrem as funções auxiliares de conversão e as regras de tratamento por
dataset, usando DataFrames sintéticos pequenos (não os dados reais) --
cada teste isola exatamente a regra que verifica.
"""

import pandas as pd

import transformar_silver as silver


# ----------------------------------------------------------------------------
# Funções auxiliares de conversão
# ----------------------------------------------------------------------------

def test_converter_valor_brl_com_separador_de_milhar():
    serie = pd.Series(["1.234,56", "10,00", "0,00"])
    resultado = silver.converter_valor_brl(serie)
    assert resultado.tolist() == [1234.56, 10.0, 0.0]


def test_converter_data_br_valida_e_invalida():
    serie = pd.Series(["01/01/2024", "31/12/2024", "data_invalida", None])
    resultado = silver.converter_data_br(serie)
    assert resultado.iloc[0] == pd.Timestamp("2024-01-01")
    assert resultado.iloc[1] == pd.Timestamp("2024-12-31")
    assert pd.isna(resultado.iloc[2])  # texto que não é data -> NaT, não erro
    assert pd.isna(resultado.iloc[3])


def test_padronizar_texto_remove_espacos_extras():
    serie = pd.Series(["  Texto  com   espaços  ", "Normal"])
    resultado = silver.padronizar_texto(serie)
    assert resultado.tolist() == ["Texto com espaços", "Normal"]


# ----------------------------------------------------------------------------
# tratar_licitacoes
# ----------------------------------------------------------------------------

def _licitacao_minima(**overrides) -> pd.DataFrame:
    base = {
        "Nome UG": ["UG Teste"], "Modalidade Compra": ["Pregão"], "Objeto": ["Objeto"],
        "Situação Licitação": ["Concluída"], "Nome Órgão Superior": ["Órgão Sup"],
        "Nome Órgão": ["Órgão"], "Município": ["Brasília"], "UF": ["DF"],
        "Valor Licitação": ["1000,00"], "Data Resultado Compra": ["01/01/2024"],
        "Data Abertura": ["01/01/2024"],
    }
    base.update(overrides)
    return pd.DataFrame(base)


def test_tratar_licitacoes_uf_invalida_e_zerada_mas_linha_e_mantida():
    df = _licitacao_minima(UF=["-3"])
    resultado, relatorio = silver.tratar_licitacoes(df)

    assert relatorio.uf_invalida_corrigida == 1
    assert len(resultado) == 1  # linha não é descartada
    assert pd.isna(resultado["UF"].iloc[0])


def test_tratar_licitacoes_valor_negativo_e_removido():
    df = _licitacao_minima(**{"Valor Licitação": ["-500,00"]})
    resultado, relatorio = silver.tratar_licitacoes(df)

    assert relatorio.valores_negativos_removidos == 1
    assert len(resultado) == 0


def test_tratar_licitacoes_duplicados_exatos_sao_removidos():
    linha = _licitacao_minima()
    df = pd.concat([linha, linha], ignore_index=True)  # 2 linhas idênticas

    resultado, relatorio = silver.tratar_licitacoes(df)

    assert relatorio.duplicados_removidos == 1
    assert len(resultado) == 1


# ----------------------------------------------------------------------------
# tratar_itens -- inclui teste de REGRESSÃO do bug de ordem de operações
# ----------------------------------------------------------------------------

def _item_minimo(**overrides) -> pd.DataFrame:
    base = {
        "Descrição": ["Produto Teste"], "Nome Vencedor": ["Fornecedor Teste"],
        "Código Item Compra": ["1"], "Valor Item": ["100,00"],
        "Quantidade Item": ["10"], "Código Vencedor": ["12345678000199"],
    }
    base.update(overrides)
    return pd.DataFrame(base)


def test_tratar_itens_sem_codigo_gera_chave_substituta():
    df = _item_minimo(**{"Código Item Compra": [None]})
    resultado, relatorio = silver.tratar_itens(df)

    assert relatorio.codigo_item_gerado == 1
    assert resultado["Código Item Compra"].iloc[0].startswith("SEM_CODIGO_")
    assert resultado["codigo_item_gerado"].iloc[0] == True  # noqa: E712


def test_tratar_itens_duplicatas_sem_codigo_sao_detectadas_antes_da_chave_substituta():
    """
    Teste de regressão: a primeira versão deste script gerava a chave
    substituta (SEM_CODIGO_<índice>) ANTES de remover duplicados. Como cada
    linha tem um índice diferente, duas linhas idênticas (mesma licitação,
    mesmo valor, ambas sem Código Item Compra) deixavam de ser reconhecidas
    como duplicatas -- silenciosamente inflando a contagem de itens.

    Este teste replica exatamente esse cenário: duas linhas idênticas, ambas
    com Código Item Compra nulo. O resultado correto é 1 linha (duplicata
    removida), não 2.
    """
    linha = _item_minimo(**{"Código Item Compra": [None]})
    df = pd.concat([linha, linha], ignore_index=True)

    resultado, relatorio = silver.tratar_itens(df)

    assert relatorio.duplicados_removidos == 1, (
        "Duplicata com Código Item Compra nulo não foi detectada -- "
        "verifique se a deduplicação ainda acontece ANTES da geração da chave substituta."
    )
    assert len(resultado) == 1
    assert relatorio.codigo_item_gerado == 1  # só 1 linha restante precisa da chave


def test_tratar_itens_valor_negativo_e_removido():
    df = _item_minimo(**{"Valor Item": ["-50,00"]})
    resultado, relatorio = silver.tratar_itens(df)

    assert relatorio.valores_negativos_removidos == 1
    assert len(resultado) == 0


def test_tratar_itens_classifica_tipo_documento():
    df = pd.concat([
        _item_minimo(**{"Código Item Compra": ["1"], "Código Vencedor": ["12345678000199"]}),  # CNPJ, 14 díg.
        _item_minimo(**{"Código Item Compra": ["2"], "Código Vencedor": ["12345678901"]}),      # CPF, 11 díg.
    ], ignore_index=True)

    resultado, _ = silver.tratar_itens(df)

    assert resultado["tipo_documento_vencedor"].tolist() == ["CNPJ", "CPF"]


# ----------------------------------------------------------------------------
# tratar_participantes
# ----------------------------------------------------------------------------

def _participante_minimo(**overrides) -> pd.DataFrame:
    base = {
        "Nome Participante": ["Fornecedor Teste"], "Código Participante": ["12345678000199"],
        "Flag Vencedor": ["SIM"],
    }
    base.update(overrides)
    return pd.DataFrame(base)


def test_tratar_participantes_codigo_invalido_e_zerado():
    df = _participante_minimo(**{"Código Participante": ["-11"]})
    resultado, relatorio = silver.tratar_participantes(df)

    assert relatorio.participante_invalido_corrigido == 1
    assert pd.isna(resultado["Código Participante"].iloc[0])


def test_tratar_participantes_fornecedor_estrangeiro_nao_e_tratado_como_erro():
    df = _participante_minimo(**{"Código Participante": ["ESTRANG0032850"]})
    resultado, relatorio = silver.tratar_participantes(df)

    assert relatorio.participante_estrangeiro == 1
    assert relatorio.participante_invalido_corrigido == 0
    assert resultado["Código Participante"].iloc[0] == "ESTRANG0032850"  # mantido, não zerado


def test_tratar_participantes_flag_vencedor_vira_booleano():
    df = pd.concat([
        _participante_minimo(**{"Flag Vencedor": ["SIM"]}),
        _participante_minimo(**{"Flag Vencedor": ["NÃO"]}),
    ], ignore_index=True)

    resultado, _ = silver.tratar_participantes(df)

    assert resultado["flag_vencedor"].tolist() == [True, False]