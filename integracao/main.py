import json
import uuid
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .database import conectar, criar_tabela

app = FastAPI(title="ArchCorp — Integração")


class FluxoF1(BaseModel):
    agendamento_id: str


class FluxoF2(BaseModel):
    atendimento_id: str
    exame: str


class FluxoF3(BaseModel):
    origem: str
    referencia_id: str
    paciente: str
    descricao: str
    valor: float = Field(gt=0)


@app.on_event("startup")
def iniciar_banco():
    criar_tabela()


def chamar_servico(metodo: str, url: str, dados: dict | None = None) -> dict:
    """Usa contratos HTTP; a integração não acessa bancos de outros serviços."""
    try:
        resposta = httpx.request(metodo, url, json=dados, timeout=5)
        resposta.raise_for_status()
        return resposta.json()
    except httpx.HTTPStatusError as erro:
        raise RuntimeError(f"O serviço recusou a operação ({erro.response.status_code}).") from erro
    except httpx.RequestError as erro:
        raise RuntimeError(f"Serviço indisponível: {erro.request.url}.") from erro


def interpretar_hl7(mensagem: str) -> dict:
    """Lê MSH/PID/OBR/OBX do subconjunto HL7 didático gerado pelo S4."""
    segmentos = {
        partes[0]: partes
        for linha in mensagem.replace("\n", "\r").split("\r")
        if (partes := linha.split("|")) and partes[0]
    }
    if not {"MSH", "PID", "OBR", "OBX"}.issubset(segmentos):
        raise ValueError("HL7 inválido: faltam segmentos obrigatórios.")
    pid, obr, obx = segmentos["PID"], segmentos["OBR"], segmentos["OBX"]
    if len(pid) < 4 or len(obr) < 5 or len(obx) < 6:
        raise ValueError("HL7 inválido: campos insuficientes.")
    if not all([pid[3], obr[3], obr[4], obx[5]]):
        raise ValueError("HL7 inválido: paciente, exame ou resultado ausente.")
    return {"paciente": pid[3], "exame_id": obr[3], "exame": obr[4], "resultado": obx[5]}


def resposta_operacao(operacao: dict, resultado: dict, repetida: bool) -> dict:
    return {
        "operacao_id": operacao["id"], "fluxo": operacao["fluxo"],
        "status": "CONCLUIDO", "idempotente": repetida, **resultado,
    }


def executar_com_rastreabilidade(fluxo: str, chave: str, requisicao: dict, acao) -> dict:
    agora = datetime.now().isoformat(timespec="seconds")
    with conectar() as conexao:
        existente = conexao.execute("SELECT * FROM operacoes WHERE chave_idempotencia = ?", (chave,)).fetchone()
        if existente:
            operacao = dict(existente)
            if operacao["status"] == "CONCLUIDO":
                return resposta_operacao(operacao, json.loads(operacao["resposta"]), True)
            raise HTTPException(409, detail={
                "operacao_id": operacao["id"],
                "mensagem": "A operação falhou; use o endpoint de reprocessamento.",
            })

        operacao = {"id": str(uuid.uuid4()), "fluxo": fluxo, "chave": chave,
                    "requisicao": json.dumps(requisicao), "criado_em": agora}
        conexao.execute("""
            INSERT INTO operacoes
            (id, fluxo, chave_idempotencia, requisicao, status, criado_em, atualizado_em)
            VALUES (:id, :fluxo, :chave, :requisicao, 'PROCESSANDO', :criado_em, :criado_em)
        """, operacao)

    try:
        resultado = acao(requisicao)
        with conectar() as conexao:
            conexao.execute("""
                UPDATE operacoes SET status = 'CONCLUIDO', resposta = ?, atualizado_em = ? WHERE id = ?
            """, (json.dumps(resultado), datetime.now().isoformat(timespec="seconds"), operacao["id"]))
        return resposta_operacao({"id": operacao["id"], "fluxo": fluxo}, resultado, False)
    except Exception as erro:
        with conectar() as conexao:
            conexao.execute("""
                UPDATE operacoes SET status = 'FALHOU', erro = ?, atualizado_em = ? WHERE id = ?
            """, (str(erro), datetime.now().isoformat(timespec="seconds"), operacao["id"]))
        raise HTTPException(503, detail={"operacao_id": operacao["id"], "mensagem": str(erro)})


