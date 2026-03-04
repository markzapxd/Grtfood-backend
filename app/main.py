"""GRT Food — Backend FastAPI.

Aplicação principal com todas as rotas REST, WebSocket e lifecycle.
"""

import asyncio
import calendar
import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, col, func, select

from app.config import settings
from app.cron import get_menu_close_hour, get_menu_open_hour, init_scheduler
from app.database import create_db_and_tables, get_session
from app.mail import enviar_email, renderizar_email_pedidos
from app.models import Cardapio, Pedido, Usuario
from app.schemas import (
    CardapioPayload,
    CardapioResponse,
    EstadoResponse,
    PedidoCreate,
    PedidoProcessado,
    PedidoResponse,
    ResumoAgrupado,
    ResumoMensalItem,
    ResumoMensalResponse,
    UsuarioCreate,
    UsuarioResponse,
)
from app.ws import manager

# ─── Estado global ──────────────────────────────────────────
estado: str = "Aberto"


# ─── Lifecycle ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa banco e scheduler no startup."""
    global estado
    
    try:
        create_db_and_tables()
        print("Banco de dados conectado e tabelas sincronizadas!")
    except Exception as e:
        print(f"ERRO CRÍTICO AO CONECTAR NO BANCO DE DADOS: {e}")

    try:
        estado = calcular_estado_cardapio()
        init_scheduler(abre_cardapio, fecha_cardapio)
        print("Scheduler iniciado com sucesso!")
    except Exception as e:
        print(f"ERRO AO INICIAR O SCHEDULER: {e}")

    yield


