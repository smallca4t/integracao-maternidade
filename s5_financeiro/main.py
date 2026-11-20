import uuid
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .database import conectar, criar_tabela

app = FastAPI(title="S5 — Financeiro")


class ItemFaturavel(BaseModel):
    origem: str
    referencia_id: str
    paciente: str
    descricao: str
    valor: float = Field(gt=0)


class EventoFaturavel(BaseModel):
    origem: str
    referencia_id: str
    paciente: str
    descricao: str


@app.on_event("startup")
def iniciar_banco():
    criar_tabela()


@app.post("/itens-faturaveis")
def receber_item(item: ItemFaturavel):
    if item.origem not in {"S2", "S4"}:
        raise HTTPException(422, "A origem deve ser S2 ou S4.")
    with conectar() as conexao:
        existente = conexao.execute("SELECT * FROM itens_faturaveis WHERE origem = ? AND referencia_id = ?", (item.origem, item.referencia_id)).fetchone()
        if existente:
            return dict(existente)
        registro = {"id": str(uuid.uuid4()), **item.model_dump(), "status": "PENDENTE", "criado_em": datetime.now().isoformat(timespec="seconds")}
        conexao.execute("""
            INSERT INTO itens_faturaveis
            (id, origem, referencia_id, paciente, descricao, valor, status, criado_em)
            VALUES (:id, :origem, :referencia_id, :paciente, :descricao, :valor, :status, :criado_em)
        """, registro)
    return registro


@app.get("/itens-faturaveis")
def listar_itens():
    with conectar() as conexao:
        itens = conexao.execute("SELECT * FROM itens_faturaveis ORDER BY criado_em DESC").fetchall()
    return [dict(item) for item in itens]


@app.post("/eventos-faturaveis")
def receber_evento(evento: EventoFaturavel):
    """Pré-faturamento: registra o procedimento, sem atribuir preço automaticamente."""
    if evento.origem not in {"S2", "S4"}:
        raise HTTPException(422, "A origem deve ser S2 ou S4.")
    with conectar() as conexao:
        existente = conexao.execute("""
            SELECT * FROM eventos_faturaveis WHERE origem = ? AND referencia_id = ?
        """, (evento.origem, evento.referencia_id)).fetchone()
        if existente:
            return dict(existente)
        registro = {"id": str(uuid.uuid4()), **evento.model_dump(),
                    "status": "PENDENTE_DE_VALOR",
                    "criado_em": datetime.now().isoformat(timespec="seconds")}
        conexao.execute("""
            INSERT INTO eventos_faturaveis
            (id, origem, referencia_id, paciente, descricao, status, criado_em)
            VALUES (:id, :origem, :referencia_id, :paciente, :descricao, :status, :criado_em)
        """, registro)
    return registro


@app.get("/eventos-faturaveis")
def listar_eventos():
    with conectar() as conexao:
        itens = conexao.execute("""
            SELECT * FROM eventos_faturaveis ORDER BY criado_em DESC
        """).fetchall()
    return [dict(item) for item in itens]


@app.get("/contas-paciente")
def listar_contas_paciente():
    with conectar() as conexao:
        contas = conexao.execute("""
            SELECT paciente, COUNT(*) AS quantidade_procedimentos,
                   GROUP_CONCAT(descricao, ' | ') AS procedimentos
            FROM eventos_faturaveis
            GROUP BY paciente
            ORDER BY paciente
        """).fetchall()
    return [dict(conta) for conta in contas]


@app.get("/", response_class=HTMLResponse)
def inicio():
    return """
    <html><head><title>S5 — Financeiro</title><style>
      body{font-family:Arial;background:#f4f7fb;padding:40px}.card{max-width:760px;background:white;border-radius:12px;padding:24px;box-shadow:0 2px 10px #0002}.status{color:#147a3d;font-weight:bold}li{margin:12px 0;padding-bottom:12px;border-bottom:1px solid #ddd}.muted{color:#5b6472}
    </style></head><body><div class="card"><h1>S5 — Financeiro</h1><p><strong>Função:</strong> organizar a conta da paciente a partir de eventos clínicos faturáveis.</p><p class="muted">Os procedimentos chegam pela Integração sem valor. A precificação é uma etapa administrativa posterior.</p><p class="status">● Serviço disponível</p><h2>Contas por paciente</h2><ul id="contas"></ul><h2>Procedimentos aguardando valor</h2><ul id="eventos"></ul></div><script>
      async function carregar(){const [a,b]=await Promise.all([fetch('/contas-paciente'),fetch('/eventos-faturaveis')]);const contas=await a.json(),eventos=await b.json();document.getElementById('contas').innerHTML=contas.map(x=>`<li><strong>${x.paciente}</strong><br>${x.quantidade_procedimentos} procedimento(s): ${x.procedimentos}</li>`).join('')||'<li class="muted">Nenhuma conta em aberto.</li>';document.getElementById('eventos').innerHTML=eventos.map(x=>`<li><strong>${x.descricao}</strong> — ${x.paciente}<br>Origem: ${x.origem}; Referência: ${x.referencia_id}<br>Status: ${x.status}</li>`).join('')||'<li class="muted">Nenhum procedimento aguardando valor.</li>'};carregar()
    </script></body></html>
    """
