import uuid
import httpx

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .database import conectar, criar_tabela

app = FastAPI(title="S2 — Atendimento")


class AtendimentoEntrada(BaseModel):
    agendamento_id: str
    paciente: str


class SolicitacaoExameEntrada(BaseModel):
    atendimento_id: str
    exame: str


class ExameIntegracaoEntrada(BaseModel):
    exame: str


@app.on_event("startup")
def iniciar_banco():
    criar_tabela()


@app.get("/", response_class=HTMLResponse)
def inicio():
    return """
    <html>
      <head>
        <title>S2 — Atendimento</title>
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
            background: #0f766e;
            color: white;
            cursor: pointer;
          }

          .status { color: #147a3d; font-weight: bold; }
          li { margin: 10px 0; }
        </style>
      </head>

      <body>
        <div class="card">
          <h1>S2 — Atendimento</h1>
          <p><strong>Função:</strong> abrir atendimentos a partir de agendamentos.</p>
          <p><strong>Representação:</strong> sistema local de atendimento.</p>
          <p class="status">● Serviço disponível</p>

          <h2>Abrir atendimento</h2>

          <input id="agendamentoId" placeholder="ID do agendamento">
          <input id="paciente" placeholder="Nome da paciente">
          <button onclick="abrirAtendimento()">Abrir atendimento</button>

          <p id="mensagem"></p>

          <h2>Atendimentos abertos</h2>
          <ul id="lista"></ul>
        </div>

        <script>
          async function abrirAtendimento() {
            const agendamento_id =
              document.getElementById("agendamentoId").value;

            const paciente =
              document.getElementById("paciente").value;

            const resposta = await fetch("/atendimentos", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ agendamento_id, paciente })
            });

            const dados = await resposta.json();

            document.getElementById("mensagem").textContent =
              `Atendimento aberto: ${dados.id}`;

            document.getElementById("agendamentoId").value = "";
            document.getElementById("paciente").value = "";

            carregarAtendimentos();
          }

          async function carregarAtendimentos() {
            const resposta = await fetch("/atendimentos");
            const atendimentos = await resposta.json();

            document.getElementById("lista").innerHTML =
              atendimentos.map(item => `
                <li>
                  <strong>${item.paciente}</strong><br>
                  Atendimento: ${item.id}<br>
                  Agendamento de origem: ${item.agendamento_id}<br>
                  Status: ${item.status}<br>
                  <button onclick="enviarExame('${item.id}')">
                    Solicitar exame pela Integração (F2)
                  </button>
                </li>
              `).join("");
          }

          async function enviarExame(atendimentoId) {
            const exame = prompt("Qual exame deseja solicitar?");
            if (!exame) return;

            const resposta = await fetch(
              `/atendimentos/${atendimentoId}/enviar-exame-integracao`,
              {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ exame })
              }
            );

            const dados = await resposta.json();
            document.getElementById("mensagem").textContent = resposta.ok
              ? `F2 concluído. Exame: ${dados.operacao.exame.id}`
              : `Falha ao integrar: ${dados.detail}`;
          }

          carregarAtendimentos();
        </script>
      </body>
    </html>
    """


@app.post("/atendimentos")
def abrir_atendimento(entrada: AtendimentoEntrada):
    with conectar() as conexao:
        existente = conexao.execute("""
            SELECT id, agendamento_id, paciente, status
            FROM atendimentos
            WHERE agendamento_id = ?
        """, (entrada.agendamento_id,)).fetchone()

        if existente:
            return dict(existente)

        atendimento = {
            "id": str(uuid.uuid4()),
            "agendamento_id": entrada.agendamento_id,
            "paciente": entrada.paciente,
            "status": "ABERTO"
        }

        conexao.execute("""
            INSERT INTO atendimentos (id, agendamento_id, paciente, status)
            VALUES (:id, :agendamento_id, :paciente, :status)
        """, atendimento)

    return atendimento


@app.get("/atendimentos")
def listar_atendimentos():
    with conectar() as conexao:
        resultado = conexao.execute("""
            SELECT id, agendamento_id, paciente, status
            FROM atendimentos
        """).fetchall()

    return [dict(item) for item in resultado]


@app.post("/solicitacoes-exame")
def solicitar_exame(entrada: SolicitacaoExameEntrada):
    with conectar() as conexao:
        atendimento = conexao.execute("""
            SELECT id, paciente FROM atendimentos WHERE id = ?
        """, (entrada.atendimento_id,)).fetchone()
        if not atendimento:
            raise HTTPException(404, "Atendimento não encontrado.")

        existente = conexao.execute("""
            SELECT id, atendimento_id, paciente, exame, status
            FROM solicitacoes_exame WHERE atendimento_id = ? AND exame = ?
        """, (entrada.atendimento_id, entrada.exame)).fetchone()
        if existente:
            return dict(existente)

        solicitacao = {
            "id": str(uuid.uuid4()),
            "atendimento_id": entrada.atendimento_id,
            "paciente": atendimento["paciente"],
            "exame": entrada.exame,
            "status": "SOLICITADO",
        }
        conexao.execute("""
            INSERT INTO solicitacoes_exame (id, atendimento_id, paciente, exame, status)
            VALUES (:id, :atendimento_id, :paciente, :exame, :status)
        """, solicitacao)
    return solicitacao


@app.get("/solicitacoes-exame")
def listar_solicitacoes_exame():
    with conectar() as conexao:
        resultado = conexao.execute("""
            SELECT id, atendimento_id, paciente, exame, status
            FROM solicitacoes_exame
        """).fetchall()
    return [dict(item) for item in resultado]


@app.post("/atendimentos/{atendimento_id}/enviar-exame-integracao")
def enviar_exame_para_integracao(atendimento_id: str, entrada: ExameIntegracaoEntrada):
    with conectar() as conexao:
        atendimento = conexao.execute("""
            SELECT id FROM atendimentos WHERE id = ?
        """, (atendimento_id,)).fetchone()
    if not atendimento:
        raise HTTPException(404, "Atendimento não encontrado.")

    try:
        resposta = httpx.post(
            "http://127.0.0.1:8000/fluxos/f2",
            json={"atendimento_id": atendimento_id, "exame": entrada.exame},
            timeout=5,
        )
        resposta.raise_for_status()
        return {"operacao": resposta.json()}
    except httpx.HTTPError as erro:
        raise HTTPException(503, "A Integração não está disponível para executar o F2.") from erro
