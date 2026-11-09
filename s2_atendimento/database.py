import sqlite3
from pathlib import Path

CAMINHO_BANCO = Path(__file__).resolve().parent / "atendimento.db"


def conectar():
    conexao = sqlite3.connect(CAMINHO_BANCO)
    conexao.row_factory = sqlite3.Row
    return conexao


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