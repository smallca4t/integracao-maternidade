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
    return {"agendamento": agendamento, "atendimento": atendimento,
            "registro_prontuario": registro}


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
    return {"solicitacao": solicitacao, "exame": exame,
            "registro_laboratorial": registro}


def processar_f3(dados: dict) -> dict:
    if dados["origem"] not in {"S2", "S4"}:
        raise ValueError("A origem do item faturável deve ser S2 ou S4.")
    item = chamar_servico("POST", "http://127.0.0.1:8006/itens-faturaveis", dados)
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


def consultar_contagem(url: str) -> tuple[bool, int, str | None]:
    """Consulta apenas APIs públicas dos simuladores; não acessa seus bancos."""
    try:
        resposta = httpx.get(url, timeout=2)
        resposta.raise_for_status()
        return True, len(resposta.json()), None
    except (httpx.HTTPError, ValueError) as erro:
        return False, 0, str(erro)


@app.get("/monitoramento/dados")
def dados_monitoramento():
    configuracao = [
        ("S1", "Agendamento", "http://127.0.0.1:8001", [("Agendamentos", "/agendamentos")]),
        ("S2", "Atendimento", "http://127.0.0.1:8002", [("Atendimentos", "/atendimentos"), ("Solicitações", "/solicitacoes-exame")]),
        ("S3", "PEP", "http://127.0.0.1:8003", [("Registros administrativos", "/registros-administrativos"), ("Registros laboratoriais", "/registros-laboratoriais")]),
        ("S4", "LIS", "http://127.0.0.1:8004", [("Exames liberados", "/exames")]),
        ("S5", "Financeiro", "http://127.0.0.1:8006", [("Itens faturáveis", "/itens-faturaveis")]),
    ]
    sistemas = []
    for codigo, nome, base_url, metricas_configuradas in configuracao:
        metricas = []
        erros = []
        for rotulo, rota in metricas_configuradas:
            ativo, total, erro = consultar_contagem(base_url + rota)
            metricas.append({"rotulo": rotulo, "total": total})
            if not ativo:
                erros.append(erro)
        sistemas.append({"codigo": codigo, "nome": nome, "url": base_url,
                         "ativo": not erros, "metricas": metricas,
                         "erro": erros[0] if erros else None})

    with conectar() as conexao:
        registros = conexao.execute("""
            SELECT id, fluxo, requisicao, status, erro, tentativas, criado_em, atualizado_em
            FROM operacoes ORDER BY criado_em DESC LIMIT 8
        """).fetchall()

    operacoes = []
    for item in registros:
        operacao = dict(item)
        requisicao = json.loads(operacao.pop("requisicao"))
        operacao["referencia"] = {
            "F1": requisicao.get("agendamento_id"),
            "F2": requisicao.get("atendimento_id"),
            "F3": requisicao.get("referencia_id"),
        }.get(operacao["fluxo"], "—")
        operacoes.append(operacao)
    return {"sistemas": sistemas, "operacoes": operacoes,
            "atualizado_em": datetime.now().isoformat(timespec="seconds")}


