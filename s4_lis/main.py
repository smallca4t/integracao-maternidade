import uuid
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .database import conectar, criar_tabela

app = FastAPI(title="S4 — LIS")


class SolicitacaoLIS(BaseModel):
    solicitacao_id: str
    atendimento_id: str
    paciente: str
    exame: str


class ResultadoEntrada(BaseModel):
    resultado: str


@app.on_event("startup")
def iniciar_banco():
    criar_tabela()


def gerar_hl7(exame_id: str, solicitacao: dict, resultado: str) -> str:
    """Mensagem ORU^R01 mínima; representa somente o resultado liberado."""
    data_hora = datetime.now().strftime("%Y%m%d%H%M%S")
    return (
        f"MSH|^~\\&|LIS|MML|PEP|MML|{data_hora}||ORU^R01|{exame_id}|P|2.5\r"
        f"PID|||{solicitacao['paciente']}||PACIENTE FICTICIO\r"
        f"OBR|1|{solicitacao['solicitacao_id']}|{exame_id}|{solicitacao['exame']}\r"
        f"OBX|1|ST|{solicitacao['exame']}||{resultado}|N"
    )


@app.post("/solicitacoes")
def receber_solicitacao(solicitacao: SolicitacaoLIS):
    with conectar() as conexao:
        existente = conexao.execute("""
            SELECT * FROM solicitacoes_laboratoriais WHERE solicitacao_id = ?
        """, (solicitacao.solicitacao_id,)).fetchone()
        if existente:
            return dict(existente)

        registro = {**solicitacao.model_dump(), "status": "RECEBIDO",
                    "criado_em": datetime.now().isoformat(timespec="seconds")}
        conexao.execute("""
            INSERT INTO solicitacoes_laboratoriais
            (solicitacao_id, atendimento_id, paciente, exame, status, criado_em)
            VALUES (:solicitacao_id, :atendimento_id, :paciente, :exame, :status, :criado_em)
        """, registro)
    return registro


@app.get("/solicitacoes")
def listar_solicitacoes():
    with conectar() as conexao:
        itens = conexao.execute("""
            SELECT * FROM solicitacoes_laboratoriais ORDER BY criado_em DESC
        """).fetchall()
    return [dict(item) for item in itens]


@app.post("/solicitacoes/{solicitacao_id}/iniciar-analise")
def iniciar_analise(solicitacao_id: str):
    with conectar() as conexao:
        solicitacao = conexao.execute("""
            SELECT * FROM solicitacoes_laboratoriais WHERE solicitacao_id = ?
        """, (solicitacao_id,)).fetchone()
        if not solicitacao:
            raise HTTPException(404, "Solicitação não encontrada no LIS.")
        solicitacao = dict(solicitacao)
        if solicitacao["status"] == "RECEBIDO":
            conexao.execute("""
                UPDATE solicitacoes_laboratoriais SET status = 'EM_ANALISE'
                WHERE solicitacao_id = ?
            """, (solicitacao_id,))
            solicitacao["status"] = "EM_ANALISE"
    return solicitacao


