import sqlite3
from pathlib import Path

CAMINHO_BANCO = Path(__file__).resolve().parent / "prontuario.db"


def conectar():
    conexao = sqlite3.connect(CAMINHO_BANCO)
    conexao.row_factory = sqlite3.Row
    return conexao


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