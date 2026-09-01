"""
Testes de ingestao_bronze.py.

Cobrem: reconhecimento de nome de arquivo, validação de schema, cálculo de
checksum, e o comportamento fim-a-fim de processar_arquivo (sucesso, schema
inválido, reprocessamento idempotente).
"""

import json

import pandas as pd
import pytest

import ingestao_bronze as bronze


# ----------------------------------------------------------------------------
# Padrão de nome de arquivo
# ----------------------------------------------------------------------------

@pytest.mark.parametrize("nome,deve_casar", [
    ("202401_Licitação.csv", True),
    ("202412_ItemLicitação.csv", True),
    ("Licitação.csv", False),          # sem prefixo AAAAMM
    ("202401_Licitação.txt", False),   # extensão errada
    ("2024_Licitação.csv", False),     # ano+mês incompletos
])
def test_padrao_nome_arquivo(nome, deve_casar):
    resultado = bronze.PADRAO_NOME_ARQUIVO.match(nome)
    assert (resultado is not None) == deve_casar


# ----------------------------------------------------------------------------
# Validação de colunas obrigatórias
# ----------------------------------------------------------------------------

def test_validar_colunas_todas_presentes():
    cabecalho = ["Número Licitação", "Código UG", "Código Órgão", "UF", "Valor Licitação", "Extra"]
    faltando = bronze.validar_colunas("Licitação", cabecalho)
    assert faltando == []


def test_validar_colunas_uma_faltando():
    cabecalho = ["Número Licitação", "Código UG", "Código Órgão", "Valor Licitação"]  # falta UF
    faltando = bronze.validar_colunas("Licitação", cabecalho)
    assert faltando == ["UF"]


# ----------------------------------------------------------------------------
# Checksum
# ----------------------------------------------------------------------------

def test_calcular_sha256_e_deterministico(tmp_path):
    arquivo = tmp_path / "teste.csv"
    arquivo.write_text("a;b;c\n1;2;3\n", encoding="latin1")

    hash1 = bronze.calcular_sha256(arquivo)
    hash2 = bronze.calcular_sha256(arquivo)
    assert hash1 == hash2


def test_calcular_sha256_muda_com_conteudo_diferente(tmp_path):
    arquivo1 = tmp_path / "a.csv"
    arquivo2 = tmp_path / "b.csv"
    arquivo1.write_text("a;b\n1;2\n", encoding="latin1")
    arquivo2.write_text("a;b\n9;9\n", encoding="latin1")

    assert bronze.calcular_sha256(arquivo1) != bronze.calcular_sha256(arquivo2)


# ----------------------------------------------------------------------------
# processar_arquivo -- fim a fim, usando pastas temporárias
# ----------------------------------------------------------------------------

def _escrever_csv_licitacao_valido(caminho, linhas: int = 2):
    colunas = [
        "Número Licitação", "Código UG", "Nome UG", "Código Modalidade Compra",
        "Modalidade Compra", "Número Processo", "Objeto", "Situação Licitação",
        "Código Órgão Superior", "Nome Órgão Superior", "Código Órgão", "Nome Órgão",
        "UF", "Município", "Data Resultado Compra", "Data Abertura", "Valor Licitação",
    ]
    linha_exemplo = ["1", "100", "UG Teste", "6", "Pregão", "P1", "Objeto teste",
                      "Concluída", "10", "Órgão Sup", "20", "Órgão Teste", "DF",
                      "Brasília", "01/01/2024", "01/01/2024", "1000,00"]
    conteudo = ";".join(colunas) + "\n"
    for _ in range(linhas):
        conteudo += ";".join(linha_exemplo) + "\n"
    caminho.write_text(conteudo, encoding="latin1")


def test_processar_arquivo_sucesso(tmp_path, monkeypatch):
    landing = tmp_path / "dados_brutos"
    bronze_dir = tmp_path / "bronze"
    landing.mkdir()
    monkeypatch.setattr(bronze, "BRONZE_DIR", bronze_dir)

    arquivo = landing / "202401_Licitação.csv"
    _escrever_csv_licitacao_valido(arquivo, linhas=2)

    resultado = bronze.processar_arquivo(arquivo)

    assert resultado.status == "sucesso"
    assert resultado.linhas == 2
    destino = bronze_dir / "licitacoes" / "ano=2024" / "mes=01" / arquivo.name
    assert destino.exists()

    manifesto = json.loads((bronze_dir / "licitacoes" / "ano=2024" / "mes=01" / f"_manifest_{arquivo.stem}.json").read_text())
    assert manifesto["linhas"] == 2
    assert manifesto["status"] == "sucesso"


def test_processar_arquivo_schema_invalido_nao_promove_para_bronze(tmp_path, monkeypatch):
    landing = tmp_path / "dados_brutos"
    bronze_dir = tmp_path / "bronze"
    landing.mkdir()
    monkeypatch.setattr(bronze, "BRONZE_DIR", bronze_dir)

    arquivo = landing / "202401_Licitação.csv"
    # CSV sem a coluna obrigatória "UF"
    arquivo.write_text("Número Licitação;Código UG;Valor Licitação\n1;100;1000,00\n", encoding="latin1")

    resultado = bronze.processar_arquivo(arquivo)

    assert resultado.status == "erro_validacao"
    # Nada deve ter sido criado na bronze
    assert not (bronze_dir / "licitacoes").exists()


def test_processar_arquivo_reprocessamento_e_idempotente(tmp_path, monkeypatch):
    landing = tmp_path / "dados_brutos"
    bronze_dir = tmp_path / "bronze"
    landing.mkdir()
    monkeypatch.setattr(bronze, "BRONZE_DIR", bronze_dir)

    arquivo = landing / "202401_Licitação.csv"
    _escrever_csv_licitacao_valido(arquivo, linhas=3)

    resultado1 = bronze.processar_arquivo(arquivo)
    resultado2 = bronze.processar_arquivo(arquivo)

    # Rodar duas vezes não deve mudar o resultado nem duplicar dados --
    # o arquivo de destino é sempre o mesmo caminho, sobrescrito.
    assert resultado1.linhas == resultado2.linhas == 3
    destino = bronze_dir / "licitacoes" / "ano=2024" / "mes=01" / arquivo.name
    df_destino = pd.read_csv(destino, encoding="latin1", sep=";")
    assert len(df_destino) == 3