@app.get("/monitoramento", response_class=HTMLResponse)
def monitoramento():
    return """
    <html><head><title>ArchCorp — Painel de Registros</title><style>
      body{font-family:Arial;background:#f4f7fb;color:#1f2937;margin:0;padding:36px}.topo{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.subtitulo{color:#5b6472;margin-top:6px}.grade{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px;margin:24px 0}.card{background:#fff;border-radius:12px;padding:18px;box-shadow:0 2px 10px #0002;border-left:6px solid #1769aa}.ativo{color:#147a3d;font-weight:bold}.inativo{color:#b42318;font-weight:bold}.metrica{margin:8px 0;color:#4b5563}.metrica strong{color:#1f2937}.painel{background:#fff;border-radius:12px;padding:20px;box-shadow:0 2px 10px #0002}.fluxos{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0 22px}.fluxo{background:#ede9fe;color:#5b21b6;border-radius:20px;padding:8px 12px;font-size:.9em}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:10px;border-bottom:1px solid #e5e7eb;font-size:.9em}.concluido{color:#147a3d}.falhou{color:#b42318}button,a{border:0;border-radius:6px;padding:10px 14px;background:#7c3aed;color:#fff;text-decoration:none;cursor:pointer}.erro{font-size:.8em;color:#b42318;word-break:break-word}@media(max-width:650px){body{padding:20px}.topo{display:block}.painel{overflow-x:auto}}
    </style></head><body><div class="topo"><div><h1>Painel de registros</h1><p class="subtitulo">Visão didática dos sistemas ativos e dos dados que circulam entre eles.</p></div><div><a href="/">Voltar aos fluxos</a> <button onclick="carregar()">Atualizar</button></div></div>
    <div class="fluxos"><span class="fluxo">F1 · S1 → S2 → S3</span><span class="fluxo">F2 · S2 → S4 → S3</span><span class="fluxo">F3 · S2/S4 → S5, após regra financeira</span></div><p id="atualizado" class="subtitulo"></p><section id="sistemas" class="grade"></section><section class="painel"><h2>Últimas operações da integração</h2><table><thead><tr><th>Fluxo</th><th>Referência de origem</th><th>Status</th><th>Tentativas</th><th>Atualizada em</th></tr></thead><tbody id="operacoes"></tbody></table></section>
    <script>
      function escapar(texto){const item=document.createElement('span');item.textContent=texto ?? '';return item.innerHTML}
      async function carregar(){const resposta=await fetch('/monitoramento/dados');const dados=await resposta.json();document.getElementById('atualizado').textContent='Atualizado em: '+new Date(dados.atualizado_em).toLocaleString();document.getElementById('sistemas').innerHTML=dados.sistemas.map(s=>`<article class="card"><h2>${s.codigo} — ${escapar(s.nome)}</h2><p class="${s.ativo?'ativo':'inativo'}">● ${s.ativo?'Disponível':'Indisponível'}</p>${s.metricas.map(m=>`<p class="metrica">${escapar(m.rotulo)}: <strong>${m.total}</strong></p>`).join('')}${s.erro?`<p class="erro">${escapar(s.erro)}</p>`:''}<a href="${s.url}" target="_blank">Abrir sistema</a></article>`).join('');document.getElementById('operacoes').innerHTML=dados.operacoes.length?dados.operacoes.map(o=>`<tr><td>${o.fluxo}</td><td>${escapar(o.referencia)}</td><td class="${o.status==='CONCLUIDO'?'concluido':'falhou'}">${o.status}</td><td>${o.tentativas}</td><td>${new Date(o.atualizado_em).toLocaleString()}</td></tr>`).join(''):'<tr><td colspan="5">Nenhuma integração executada ainda.</td></tr>'}
      carregar();setInterval(carregar,5000);
    </script></body></html>
    """


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
      <article class="card integracao"><h2>Integração</h2><p>Orquestra F1, F2 e F3; registra operações, falhas e tentativas.</p><p class="disponivel">● Serviço disponível</p><a href="/monitoramento">Painel de registros</a> · <a href="/docs" target="_blank">Abrir Swagger</a></article>
      <article class="card integracao"><h2>Fluxo F1</h2><p>S1 → S2 → S3: agendamento e registro administrativo.</p><p>Inicie no S1, após criar o agendamento.</p></article>
      <article class="card integracao"><h2>Fluxo F2</h2><p>S2 → S4 → S3: solicitação, HL7 v2 e resultado.</p><p>Inicie no S2, a partir de um atendimento aberto.</p></article>
      <article class="card"><h2>S1 — Agendamento</h2><p>SaaS simulado.</p><p class="disponivel">● Serviço disponível</p><a href="http://127.0.0.1:8001" target="_blank">Abrir S1</a></article>
      <article class="card"><h2>S2 — Atendimento</h2><p>Atendimentos e solicitações de exame.</p><p class="disponivel">● Serviço disponível</p><a href="http://127.0.0.1:8002" target="_blank">Abrir S2</a></article>
      <article class="card"><h2>S3 — PEP</h2><p>Adaptador hipotético para registros administrativos e laboratoriais.</p><p class="disponivel">● Serviço disponível</p><a href="http://127.0.0.1:8003" target="_blank">Abrir S3</a></article>
      <article class="card"><h2>S4 — LIS</h2><p>Solicitações e resultados em HL7 v2 simplificado.</p><p class="disponivel">● Serviço disponível</p><a href="http://127.0.0.1:8004" target="_blank">Abrir S4</a></article>
      <article class="card"><h2>S5 — Financeiro</h2><p>Itens faturáveis de S2 e S4.</p><p class="disponivel">● Serviço disponível</p><a href="http://127.0.0.1:8006" target="_blank">Abrir S5</a></article>
    </section><script>
      async function enviar(url,body,destino){const alvo=document.getElementById(destino);alvo.textContent='Processando…';try{const resposta=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const dados=await resposta.json();alvo.textContent=resposta.ok?`Concluído. Operação: ${dados.operacao_id}${dados.idempotente?' (resultado já existente)':''}`:`Falha: ${dados.detail.mensagem || JSON.stringify(dados.detail)}`}catch(e){alvo.textContent='Falha de comunicação: '+e.message}}
    </script></body></html>
    """
