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


@app.get("/", response_class=HTMLResponse)
def inicio():
    return """
    <html><head><title>S5 — Financeiro</title><style>
      body{font-family:Arial;background:#f4f7fb;padding:40px}.card{max-width:720px;background:white;border-radius:12px;padding:24px;box-shadow:0 2px 10px #0002}input,select,button{display:block;width:100%;box-sizing:border-box;margin-top:10px;padding:10px;border-radius:6px}input,select{border:1px solid #bbb}button{border:0;background:#166534;color:white;cursor:pointer}.status{color:#147a3d;font-weight:bold}li{margin:12px 0;padding-bottom:12px;border-bottom:1px solid #ddd}
    </style></head><body><div class="card"><h1>S5 — Financeiro</h1><p><strong>Função:</strong> receber itens faturáveis de S2 e S4.</p><p class="status">● Serviço disponível</p><h2>Novo item faturável</h2><select id="origem"><option>S2</option><option>S4</option></select><input id="referencia" placeholder="ID de atendimento ou exame"><input id="paciente" placeholder="Nome da paciente"><input id="descricao" placeholder="Descrição"><input id="valor" type="number" step="0.01" placeholder="Valor"><button onclick="enviar()">Registrar item</button><p id="mensagem"></p><h2>Itens recebidos</h2><ul id="lista"></ul></div><script>
      async function enviar(){const body={origem:origem.value,referencia_id:referencia.value,paciente:paciente.value,descricao:descricao.value,valor:Number(valor.value)};const r=await fetch('/itens-faturaveis',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();mensagem.textContent=r.ok?'Item registrado: '+d.id:'Falha: '+JSON.stringify(d.detail);carregar()}
      async function carregar(){const r=await fetch('/itens-faturaveis');const itens=await r.json();lista.innerHTML=itens.map(x=>`<li><strong>${x.descricao}</strong> — R$ ${x.valor.toFixed(2)}<br>Origem: ${x.origem}; Status: ${x.status}</li>`).join('')};carregar()
    </script></body></html>
    """
