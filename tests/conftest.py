"""
Configuração compartilhada dos testes.

Os scripts do pipeline (ingestao_bronze.py, transformar_silver.py,
transformar_gold.py) ficam na raiz do projeto, não dentro de um pacote
Python formal. Este conftest garante que a raiz do projeto esteja no
sys.path, para que `import ingestao_bronze` funcione independente de onde
o pytest for chamado.
"""

import sys
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))