def processar_f1(dados: dict) -> dict:
    agendamento = chamar_servico("GET", f"http://127.0.0.1:8001/agendamentos/{dados['agendamento_id']}")
    atendimento = chamar_servico("POST", "http://127.0.0.1:8002/atendimentos", {
        "agendamento_id": agendamento["id"], "paciente": agendamento["paciente"]})
    registro = chamar_servico("POST", "http://127.0.0.1:8003/registros-administrativos", {
        "atendimento_id": atendimento["id"], "paciente": atendimento["paciente"]})
    return {"agendamento": agendamento, "atendimento": atendimento, "registro_prontuario": registro}


def processar_f2(dados: dict) -> dict:
    solicitacao = chamar_servico("POST", "http://127.0.0.1:8002/solicitacoes-exame", dados)
    exame = chamar_servico("POST", "http://127.0.0.1:8004/exames", {
        "solicitacao_id": solicitacao["id"], "atendimento_id": solicitacao["atendimento_id"],
        "paciente": solicitacao["paciente"], "exame": solicitacao["exame"]})
    resultado = interpretar_hl7(exame["hl7_v2"])
    registro = chamar_servico("POST", "http://127.0.0.1:8003/registros-laboratoriais", {
        "exame_id": resultado["exame_id"], "atendimento_id": solicitacao["atendimento_id"],
        "paciente": resultado["paciente"], "exame": resultado["exame"],
        "resultado": resultado["resultado"], "hl7_v2": exame["hl7_v2"]})
    return {"solicitacao": solicitacao, "exame": exame, "registro_laboratorial": registro}


def processar_f3(dados: dict) -> dict:
    if dados["origem"] not in {"S2", "S4"}:
        raise ValueError("A origem do item faturável deve ser S2 ou S4.")
    item = chamar_servico("POST", "http://127.0.0.1:8005/itens-faturaveis", dados)
    return {"item_faturavel": item}


def executar_fluxo_salvo(fluxo: str, dados: dict) -> dict:
    return {"F1": processar_f1, "F2": processar_f2, "F3": processar_f3}[fluxo](dados)


@app.post("/fluxos/f1")
def executar_fluxo_f1(fluxo: FluxoF1):
    dados = fluxo.model_dump()
    return executar_com_rastreabilidade("F1", f"F1:{fluxo.agendamento_id}", dados, processar_f1)


@app.post("/fluxos/f2")
def executar_fluxo_f2(fluxo: FluxoF2):
    dados = fluxo.model_dump()
    return executar_com_rastreabilidade("F2", f"F2:{fluxo.atendimento_id}:{fluxo.exame.upper()}", dados, processar_f2)


@app.post("/fluxos/f3")
def executar_fluxo_f3(fluxo: FluxoF3):
    dados = fluxo.model_dump()
    return executar_com_rastreabilidade("F3", f"F3:{fluxo.origem}:{fluxo.referencia_id}", dados, processar_f3)


@app.get("/operacoes")
def listar_operacoes():
    with conectar() as conexao:
        operacoes = conexao.execute("SELECT * FROM operacoes ORDER BY criado_em DESC").fetchall()
    return [dict(item) for item in operacoes]


@app.post("/operacoes/{operacao_id}/reprocessar")
def reprocessar(operacao_id: str):
    with conectar() as conexao:
        encontrada = conexao.execute("SELECT * FROM operacoes WHERE id = ?", (operacao_id,)).fetchone()
    if not encontrada:
        raise HTTPException(404, "Operação não encontrada.")
    operacao = dict(encontrada)
    if operacao["status"] != "FALHOU":
        raise HTTPException(409, "Somente operações com falha podem ser reprocessadas.")

    try:
        resultado = executar_fluxo_salvo(operacao["fluxo"], json.loads(operacao["requisicao"]))
        with conectar() as conexao:
            conexao.execute("""
                UPDATE operacoes SET status = 'CONCLUIDO', resposta = ?, erro = NULL,
                tentativas = tentativas + 1, atualizado_em = ? WHERE id = ?
            """, (json.dumps(resultado), datetime.now().isoformat(timespec="seconds"), operacao_id))
        return resposta_operacao(operacao, resultado, False)
    except Exception as erro:
        with conectar() as conexao:
            conexao.execute("""
                UPDATE operacoes SET erro = ?, tentativas = tentativas + 1, atualizado_em = ? WHERE id = ?
            """, (str(erro), datetime.now().isoformat(timespec="seconds"), operacao_id))
        raise HTTPException(503, detail={"operacao_id": operacao_id, "mensagem": str(erro)})