app = FastAPI(
    title="GRT Food API",
    description="Sistema de pedidos de almoço — Garten Automação",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS (Liberado para qualquer origem)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# ═══════════════════════════════════════════════════════════
#  FUNÇÕES AUXILIARES
# ═══════════════════════════════════════════════════════════

def calcular_estado_cardapio() -> str:
    """Calcula o estado do cardápio baseado no horário atual."""
    agora = datetime.now()
    hour_open, minute_open = get_menu_open_hour()
    hour_close, minute_close = get_menu_close_hour()

    if agora.hour >= int(hour_close) and agora.minute >= int(minute_close):
        return "Fechado"
    elif agora.hour >= int(hour_open) and agora.minute >= int(minute_open):
        return "Aberto"
    return "Fechado"


def get_cardapio_do_dia(session: Session) -> Cardapio | None:
    """Retorna o cardápio de hoje ou None."""
    statement = select(Cardapio).where(Cardapio.data == date.today())
    return session.exec(statement).first()


def get_pedidos_do_dia(session: Session) -> list[dict]:
    """Retorna os pedidos do dia formatados."""
    hoje = date.today()
    amanha = hoje + timedelta(days=1)
    statement = (
        select(Pedido, Usuario)
        .where(Pedido.data >= datetime.combine(hoje, datetime.min.time()))
        .where(Pedido.data < datetime.combine(amanha, datetime.min.time()))
        .join(Usuario, Pedido.usuario_id == Usuario.id)
        .order_by(col(Pedido.data).desc())
    )
    results = session.exec(statement).all()
    return [
        {
            "id": pedido.id,
            "usuario": usuario.nome,
            "dataDoPedido": pedido.data.isoformat(),
            "pedido": json.loads(pedido.pedido_json),
        }
        for pedido, usuario in results
    ]


def processar_pedidos(session: Session) -> list[dict]:
    """Processa pedidos: calcula itens removidos e opções selecionadas."""
    cardapio_db = get_cardapio_do_dia(session)
    if not cardapio_db:
        return []

    cardapio = json.loads(cardapio_db.cardapio_json)
    pedidos = get_pedidos_do_dia(session)

    processados = []
    for pedido in pedidos:
        removidos = [
            item
            for item in cardapio.get("items", [])
            if item not in pedido["pedido"].get("items", [])
        ]
        selecionados = [
            f"{k} : {v}"
            for k, v in pedido["pedido"].get("multiplos", {}).items()
        ]
        processados.append(
            {
                "usuario": pedido["usuario"],
                "removidos": removidos,
                "selecionados": selecionados,
                "data": pedido["dataDoPedido"],
            }
        )

    processados.sort(key=lambda x: x["usuario"])
    return processados


def agrupar_pedidos(pedidos: list[dict]) -> list[dict]:
    """Agrupa pedidos por seleções/remoções usando Pandas."""
    if not pedidos:
        return []

    lista_removidos = [",".join(p["removidos"]) for p in pedidos]
    lista_selecionados = [",".join(p["selecionados"]) for p in pedidos]

    df = pd.DataFrame(
        {
            "quantidade": [1] * len(lista_removidos),
            "removidos": lista_removidos,
            "selecionados": lista_selecionados,
        }
    )
    return (
        df.groupby(["selecionados", "removidos"], as_index=False)
        .sum()
        .to_dict("records")
    )


# ─── Funções do cron (abertura/fechamento) ──────────────────

async def abre_cardapio():
    """Job do scheduler: abre o cardápio e cadastra itens automáticos."""
    global estado
    estado = "Aberto"
    await manager.notifica_estado(estado)

    # Cadastro automático de cardápio
    items_env = settings.automatic_menu_items
    if items_env:
        from app.database import engine

        with Session(engine) as session:
            items = [i.strip() for i in items_env.split(",") if i.strip()]
            cardapio = get_cardapio_do_dia(session)
            payload = json.dumps({"items": items, "multiplos": {}})
            if not cardapio:
                cardapio = Cardapio(data=date.today(), cardapio_json=payload)
                session.add(cardapio)
            else:
                cardapio.cardapio_json = payload
                session.add(cardapio)
            session.commit()

            cardapio_data = json.loads(cardapio.cardapio_json)
            await manager.notifica_cardapio(cardapio_data)

            pedidos = get_pedidos_do_dia(session)
            await manager.notifica_pedidos(pedidos)


async def fecha_cardapio():
    """Job do scheduler: fecha o cardápio e envia e-mail agrupado."""
    global estado
    estado = "Fechado"
    await manager.notifica_estado(estado)

    from app.database import engine

    with Session(engine) as session:
        pedidos = processar_pedidos(session)
        resumo = agrupar_pedidos(pedidos)
        html = renderizar_email_pedidos(pedidos, resumo)
        enviar_email(html)


from pathlib import Path
from fastapi.responses import FileResponse

# ═══════════════════════════════════════════════════════════
#  ROTAS — SAÚDE DA API E USUÁRIOS
# ═══════════════════════════════════════════════════════════

@app.get("/api/health")
def health_check():
    """Health check api route."""
    return {"status": "ok", "message": "GRT Food API is running"}

@app.get("/api/usuarios", response_model=list[UsuarioResponse])
def listar_usuarios(session: Session = Depends(get_session)):
    """Lista todos os usuários ordenados por nome."""
    statement = select(Usuario).order_by(col(Usuario.nome).asc())
    return session.exec(statement).all()


@app.post("/api/usuarios", response_model=UsuarioResponse, status_code=201)
def criar_usuario(payload: UsuarioCreate, session: Session = Depends(get_session)):
    """Cria um novo usuário."""
    usuario = Usuario(nome=payload.nome)
    session.add(usuario)
    session.commit()
    session.refresh(usuario)
    return usuario


# ═══════════════════════════════════════════════════════════
#  ROTAS — CARDÁPIO
# ═══════════════════════════════════════════════════════════

@app.get("/api/cardapio")
def obter_cardapio(session: Session = Depends(get_session)):
    """Retorna o cardápio do dia."""
    cardapio = get_cardapio_do_dia(session)
    if not cardapio:
        return None
    data = json.loads(cardapio.cardapio_json)
    return CardapioResponse(
        id=cardapio.id,
        data=cardapio.data,
        items=data.get("items", []),
        multiplos=data.get("multiplos", {}),
    )


@app.post("/api/cardapio", response_model=CardapioResponse)
async def definir_cardapio(
    payload: CardapioPayload, session: Session = Depends(get_session)
):
    """Cria ou atualiza o cardápio do dia."""
    cardapio_json = json.dumps(payload.model_dump())
    cardapio = get_cardapio_do_dia(session)

    if not cardapio:
        cardapio = Cardapio(data=date.today(), cardapio_json=cardapio_json)
        session.add(cardapio)
    else:
        cardapio.cardapio_json = cardapio_json
        session.add(cardapio)

    session.commit()
    session.refresh(cardapio)

    # Broadcast via WebSocket
    await manager.notifica_cardapio(payload.model_dump())

    data = json.loads(cardapio.cardapio_json)
    return CardapioResponse(
        id=cardapio.id,
        data=cardapio.data,
        items=data.get("items", []),
        multiplos=data.get("multiplos", {}),
    )


# ═══════════════════════════════════════════════════════════
#  ROTAS — PEDIDOS
# ═══════════════════════════════════════════════════════════

@app.get("/api/pedidos", response_model=list[PedidoResponse])
def listar_pedidos(session: Session = Depends(get_session)):
    """Lista os pedidos do dia."""
    return get_pedidos_do_dia(session)


@app.post("/api/pedidos", response_model=PedidoResponse, status_code=201)
async def criar_pedido(
    payload: PedidoCreate, session: Session = Depends(get_session)
):
    """Cria um novo pedido (somente se o cardápio estiver Aberto)."""
    if estado != "Aberto":
        raise HTTPException(status_code=403, detail="Cardápio fechado. Não é possível fazer pedidos.")

    # Verifica se o usuario existe
    usuario = session.get(Usuario, payload.usuario_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    pedido = Pedido(
        usuario_id=payload.usuario_id,
        pedido_json=json.dumps(payload.pedido.model_dump()),
        obs=payload.obs,
    )
    session.add(pedido)
    session.commit()
    session.refresh(pedido)

    # Broadcast via WebSocket
    pedidos = get_pedidos_do_dia(session)
    await manager.notifica_pedidos(pedidos)

    return {
        "id": pedido.id,
        "usuario": usuario.nome,
        "dataDoPedido": pedido.data.isoformat(),
        "pedido": payload.pedido.model_dump(),
    }


@app.delete("/api/pedidos/{pedido_id}", status_code=204)
async def deletar_pedido(
    pedido_id: int, session: Session = Depends(get_session)
):
    """Deleta um pedido pelo ID."""
    pedido = session.get(Pedido, pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")

    session.delete(pedido)
    session.commit()

    # Broadcast via WebSocket
    pedidos = get_pedidos_do_dia(session)
    await manager.notifica_pedidos(pedidos)


@app.get("/api/pedidos/processados", response_model=list[PedidoProcessado])
def listar_pedidos_processados(session: Session = Depends(get_session)):
    """Lista os pedidos processados (com removidos/selecionados)."""
    return processar_pedidos(session)


# ═══════════════════════════════════════════════════════════
#  ROTAS — ESTADO DO CARDÁPIO
# ═══════════════════════════════════════════════════════════

@app.get("/api/estado", response_model=EstadoResponse)
def obter_estado():
    """Retorna o estado atual do cardápio."""
    return EstadoResponse(estado=estado)


@app.post("/api/estado/abrir", response_model=EstadoResponse)
async def abrir_cardapio_manual(session: Session = Depends(get_session)):
    """Abre o cardápio manualmente (para admin/RH)."""
    await abre_cardapio()
    return EstadoResponse(estado=estado)


@app.post("/api/estado/fechar", response_model=EstadoResponse)
async def fechar_cardapio_manual(session: Session = Depends(get_session)):
    """Fecha o cardápio manualmente e envia e-mail."""
    await fecha_cardapio()
    return EstadoResponse(estado=estado)


# ═══════════════════════════════════════════════════════════
#  ROTAS — RELATÓRIOS
# ═══════════════════════════════════════════════════════════

def _periodo_mensal(offset_semanas: int = 0) -> tuple[datetime, datetime]:
    """Calcula o período mensal customizado (dia 26 → dia 25).

    O sistema original usa dia 26 do mês anterior até dia 25 do mês atual.
    """
    ref = datetime.now() - timedelta(weeks=offset_semanas)
    month_end = ref.replace(day=25, hour=23, minute=59, second=59)
    month_start = (month_end.replace(day=1) - timedelta(days=1)).replace(
        day=26, hour=0, minute=0, second=0
    )
    return month_start, month_end


@app.get("/api/relatorios/mensal", response_model=ResumoMensalResponse)
def relatorio_mensal(session: Session = Depends(get_session)):
    """Relatório mensal detalhado (período 26→25) — mês atual."""
    month_start, month_end = _periodo_mensal()
    return _gerar_relatorio_mensal(session, month_start, month_end)


@app.get("/api/relatorios/mensal-anterior", response_model=ResumoMensalResponse)
def relatorio_mensal_anterior(session: Session = Depends(get_session)):
    """Relatório mensal detalhado — mês anterior (offset 4 semanas)."""
    month_start, month_end = _periodo_mensal(offset_semanas=4)
    return _gerar_relatorio_mensal(session, month_start, month_end)


def _gerar_relatorio_mensal(
    session: Session, month_start: datetime, month_end: datetime
) -> ResumoMensalResponse:
    """Gera o relatório mensal para o período especificado."""
    # Contagem por usuário
    statement = (
        select(Pedido.usuario_id, func.count(Pedido.id).label("qtde"))
        .where(Pedido.data >= month_start, Pedido.data <= month_end)
        .group_by(Pedido.usuario_id)
    )
    contagens = session.exec(statement).all()

    # Pedidos individuais para mapa de dias
    statement_pedidos = select(Pedido).where(
        Pedido.data >= month_start, Pedido.data <= month_end
    )
    todos_pedidos = session.exec(statement_pedidos).all()

    # Mapa: usuario_id → {dia: contagem}
    dias_grp: dict[int, dict[int, int]] = {}
    for p in todos_pedidos:
        dias = dias_grp.setdefault(p.usuario_id, {})
        dias[p.data.day] = dias.get(p.data.day, 0) + 1

    # Buscar nomes dos usuários
    usuario_ids = [uid for uid, _ in contagens]
    usuarios = {
        u.id: u.nome
        for u in session.exec(
            select(Usuario).where(col(Usuario.id).in_(usuario_ids))
        ).all()
    }

    resumo = sorted(
        [
            ResumoMensalItem(
                usuario=usuarios.get(uid, "Desconhecido"),
                usuario_id=uid,
                qtde=qtde,
                dias=dias_grp.get(uid, {}),
            )
            for uid, qtde in contagens
        ],
        key=lambda x: x.usuario,
    )

    # Dias do período (26→fim do mês, 1→25)
    dias_no_mes_count = calendar.monthrange(month_start.year, month_start.month)[1]
    dias = list(range(26, dias_no_mes_count + 1)) + list(range(1, 26))

    return ResumoMensalResponse(
        resumo=resumo,
        data_inicio=month_start.strftime("%d/%m/%Y %H:%M:%S"),
        data_fim=month_end.strftime("%d/%m/%Y %H:%M:%S"),
        gerado=datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        dias_no_mes=dias,
    )


# ═══════════════════════════════════════════════════════════
#  ROTA — TESTE DE E-MAIL
# ═══════════════════════════════════════════════════════════

@app.get("/api/mail/test")
def teste_email(session: Session = Depends(get_session)):
    """Envia e-mail de teste com os pedidos do dia."""
    from app.config import settings as _s
    if not _s.mail_smtp_server:
        raise HTTPException(status_code=400, detail="SMTP não configurado (MAIL_SMTP_SERVER vazio).")
    if not _s.mail_to:
        raise HTTPException(status_code=400, detail="Destinatário não configurado (MAIL_TO vazio).")

    pedidos = processar_pedidos(session)
    resumo = agrupar_pedidos(pedidos)
    html = renderizar_email_pedidos(pedidos, resumo)
    try:
        enviar_email(html)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao enviar: {e}")
    return {"status": "ok", "message": f"E-mail enviado para {_s.mail_to}"}


# ═══════════════════════════════════════════════════════════
#  WEBSOCKET
# ═══════════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Endpoint WebSocket — mantém conexão e envia estado inicial."""
    await manager.connect(websocket)
    try:
        # Envia estado inicial ao conectar
        await manager.send_json(websocket, {"tipo": "estado", "dados": estado})
        # Mantém conexão aberta (recebe pings/mensagens)
        while True:
            data = await websocket.receive_text()
            # O WebSocket é usado apenas para receber broadcasts
            # mensagens do cliente podem ser ignoradas ou logadas
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

# ═══════════════════════════════════════════════════════════
#  FRONTEND STATIC FILES
# ═══════════════════════════════════════════════════════════
from fastapi.staticfiles import StaticFiles

frontend_path = Path(__file__).parent / "static"

if frontend_path.exists():
    @app.get("/")
    async def serve_index():
        index = frontend_path / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(status_code=404)

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        if full_path.startswith("api/") or full_path == "ws":
            raise HTTPException(status_code=404, detail="Not found")
        file_path = frontend_path / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_path / "index.html")
else:
    @app.get("/")
    def root_fallback():
        return {"status": "ok", "message": "API rodando. Pasta static não encontrada."}

