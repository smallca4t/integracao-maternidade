import uuid
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .database import conectar, criar_tabela

app = FastAPI(title="S3 — Prontuário Eletrônico")


class RegistroAdministrativo(BaseModel):
    atendimento_id: str
    paciente: str


class RegistroLaboratorial(BaseModel):
    exame_id: str
    atendimento_id: str
    paciente: str
    exame: str
    resultado: str
    hl7_v2: str


@app.on_event("startup")
def iniciar_banco():
    criar_tabela()


@app.get("/", response_class=HTMLResponse)
def inicio():
    return """
    <html>
      <head>
        <title>S3 — Prontuário Eletrônico</title>
        <style>
          body {
            font-family: Arial;
            background: #f4f7fb;
            padding: 40px;
          }

          .card {
            max-width: 700px;
            background: white;
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 2px 10px #0002;
          }

          .status {
            color: #147a3d;
            font-weight: bold;
          }

          li {
            margin: 12px 0;
            padding-bottom: 12px;
            border-bottom: 1px solid #ddd;
          }
        </style>
      </head>

      <body>
        <div class="card">
          <h1>S3 — Prontuário Eletrônico</h1>

          <p>
            <strong>Função:</strong>
            receber registros administrativos e, futuramente,
            resultados laboratoriais.
          </p>

          <p>
            <strong>Observação acadêmica:</strong>
            esta é uma interface hipotética de integração; não representa
            uma API comprovadamente disponível em um prontuário real.
          </p>

          <p class="status">● Serviço disponível</p>

          <h2>Registros administrativos recebidos</h2>
          <ul id="lista"></ul>

          <h2>Resultados laboratoriais recebidos</h2>
          <ul id="listaLaboratorial"></ul>
        </div>

        <script>
          async function carregarRegistros() {
            const [respostaAdministrativa, respostaLaboratorial] = await Promise.all([
              fetch("/registros-administrativos"),
              fetch("/registros-laboratoriais")
            ]);

            const registros = await respostaAdministrativa.json();
            const registrosLaboratoriais = await respostaLaboratorial.json();

            document.getElementById("lista").innerHTML =
              registros.map(item => `
                <li>
                  <strong>${item.paciente}</strong><br>
                  Atendimento: ${item.atendimento_id}<br>
                  Tipo: ${item.tipo}<br>
                  Recebido em: ${item.criado_em}
                </li>
              `).join("");

            document.getElementById("listaLaboratorial").innerHTML =
              registrosLaboratoriais.map(item => `
                <li>
                  <strong>${item.exame}</strong> — ${item.paciente}<br>
                  Atendimento: ${item.atendimento_id}<br>
                  Resultado: ${item.resultado}<br>
                  Exame: ${item.exame_id}<br>
                  Recebido em: ${item.criado_em}
                </li>
              `).join("") || "<li>Nenhum resultado laboratorial recebido.</li>";
          }

          carregarRegistros();
        </script>
      </body>
    </html>
    """


@app.post("/registros-administrativos")
def receber_registro(registro: RegistroAdministrativo):
    with conectar() as conexao:
        existente = conexao.execute("""
            SELECT id, atendimento_id, paciente, tipo, criado_em
            FROM registros_administrativos
            WHERE atendimento_id = ?
        """, (registro.atendimento_id,)).fetchone()

        if existente:
            return dict(existente)

        novo_registro = {
            "id": str(uuid.uuid4()),
            "atendimento_id": registro.atendimento_id,
            "paciente": registro.paciente,
            "tipo": "ADMINISTRATIVO",
            "criado_em": datetime.now().isoformat(timespec="seconds")
        }

        conexao.execute("""
            INSERT INTO registros_administrativos
            (id, atendimento_id, paciente, tipo, criado_em)
            VALUES (:id, :atendimento_id, :paciente, :tipo, :criado_em)
        """, novo_registro)

    return novo_registro


@app.get("/registros-administrativos")
def listar_registros():
    with conectar() as conexao:
        resultado = conexao.execute("""
            SELECT id, atendimento_id, paciente, tipo, criado_em
            FROM registros_administrativos
            ORDER BY criado_em DESC
        """).fetchall()

    return [dict(item) for item in resultado]


@app.post("/registros-laboratoriais")
def receber_resultado_laboratorial(registro: RegistroLaboratorial):
    with conectar() as conexao:
        existente = conexao.execute("""
            SELECT * FROM registros_laboratoriais WHERE exame_id = ?
        """, (registro.exame_id,)).fetchone()
        if existente:
            return dict(existente)

        novo_registro = {
            "id": str(uuid.uuid4()),
            **registro.model_dump(),
            "criado_em": datetime.now().isoformat(timespec="seconds"),
        }
        conexao.execute("""
            INSERT INTO registros_laboratoriais
            (id, exame_id, atendimento_id, paciente, exame, resultado, hl7_v2, criado_em)
            VALUES (:id, :exame_id, :atendimento_id, :paciente, :exame,
                    :resultado, :hl7_v2, :criado_em)
        """, novo_registro)
    return novo_registro


@app.get("/registros-laboratoriais")
def listar_registros_laboratoriais():
    with conectar() as conexao:
        resultado = conexao.execute("""
            SELECT * FROM registros_laboratoriais ORDER BY criado_em DESC
        """).fetchall()
    return [dict(item) for item in resultado]