@app.get("/", response_class=HTMLResponse)
def painel():
    return """
    <html><head><title>ArchCorp — Maternidade Maria Luz</title><style>
      body{font-family:Arial;background:#f4f7fb;color:#1f2937;margin:0;padding:40px}.subtitulo{color:#5b6472}.grade{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:18px;margin-top:28px}.card{background:#fff;border-radius:12px;padding:20px;box-shadow:0 2px 10px #0002;border-left:6px solid #1769aa}.integracao{border-left-color:#7c3aed}.disponivel{color:#147a3d;font-weight:bold}input,select,button{display:block;width:100%;box-sizing:border-box;margin-top:10px;padding:10px;border-radius:6px}input,select{border:1px solid #bbb}button{border:0;background:#7c3aed;color:#fff;cursor:pointer}a{display:inline-block;margin-top:12px;color:#1769aa;font-weight:bold;text-decoration:none}.resultado{white-space:pre-wrap;font-size:.9em}
    </style></head><body><h1>ArchCorp — Maternidade Maria Luz</h1><p class="subtitulo">Painel demonstrativo da arquitetura de integração hospitalar</p><section class="grade">
      <article class="card integracao"><h2>Integração</h2><p>Orquestra F1, F2 e F3; registra operações, falhas e tentativas.</p><p class="disponivel">● Serviço disponível</p><a href="/docs" target="_blank">Abrir Swagger</a> · <a href="/operacoes" target="_blank">Ver operações</a></article>
      <article class="card integracao"><h2>Fluxo F1</h2><p>S1 → S2 → S3: agendamento e registro administrativo.</p><input id="f1Agendamento" placeholder="ID do agendamento"><button onclick="enviar('/fluxos/f1',{agendamento_id:f1Agendamento.value},'resultadoF1')">Executar F1</button><p class="resultado" id="resultadoF1"></p></article>
      <article class="card integracao"><h2>Fluxo F2</h2><p>S2 → S4 → S3: solicitação, HL7 v2 e resultado.</p><input id="f2Atendimento" placeholder="ID do atendimento"><input id="f2Exame" placeholder="Exame, por exemplo: HEMOGRAMA"><button onclick="enviar('/fluxos/f2',{atendimento_id:f2Atendimento.value,exame:f2Exame.value},'resultadoF2')">Executar F2</button><p class="resultado" id="resultadoF2"></p></article>
      <article class="card integracao"><h2>Fluxo F3</h2><p>S2 ou S4 → S5: item faturável.</p><select id="f3Origem"><option>S2</option><option>S4</option></select><input id="f3Referencia" placeholder="ID de atendimento ou exame"><input id="f3Paciente" placeholder="Nome da paciente"><input id="f3Descricao" placeholder="Descrição"><input id="f3Valor" type="number" step="0.01" placeholder="Valor"><button onclick="enviar('/fluxos/f3',{origem:f3Origem.value,referencia_id:f3Referencia.value,paciente:f3Paciente.value,descricao:f3Descricao.value,valor:Number(f3Valor.value)},'resultadoF3')">Executar F3</button><p class="resultado" id="resultadoF3"></p></article>
      <article class="card"><h2>S1 — Agendamento</h2><p>SaaS simulado.</p><p class="disponivel">● Serviço disponível</p><a href="http://127.0.0.1:8001" target="_blank">Abrir S1</a></article>
      <article class="card"><h2>S2 — Atendimento</h2><p>Atendimentos e solicitações de exame.</p><p class="disponivel">● Serviço disponível</p><a href="http://127.0.0.1:8002" target="_blank">Abrir S2</a></article>
      <article class="card"><h2>S3 — PEP</h2><p>Adaptador hipotético para registros administrativos e laboratoriais.</p><p class="disponivel">● Serviço disponível</p><a href="http://127.0.0.1:8003" target="_blank">Abrir S3</a></article>
      <article class="card"><h2>S4 — LIS</h2><p>Solicitações e resultados em HL7 v2 simplificado.</p><p class="disponivel">● Serviço disponível</p><a href="http://127.0.0.1:8004" target="_blank">Abrir S4</a></article>
      <article class="card"><h2>S5 — Financeiro</h2><p>Itens faturáveis de S2 e S4.</p><p class="disponivel">● Serviço disponível</p><a href="http://127.0.0.1:8005" target="_blank">Abrir S5</a></article>
    </section><script>
      async function enviar(url,body,destino){const alvo=document.getElementById(destino);alvo.textContent='Processando…';try{const resposta=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const dados=await resposta.json();alvo.textContent=resposta.ok?`Concluído. Operação: ${dados.operacao_id}${dados.idempotente?' (resultado já existente)':''}`:`Falha: ${dados.detail.mensagem || JSON.stringify(dados.detail)}`}catch(e){alvo.textContent='Falha de comunicação: '+e.message}}
    </script></body></html>
    """
