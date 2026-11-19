import sqlite3
from contextlib import contextmanager
from pathlib import Path

CAMINHO_BANCO = Path(__file__).resolve().parent / "prontuario.db"


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
            CREATE TABLE IF NOT EXISTS registros_administrativos (
                id TEXT PRIMARY KEY,
                atendimento_id TEXT UNIQUE NOT NULL,
                paciente TEXT NOT NULL,
                tipo TEXT NOT NULL,
                criado_em TEXT NOT NULL
            )
        """)
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS registros_laboratoriais (
                id TEXT PRIMARY KEY,
                exame_id TEXT UNIQUE NOT NULL,
                atendimento_id TEXT NOT NULL,
                paciente TEXT NOT NULL,
                exame TEXT NOT NULL,
                resultado TEXT NOT NULL,
                hl7_v2 TEXT NOT NULL,
                criado_em TEXT NOT NULL
            )
        """)
