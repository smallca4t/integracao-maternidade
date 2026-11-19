import uuid
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .database import conectar, criar_tabela

app = FastAPI(title="S4 — LIS")


class PedidoExame(BaseModel):
    solicitacao_id: str
    atendimento_id: str
    paciente: str
    exame: str


@app.on_event("startup")
def iniciar_banco():
    criar_tabela()


def gerar_hl7(exame_id: str, pedido: PedidoExame, resultado: str) -> str:
    """Mensagem ORU^R01 mínima, usada somente para a demonstração acadêmica."""
    data_hora = datetime.now().strftime("%Y%m%d%H%M%S")
    return (
        f"MSH|^~\\&|LIS|MML|PEP|MML|{data_hora}||ORU^R01|{exame_id}|P|2.5\r"
        f"PID|||{pedido.paciente}||PACIENTE FICTICIO\r"
        f"OBR|1|{pedido.solicitacao_id}|{exame_id}|{pedido.exame}\r"
        f"OBX|1|ST|{pedido.exame}||{resultado}|N"
    )


@app.post("/exames")
def processar_exame(pedido: PedidoExame):
    with conectar() as conexao:
        existente = conexao.execute("""
            SELECT id, solicitacao_id, atendimento_id, paciente, exame, status,
                   resultado, hl7_v2, criado_em
            FROM exames WHERE solicitacao_id = ?
        """, (pedido.solicitacao_id,)).fetchone()
        if existente:
            return dict(existente)

        exame_id = str(uuid.uuid4())
        resultado = "Resultado demonstrativo: normal"
        registro = {
            "id": exame_id, "solicitacao_id": pedido.solicitacao_id,
            "atendimento_id": pedido.atendimento_id, "paciente": pedido.paciente,
            "exame": pedido.exame, "status": "LIBERADO", "resultado": resultado,
            "hl7_v2": gerar_hl7(exame_id, pedido, resultado),
            "criado_em": datetime.now().isoformat(timespec="seconds"),
        }
        conexao.execute("""
            INSERT INTO exames
            (id, solicitacao_id, atendimento_id, paciente, exame, status,
             resultado, hl7_v2, criado_em)
            VALUES (:id, :solicitacao_id, :atendimento_id, :paciente, :exame,
                    :status, :resultado, :hl7_v2, :criado_em)
        """, registro)
    return registro


@app.get("/exames")
def listar_exames():
    with conectar() as conexao:
        resultado = conexao.execute("SELECT * FROM exames ORDER BY criado_em DESC").fetchall()
    return [dict(item) for item in resultado]


@app.get("/", response_class=HTMLResponse)
def inicio():
    return """
    <html><head><title>S4 — LIS</title><style>
      body{font-family:Arial;background:#f4f7fb;padding:40px}.card{max-width:720px;background:white;border-radius:12px;padding:24px;box-shadow:0 2px 10px #0002}input,button{display:block;width:100%;box-sizing:border-box;margin-top:10px;padding:10px;border-radius:6px}input{border:1px solid #bbb}button{border:0;background:#b45309;color:white;cursor:pointer}.status{color:#147a3d;font-weight:bold}li{margin:12px 0;padding-bottom:12px;border-bottom:1px solid #ddd}
    </style></head><body><div class="card"><h1>S4 — LIS</h1><p><strong>Função:</strong> receber solicitações e liberar resultados laboratoriais.</p><p><strong>Formato representado:</strong> HL7 v2 simplificado.</p><p class="status">● Serviço disponível</p><h2>Liberar resultado demonstrativo</h2><input id="solicitacao" placeholder="ID da solicitação"><input id="atendimento" placeholder="ID do atendimento"><input id="paciente" placeholder="Nome da paciente"><input id="exame" placeholder="Exame, por exemplo: HEMOGRAMA"><button onclick="enviar()">Liberar resultado</button><p id="mensagem"></p><h2>Exames liberados</h2><ul id="lista"></ul></div><script>
      async function enviar(){const body={solicitacao_id:solicitacao.value,atendimento_id:atendimento.value,paciente:paciente.value,exame:exame.value};const r=await fetch('/exames',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();mensagem.textContent=r.ok?'Resultado liberado: '+d.id:'Falha: '+JSON.stringify(d.detail);carregar()}
      async function carregar(){const r=await fetch('/exames');const itens=await r.json();lista.innerHTML=itens.map(x=>`<li><strong>${x.exame}</strong> — ${x.paciente}<br>Resultado: ${x.resultado}<br>Status: ${x.status}</li>`).join('')};carregar()
    </script></body></html>
    """