@app.post("/solicitacoes/{solicitacao_id}/liberar-resultado")
def liberar_resultado(solicitacao_id: str, entrada: ResultadoEntrada):
    with conectar() as conexao:
        solicitacao = conexao.execute("""
            SELECT * FROM solicitacoes_laboratoriais WHERE solicitacao_id = ?
        """, (solicitacao_id,)).fetchone()
        if not solicitacao:
            raise HTTPException(404, "Solicitação não encontrada no LIS.")
        solicitacao = dict(solicitacao)

        existente = conexao.execute("""
            SELECT * FROM exames WHERE solicitacao_id = ?
        """, (solicitacao_id,)).fetchone()
        if existente:
            exame = dict(existente)
        else:
            if solicitacao["status"] != "EM_ANALISE":
                raise HTTPException(409, "Inicie a análise antes de liberar o resultado.")
            exame_id = str(uuid.uuid4())
            exame = {
                "id": exame_id, "solicitacao_id": solicitacao_id,
                "atendimento_id": solicitacao["atendimento_id"],
                "paciente": solicitacao["paciente"], "exame": solicitacao["exame"],
                "status": "RESULTADO_LIBERADO", "resultado": entrada.resultado,
                "hl7_v2": gerar_hl7(exame_id, solicitacao, entrada.resultado),
                "criado_em": datetime.now().isoformat(timespec="seconds"),
            }
            conexao.execute("""
                INSERT INTO exames
                (id, solicitacao_id, atendimento_id, paciente, exame, status,
                 resultado, hl7_v2, criado_em)
                VALUES (:id, :solicitacao_id, :atendimento_id, :paciente, :exame,
                        :status, :resultado, :hl7_v2, :criado_em)
            """, exame)
            conexao.execute("""
                UPDATE solicitacoes_laboratoriais SET status = 'RESULTADO_LIBERADO'
                WHERE solicitacao_id = ?
            """, (solicitacao_id,))

    try:
        resposta = httpx.post(
            "http://127.0.0.1:8000/eventos/resultados-laboratoriais",
            json={"atendimento_id": exame["atendimento_id"], "hl7_v2": exame["hl7_v2"]},
            timeout=5,
        )
        resposta.raise_for_status()
        return {"exame": exame, "integracao": resposta.json()}
    except httpx.HTTPError as erro:
        return {"exame": exame, "integracao": {"status": "FALHOU", "mensagem": str(erro)}}


@app.get("/exames")
def listar_exames():
    with conectar() as conexao:
        itens = conexao.execute("SELECT * FROM exames ORDER BY criado_em DESC").fetchall()
    return [dict(item) for item in itens]


@app.get("/", response_class=HTMLResponse)
def inicio():
    return """
    <html><head><title>S4 — LIS</title><style>
      body{font-family:Arial;background:#f4f7fb;padding:40px}.card{max-width:760px;background:white;border-radius:12px;padding:24px;box-shadow:0 2px 10px #0002}.status{color:#147a3d;font-weight:bold}button{margin-top:8px;padding:9px;border:0;border-radius:6px;background:#b45309;color:white;cursor:pointer}li{margin:12px 0;padding-bottom:12px;border-bottom:1px solid #ddd}.muted{color:#5b6472}
    </style></head><body><div class="card"><h1>S4 — LIS</h1><p><strong>Função:</strong> receber solicitações, realizar análise e liberar resultados laboratoriais.</p><p><strong>Formato representado:</strong> o HL7 v2 simplificado é gerado somente quando o resultado é liberado.</p><p class="status">● Serviço disponível</p><h2>Solicitações recebidas</h2><ul id="solicitacoes"></ul><h2>Resultados liberados</h2><ul id="exames"></ul></div><script>
      async function iniciarAnalise(id){await fetch(`/solicitacoes/${id}/iniciar-analise`,{method:'POST'});carregar()}
      async function liberar(id){const resultado=prompt('Informe o resultado demonstrativo:','Normal');if(!resultado)return;const r=await fetch(`/solicitacoes/${id}/liberar-resultado`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({resultado})});const d=await r.json();alert(r.ok?'Resultado liberado e encaminhado à Integração.':'Falha: '+JSON.stringify(d.detail));carregar()}
      async function carregar(){const [a,b]=await Promise.all([fetch('/solicitacoes'),fetch('/exames')]);const pedidos=await a.json(),exames=await b.json();document.getElementById('solicitacoes').innerHTML=pedidos.map(x=>`<li><strong>${x.exame}</strong> — ${x.paciente}<br>Solicitação: ${x.solicitacao_id}<br>Atendimento: ${x.atendimento_id}<br>Status: ${x.status}<br>${x.status==='RECEBIDO'?`<button onclick="iniciarAnalise('${x.solicitacao_id}')">Iniciar análise</button>`:''}${x.status==='EM_ANALISE'?`<button onclick="liberar('${x.solicitacao_id}')">Liberar resultado</button>`:''}</li>`).join('')||'<li class="muted">Nenhuma solicitação recebida.</li>';document.getElementById('exames').innerHTML=exames.map(x=>`<li><strong>${x.exame}</strong> — ${x.paciente}<br>Solicitação: ${x.solicitacao_id}<br>Exame: ${x.id}<br>Resultado: ${x.resultado}<br>Status: ${x.status}</li>`).join('')||'<li class="muted">Nenhum resultado liberado.</li>'};carregar()
    </script></body></html>
    """
