import sqlite3
from contextlib import contextmanager
from pathlib import Path

CAMINHO_BANCO = Path(__file__).resolve().parent / "financeiro.db"


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
            CREATE TABLE IF NOT EXISTS itens_faturaveis (
                id TEXT PRIMARY KEY,
                origem TEXT NOT NULL,
                referencia_id TEXT NOT NULL,
                paciente TEXT NOT NULL,
                descricao TEXT NOT NULL,
                valor REAL NOT NULL,
                status TEXT NOT NULL,
                criado_em TEXT NOT NULL,
                UNIQUE(origem, referencia_id)
            )
        """)

