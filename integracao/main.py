import httpx

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="ArchCorp — Integração")

class FluxoF1(BaseModel):
    agendamento_id: str


@app.post("/fluxos/f1")
def executar_fluxo_f1(fluxo: FluxoF1):
    try:
        resposta_s1 = httpx.get(
            f"http://127.0.0.1:8001/agendamentos/{fluxo.agendamento_id}",
            timeout=5
        )
        resposta_s1.raise_for_status()

        agendamento = resposta_s1.json()

        resposta_s2 = httpx.post(
            "http://127.0.0.1:8002/atendimentos",
            json={
                "agendamento_id": agendamento["id"],
                "paciente": agendamento["paciente"]
            },
            timeout=5
        )
        resposta_s2.raise_for_status()

        atendimento = resposta_s2.json()

        resposta_s3 = httpx.post(
            "http://127.0.0.1:8003/registros-administrativos",
            json={
                "atendimento_id": atendimento["id"],
                "paciente": atendimento["paciente"]
            },
            timeout=5
        )
        resposta_s3.raise_for_status()

        registro_prontuario = resposta_s3.json()

        return {
            "fluxo": "F1",
            "status": "CONCLUIDO",
            "agendamento": agendamento,
            "atendimento": atendimento,
            "registro_prontuario": registro_prontuario
        }

    except httpx.HTTPStatusError as erro:
        raise HTTPException(
            status_code=erro.response.status_code,
            detail="O sistema de origem ou destino recusou a operação."
        )

    except httpx.RequestError as erro:
        raise HTTPException(
            status_code=503,
            detail=f"Não foi possível comunicar com um dos sistemas: {erro}"
        )


@app.get("/", response_class=HTMLResponse)
def painel():
    return """
    <html>
      <head>
        <title>ArchCorp — Maternidade Maria Luz</title>
        <style>
          body {
            font-family: Arial;
            background: #f4f7fb;
            color: #1f2937;
            margin: 0;
            padding: 40px;
          }

          h1 { margin-bottom: 8px; }
          .subtitulo { color: #5b6472; margin-top: 0; }

          .grade {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 18px;
            margin-top: 28px;
          }

          .card {
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 10px #0002;
            border-left: 6px solid #1769aa;
          }

          .integracao { border-left-color: #7c3aed; }
          .disponivel { color: #147a3d; font-weight: bold; }
          .planejado { color: #9a6700; font-weight: bold; }

          a {
            display: inline-block;
            margin-top: 12px;
            color: #1769aa;
            text-decoration: none;
            font-weight: bold;
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
            background: #7c3aed;
            color: white;
            cursor: pointer;
        }
        </style>
      </head>

      <script>
        async function executarF1() {
            const agendamento_id =
            document.getElementById("agendamentoId").value;

        const resposta = await fetch("/fluxos/f1", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agendamento_id })
        });

        const dados = await resposta.json();
        const mensagem = document.getElementById("mensagemF1");

        if (!resposta.ok) {
            mensagem.textContent =
                `Falha no F1: ${dados.detail}`;
            return;
        }

        mensagem.textContent =
            `Concluído: atendimento ${dados.atendimento.id} aberto para ` +
            `${dados.atendimento.paciente}.`;
        }
      </script>

      <body>
        <h1>ArchCorp — Maternidade Maria Luz</h1>
        <p class="subtitulo">
          Painel demonstrativo da arquitetura de integração hospitalar
        </p>

        <section class="grade">
          <article class="card integracao">
            <h2>Integração</h2>
            <p>Orquestra os fluxos F1, F2 e F3 entre os sistemas.</p>
            <p class="disponivel">● Serviço disponível</p>
          </article>

          <article class="card integracao">
            <h2>Fluxo F1</h2>
            <p>Enviar agendamento do S1 para abertura de atendimento no S2.</p>

            <input
                id="agendamentoId"
                placeholder="ID do agendamento do S1"
            >

            <button onclick="executarF1()">Executar F1</button>

            <p id="mensagemF1"></p>
        </article>

          <article class="card">
            <h2>S1 — Agendamento</h2>
            <p>SaaS simulado para registro de agendamentos.</p>
            <p class="disponivel">● Serviço disponível</p>
            <a href="http://127.0.0.1:8001" target="_blank">
              Abrir S1
            </a>
          </article>

          <article class="card">
            <h2>S2 — Atendimento</h2>
            <p>Recebe agendamentos e abre atendimentos.</p>
            <p class="disponivel">● Serviço disponível</p>
            <a href="http://127.0.0.1:8002" target="_blank">
                Abrir S2
            </a>
          </article>

          <article class="card">
            <h2>S3 — Prontuário Eletrônico do Paciente (PEP) </h2>
            <p>Prontuário eletrônico: adaptador hipotético.</p>
            <p class="disponivel">● Serviço disponível</p>
          </article>

          <article class="card">
            <h2>S4 — LIS</h2>
            <p>Laboratório: solicitações e resultados HL7 v2.</p>
            <p class="planejado">● Em construção</p>
          </article>

          <article class="card">
            <h2>S5 — Financeiro</h2>
            <p>Recebe itens faturáveis dos fluxos clínicos.</p>
            <p class="planejado">● Em construção</p>
          </article>
        </section>
      </body>
    </html>
    """