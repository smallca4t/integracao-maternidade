import sqlite3
from contextlib import contextmanager
from pathlib import Path

CAMINHO_BANCO = Path(__file__).resolve().parent / "integracao.db"


@contextmanager
def conectar():
    conexao = sqlite3.connect(CAMINHO_BANCO)
    conexao.row_factory = sqlite3.Row
    try:
        yield conexao
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    finally:
        conexao.close()


def criar_tabela():
    with conectar() as conexao:
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS operacoes (
                id TEXT PRIMARY KEY,
                fluxo TEXT NOT NULL,
                chave_idempotencia TEXT UNIQUE NOT NULL,
                requisicao TEXT NOT NULL,
                resposta TEXT,
                status TEXT NOT NULL,
                erro TEXT,
                tentativas INTEGER NOT NULL DEFAULT 1,
                criado_em TEXT NOT NULL,
                atualizado_em TEXT NOT NULL
            )
        """)
