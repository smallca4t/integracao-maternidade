import sqlite3
from contextlib import contextmanager
from pathlib import Path

CAMINHO_BANCO = Path(__file__).resolve().parent / "atendimento.db"


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
            CREATE TABLE IF NOT EXISTS atendimentos (
                id TEXT PRIMARY KEY,
                agendamento_id TEXT NOT NULL,
                paciente TEXT NOT NULL,
                status TEXT NOT NULL
            )
        """)
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS solicitacoes_exame (
                id TEXT PRIMARY KEY,
                atendimento_id TEXT NOT NULL,
                paciente TEXT NOT NULL,
                exame TEXT NOT NULL,
                status TEXT NOT NULL,
                UNIQUE(atendimento_id, exame)
            )
        """)
