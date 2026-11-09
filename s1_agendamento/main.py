from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uuid
from .database import conectar, criar_tabela

app = FastAPI(title="S1 — Agendamento")

class Agendamento(BaseModel):
    paciente: str
    data_hora: str

@app.get("/", response_class=HTMLResponse)
def inicio():
    return """
    <html>
      <head>
        <title>S1 — Agendamento</title>
        <style>
          body {
            font-family: Arial;
            background: #f4f7fb;
            padding: 40px;
          }

          .card {
            max-width: 620px;
            background: white;
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 2px 10px #0002;
          }

          input, button {
            display: block;
            width: 100%;
            box-sizing: border-box;
            margin-top: 10px;
            padding: 10px;
            border-radius: 6px;
          }

          input { border: 1px solid #bbb; }
          button {
            border: 0;
            background: #1769aa;
            color: white;
            cursor: pointer;
          }

          .status { color: #147a3d; font-weight: bold; }
          li { margin: 8px 0; }
        </style>
      </head>

      <body>
        <div class="card">
          <h1>S1 — Agendamento</h1>

          <p><strong>Função:</strong> registrar agendamentos de pacientes.</p>
          <p><strong>Representação:</strong> SaaS em nuvem com exportação de dados.</p>
          <p class="status">● Serviço disponível</p>

          <h2>Novo agendamento</h2>

          <input id="paciente" placeholder="Nome da paciente">
          <input id="dataHora" type="datetime-local">
          <button onclick="criarAgendamento()">Registrar agendamento</button>

          <p id="mensagem"></p>

          <h2>Agendamentos registrados</h2>
          <ul id="lista"></ul>
        </div>

        <script>
          async function criarAgendamento() {
            const paciente = document.getElementById("paciente").value;
            const data_hora = document.getElementById("dataHora").value;

            const resposta = await fetch("/agendamentos", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ paciente, data_hora })
            });

            const dados = await resposta.json();

            document.getElementById("mensagem").textContent =
              `Agendamento registrado para ${dados.paciente}.`;

            document.getElementById("paciente").value = "";
            document.getElementById("dataHora").value = "";

            carregarAgendamentos();
          }

          async function carregarAgendamentos() {
            const resposta = await fetch("/agendamentos");
            const agendamentos = await resposta.json();

            document.getElementById("lista").innerHTML =
              agendamentos
                .map(item => `
                    <li>
                        <strong>${item.paciente}</strong> — ${item.data_hora}<br>
                        ID: ${item.id}<br>
                        Status: ${item.status}
                    </li>
                    `)
                .join("");
          }

          carregarAgendamentos();
        </script>
      </body>
    </html>
    """


@app.post("/agendamentos")
def criar_agendamento(agendamento: Agendamento):
    novo_agendamento = {
        "id": str(uuid.uuid4()),
        "paciente": agendamento.paciente,
        "data_hora": agendamento.data_hora,
        "status": "AGENDADO"
    }

    with conectar() as conexao:
        conexao.execute("""
            INSERT INTO agendamentos (id, paciente, data_hora, status)
            VALUES (:id, :paciente, :data_hora, :status)
        """, novo_agendamento)

    return novo_agendamento

@app.on_event("startup")
def iniciar_banco():
    criar_tabela()

@app.get("/agendamentos")
def listar_agendamentos():
    with conectar() as conexao:
        resultado = conexao.execute("""
            SELECT id, paciente, data_hora, status
            FROM agendamentos
            ORDER BY data_hora
        """).fetchall()

    return [dict(item) for item in resultado]

@app.get("/agendamentos/{agendamento_id}")
def buscar_agendamento(agendamento_id: str):
    with conectar() as conexao:
        resultado = conexao.execute("""
            SELECT id, paciente, data_hora, status
            FROM agendamentos
            WHERE id = ?
        """, (agendamento_id,)).fetchone()

    if resultado is None:
        raise HTTPException(
            status_code=404,
            detail="Agendamento não encontrado"
        )

    return dict(resultado)