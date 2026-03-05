"""GRT Food — Backend FastAPI.

Aplicação principal com todas as rotas REST, WebSocket e lifecycle.
"""

import asyncio
import calendar
import json
import re
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, col, func, select
from typing import Optional 
from datetime import datetime, timedelta

from app.config import settings
from app.cron import get_menu_close_hour, get_menu_open_hour, init_scheduler
from app.database import create_db_and_tables, get_session, engine
from app.mail import enviar_email, renderizar_email_pedidos
from app.models import AutoPedidoSemanal, Cardapio, Pedido, Usuario
from app.schemas import (
    AutoPedidoSemanalCreate,
    AutoPedidoSemanalResponse,
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
    UsuarioStatusUpdate,
)
from app.ws import manager
from app.auth import (
    verify_password,
    hash_password,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    validate_refresh_token,
    revoke_refresh_token,
    get_auth_account_by_id,
    get_auth_account_by_username,
)
from app.models import AuthAccount

# ─── Estado global ──────────────────────────────────────────
estado: str = "Aberto"

# Proteções de login (sem alterar schema do banco)
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 10 * 60
LOGIN_LOCK_SECONDS = 15 * 60
LOGIN_ATTEMPTS: dict[str, list[float]] = {}
LOGIN_LOCKED_UNTIL: dict[str, float] = {}


def _normalize_username(username: str) -> str:
    return username.strip().lower()


NAME_PATTERN = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ]+(?: [A-Za-zÀ-ÖØ-öø-ÿ]+)*$")


def _normalize_person_name(nome: str) -> str:
    return " ".join(nome.strip().split())


def _validate_person_name(nome: str) -> str:
    normalized = _normalize_person_name(nome)
    if not normalized:
        raise HTTPException(status_code=400, detail="Nome é obrigatório")
    if not NAME_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=400, detail="Nome deve conter apenas letras e espaços")
    return normalized


def _prune_attempts(username: str, now: float) -> None:
    attempts = LOGIN_ATTEMPTS.get(username, [])
    cutoff = now - LOGIN_WINDOW_SECONDS
    LOGIN_ATTEMPTS[username] = [ts for ts in attempts if ts >= cutoff]


def _is_locked(username: str, now: float) -> bool:
    locked_until = LOGIN_LOCKED_UNTIL.get(username)
    if not locked_until:
        return False
    if locked_until <= now:
        LOGIN_LOCKED_UNTIL.pop(username, None)
        return False
    return True


def _register_login_failure(username: str, now: float) -> None:
    _prune_attempts(username, now)
    attempts = LOGIN_ATTEMPTS.get(username, [])
    attempts.append(now)
    LOGIN_ATTEMPTS[username] = attempts
    if len(attempts) >= MAX_LOGIN_ATTEMPTS:
        LOGIN_LOCKED_UNTIL[username] = now + LOGIN_LOCK_SECONDS


def _register_login_success(username: str) -> None:
    LOGIN_ATTEMPTS.pop(username, None)
    LOGIN_LOCKED_UNTIL.pop(username, None)


def _ensure_administrativo_account() -> None:
    username = "administrativo"
    senha = "gartenfood"

    with Session(engine) as session:
        usuario = session.exec(
            select(Usuario).where(func.lower(Usuario.nome) == username)
        ).first()
        if not usuario:
            usuario = Usuario(nome=username, ativo=True)
            session.add(usuario)
            session.commit()
            session.refresh(usuario)

        auth = session.exec(
            select(AuthAccount).where(AuthAccount.username == username)
        ).first()
        senha_hash = hash_password(senha)
        if not auth:
            auth = AuthAccount(
                usuario_id=usuario.id,
                username=username,
                senha_hash=senha_hash,
                is_admin=True,
            )
            session.add(auth)
        else:
            auth.usuario_id = usuario.id
            auth.senha_hash = senha_hash
            auth.is_admin = True
            session.add(auth)
        session.commit()


# ─── Lifecycle ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa banco e scheduler no startup."""
    global estado
    
    try:
        create_db_and_tables()
        _ensure_administrativo_account()
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

allowed_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]

# CORS (Liberado para qualquer origem)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or ["http://localhost:3000"],
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
    if agora.weekday() >= 5:
        return "Fechado"

    hour_open, minute_open = get_menu_open_hour()
    hour_close, minute_close = get_menu_close_hour()

    now_total_minutes = (agora.hour * 60) + agora.minute
    open_total_minutes = (int(hour_open) * 60) + int(minute_open)
    close_total_minutes = (int(hour_close) * 60) + int(minute_close)

    if now_total_minutes >= close_total_minutes:
        return "Fechado"
    if now_total_minutes >= open_total_minutes:
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
    pedidos = get_pedidos_do_dia(session)

    if not cardapio_db:
        processados_sem_cardapio = []
        for pedido in pedidos:
            selecionados = [
                f"{k} : {v}"
                for k, v in pedido["pedido"].get("multiplos", {}).items()
            ]
            processados_sem_cardapio.append(
                {
                    "usuario": pedido["usuario"],
                    "removidos": [],
                    "selecionados": selecionados,
                    "data": pedido["dataDoPedido"],
                }
            )

        processados_sem_cardapio.sort(key=lambda x: x["usuario"])
        return processados_sem_cardapio

    cardapio = json.loads(cardapio_db.cardapio_json)

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


def _inicio_fim_do_dia(alvo: date) -> tuple[datetime, datetime]:
    inicio = datetime.combine(alvo, datetime.min.time())
    fim = inicio + timedelta(days=1)
    return inicio, fim


def _segunda_da_semana(alvo: date) -> date:
    return alvo - timedelta(days=alvo.weekday())


def _is_weekend(alvo: date | None = None) -> bool:
    dia = alvo or date.today()
    return dia.weekday() >= 5


def _aplicar_pedidos_automaticos_semanais(session: Session) -> int:
    """Cria pedidos automáticos do dia para usuários habilitados na semana."""
    hoje = date.today()
    if _is_weekend(hoje):
        return 0

    inicio_dia, fim_dia = _inicio_fim_do_dia(hoje)

    configs_ativas = session.exec(
        select(AutoPedidoSemanal)
        .where(AutoPedidoSemanal.ativo == True)
        .order_by(col(AutoPedidoSemanal.id).asc())
    ).all()

    if not configs_ativas:
        return 0

    total_criados = 0
    for config in configs_ativas:
        usuario = session.get(Usuario, config.usuario_id)
        if not usuario or not usuario.ativo:
            continue

        pedido_existente = session.exec(
            select(Pedido)
            .where(Pedido.usuario_id == config.usuario_id)
            .where(Pedido.data >= inicio_dia)
            .where(Pedido.data < fim_dia)
        ).first()
        if pedido_existente:
            continue

        pedido = Pedido(
            usuario_id=config.usuario_id,
            pedido_json=json.dumps({"items": ["Almoço"], "multiplos": {}}),
            obs="Pedido automático semanal",
        )
        session.add(pedido)
        total_criados += 1

    if total_criados > 0:
        session.commit()

    return total_criados


def _resetar_pedidos_automaticos_na_sexta(session: Session) -> int:
    """Desativa todos os pedidos automáticos semanais quando for sexta-feira."""
    if date.today().weekday() != 4:
        return 0

    configs_ativas = session.exec(
        select(AutoPedidoSemanal).where(AutoPedidoSemanal.ativo == True)
    ).all()

    if not configs_ativas:
        return 0

    agora = datetime.utcnow()
    for config in configs_ativas:
        config.ativo = False
        config.atualizado_em = agora
        session.add(config)
    session.commit()
    return len(configs_ativas)


# ─── Funções do cron (abertura/fechamento) ──────────────────

async def abre_cardapio():
    """Job do scheduler: abre o cardápio e cadastra itens automáticos."""
    global estado
    if _is_weekend():
        estado = "Fechado"
        await manager.notifica_estado(estado)
        return

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

    from app.database import engine

    with Session(engine) as session:
        _aplicar_pedidos_automaticos_semanais(session)
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
        _resetar_pedidos_automaticos_na_sexta(session)


from pathlib import Path
from fastapi.responses import FileResponse


def _resolve_frontend_dist_dir() -> Path | None:
    """Resolve o diretório de build estático do frontend."""
    # 1) Build copiado para dentro do backend (Docker unificado)
    bundled = Path(__file__).resolve().parents[1] / "frontend_dist"
    if bundled.exists() and bundled.is_dir():
        return bundled

    # 2) Build local do frontend (monorepo)
    local_frontend_out = Path(__file__).resolve().parents[2] / "frontend" / "out"
    if local_frontend_out.exists() and local_frontend_out.is_dir():
        return local_frontend_out

    return None


def get_current_auth_account(authorization: str = Header(None)) -> AuthAccount:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid auth scheme")
    auth_id = decode_access_token(token)
    if not auth_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    auth_account = get_auth_account_by_id(auth_id)
    if not auth_account:
        raise HTTPException(status_code=401, detail="Auth account not found")
    return auth_account


def require_admin(auth_account: AuthAccount = Depends(get_current_auth_account)):
    if not getattr(auth_account, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    return auth_account


def require_garten_admin(auth_account: AuthAccount = Depends(require_admin)):
    if _normalize_username(auth_account.username) != "garten":
        raise HTTPException(status_code=403, detail="Apenas o usuário 'garten' pode gerenciar pedidos automáticos semanais")
    return auth_account

# ═══════════════════════════════════════════════════════════
#  ROTAS — SAÚDE DA API E USUÁRIOS
# ═══════════════════════════════════════════════════════════

@app.get("/api/health")
def health_check():
    """Health check api route."""
    return {"status": "ok", "message": "GRT Food API is running"}

@app.get("/api/usuarios", response_model=list[UsuarioResponse])
def listar_usuarios(session: Session = Depends(get_session)):
    """Lista usuários ativos ordenados por nome."""
    statement = (
        select(Usuario)
        .where(Usuario.ativo == True)
        .order_by(col(Usuario.nome).asc())
    )
    return session.exec(statement).all()


@app.post("/api/usuarios", response_model=UsuarioResponse, status_code=201)
@app.post("/api/admin/usuarios", response_model=UsuarioResponse, status_code=201)
def criar_usuario(
    payload: UsuarioCreate,
    session: Session = Depends(get_session),
    auth: AuthAccount = Depends(require_admin),
):
    """Cria um novo usuário."""
    nome = _validate_person_name(payload.nome)

    existente = session.exec(
        select(Usuario).where(func.lower(Usuario.nome) == func.lower(nome))
    ).first()
    if existente:
        raise HTTPException(status_code=409, detail="Já existe uma pessoa com esse nome")

    usuario = Usuario(nome=nome, ativo=payload.ativo)
    session.add(usuario)
    session.commit()
    session.refresh(usuario)
    return usuario


@app.get("/api/admin/usuarios", response_model=list[UsuarioResponse])
@app.get("/api/admin/usuarios/", response_model=list[UsuarioResponse])
def listar_todos_usuarios_admin(
    session: Session = Depends(get_session),
    auth: AuthAccount = Depends(require_admin),
):
    """Lista todos os usuários (ativos e inativos) para administração."""
    statement = select(Usuario).order_by(col(Usuario.nome).asc())
    return session.exec(statement).all()


@app.patch("/api/admin/usuarios/{usuario_id}/status", response_model=UsuarioResponse)
@app.patch("/api/admin/usuarios/{usuario_id}/status/", response_model=UsuarioResponse)
def atualizar_status_usuario_admin(
    usuario_id: int,
    payload: UsuarioStatusUpdate,
    session: Session = Depends(get_session),
    auth: AuthAccount = Depends(require_admin),
):
    """Ativa/desativa usuário para aparecer ou não na tela de pedidos."""
    usuario = session.get(Usuario, usuario_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    usuario.ativo = payload.ativo
    session.add(usuario)
    session.commit()
    session.refresh(usuario)
    return usuario


@app.delete("/api/admin/usuarios/{usuario_id}", status_code=204)
@app.delete("/api/admin/usuarios/{usuario_id}/", status_code=204)
def excluir_usuario_admin(
    usuario_id: int,
    session: Session = Depends(get_session),
    auth: AuthAccount = Depends(require_admin),
):
    """Exclui usuário do banco (somente se não houver vínculos)."""
    usuario = session.get(Usuario, usuario_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    possui_auth = session.exec(
        select(AuthAccount).where(AuthAccount.usuario_id == usuario.id)
    ).first()
    if possui_auth:
        raise HTTPException(
            status_code=409,
            detail="Não é possível excluir: usuário vinculado a conta de login.",
        )

    possui_pedidos = session.exec(
        select(Pedido).where(Pedido.usuario_id == usuario.id)
    ).first()
    if possui_pedidos:
        raise HTTPException(
            status_code=409,
            detail="Não é possível excluir: usuário possui pedidos registrados.",
        )

    possui_auto_pedido = session.exec(
        select(AutoPedidoSemanal).where(AutoPedidoSemanal.usuario_id == usuario.id)
    ).first()
    if possui_auto_pedido:
        raise HTTPException(
            status_code=409,
            detail="Não é possível excluir: usuário vinculado a pedido automático semanal.",
        )

    session.delete(usuario)
    session.commit()


# ═══════════════════════════════════════════════════════════
#  ROTAS — AUTENTICAÇÃO (LOGIN / REFRESH / LOGOUT)
# ═══════════════════════════════════════════════════════════


from pydantic import BaseModel


class LoginPayload(BaseModel):
    username: str
    senha: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@app.post("/api/auth/login", response_model=TokenResponse)
def auth_login(payload: LoginPayload):
    username = _normalize_username(payload.username)
    now = time.time()

    if _is_locked(username, now):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")

    auth = get_auth_account_by_username(username)
    if not auth or not auth.senha_hash or not verify_password(payload.senha, auth.senha_hash):
        _register_login_failure(username, now)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    _register_login_success(username)
    access = create_access_token(auth.id)
    refresh = create_refresh_token(auth.id)
    return {"access_token": access, "refresh_token": refresh}


class RefreshPayload(BaseModel):
    refresh_token: str


@app.post("/api/auth/refresh", response_model=dict)
def auth_refresh(payload: RefreshPayload):
    auth_id = validate_refresh_token(payload.refresh_token)
    if not auth_id:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    access = create_access_token(auth_id)
    revoke_refresh_token(payload.refresh_token)
    new_refresh = create_refresh_token(auth_id)
    return {"access_token": access, "refresh_token": new_refresh}


@app.post("/api/auth/logout", response_model=dict)
def auth_logout(payload: RefreshPayload):
    revoke_refresh_token(payload.refresh_token)
    return {"status": "ok"}


@app.get("/api/admin/secret")
def admin_secret(auth: AuthAccount = Depends(require_admin), session: Session = Depends(get_session)):
    user = session.get(Usuario, auth.usuario_id)
    return {
        "secret": "somente-para-admins",
        "usuario": user.nome,
        "username": auth.username,
        "can_manage_auto_weekly": _normalize_username(auth.username) == "garten",
    }


def _to_auto_pedido_response(config: AutoPedidoSemanal, session: Session) -> AutoPedidoSemanalResponse:
    usuario = session.get(Usuario, config.usuario_id)
    return AutoPedidoSemanalResponse(
        id=config.id,
        usuario_id=config.usuario_id,
        usuario_nome=usuario.nome if usuario else "Desconhecido",
        ativo=config.ativo,
        semana_referencia=config.semana_referencia,
        criado_em=config.criado_em,
        atualizado_em=config.atualizado_em,
    )


@app.get("/api/admin/auto-pedidos-semanais", response_model=list[AutoPedidoSemanalResponse])
def listar_auto_pedidos_semanais(
    session: Session = Depends(get_session),
    auth: AuthAccount = Depends(require_garten_admin),
):
    configs = session.exec(
        select(AutoPedidoSemanal).order_by(col(AutoPedidoSemanal.ativo).desc(), col(AutoPedidoSemanal.id).asc())
    ).all()
    return [_to_auto_pedido_response(config, session) for config in configs]


@app.post("/api/admin/auto-pedidos-semanais", response_model=AutoPedidoSemanalResponse)
def ativar_auto_pedido_semanal(
    payload: AutoPedidoSemanalCreate,
    session: Session = Depends(get_session),
    auth: AuthAccount = Depends(require_garten_admin),
):
    usuario = session.get(Usuario, payload.usuario_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    if not usuario.ativo:
        raise HTTPException(status_code=400, detail="Usuário inativo não pode receber pedido automático")

    config = session.exec(
        select(AutoPedidoSemanal).where(AutoPedidoSemanal.usuario_id == payload.usuario_id)
    ).first()

    agora = datetime.utcnow()
    semana = _segunda_da_semana(date.today())

    if not config:
        config = AutoPedidoSemanal(
            usuario_id=payload.usuario_id,
            ativo=True,
            criado_por_auth_id=auth.id,
            criado_em=agora,
            atualizado_em=agora,
            semana_referencia=semana,
        )
        session.add(config)
    else:
        config.ativo = True
        config.criado_por_auth_id = auth.id
        config.semana_referencia = semana
        config.atualizado_em = agora
        session.add(config)

    session.commit()
    session.refresh(config)
    return _to_auto_pedido_response(config, session)


@app.delete("/api/admin/auto-pedidos-semanais/{usuario_id}", status_code=204)
def desativar_auto_pedido_semanal(
    usuario_id: int,
    session: Session = Depends(get_session),
    auth: AuthAccount = Depends(require_garten_admin),
):
    config = session.exec(
        select(AutoPedidoSemanal).where(AutoPedidoSemanal.usuario_id == usuario_id)
    ).first()
    if not config:
        return

    session.delete(config)
    session.commit()


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
    payload: CardapioPayload,
    session: Session = Depends(get_session),
    auth: AuthAccount = Depends(require_admin),
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
    if _is_weekend():
        raise HTTPException(status_code=403, detail="No sábado e domingo o cardápio não funciona")

    if estado != "Aberto":
        raise HTTPException(status_code=403, detail="Cardápio fechado. Não é possível fazer pedidos.")

    # Verifica se o usuario existe
    usuario = session.get(Usuario, payload.usuario_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    if not usuario.ativo:
        raise HTTPException(status_code=403, detail="Usuário inativo não pode realizar pedidos.")

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
    pedido_id: int,
    session: Session = Depends(get_session),
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
async def abrir_cardapio_manual(
    session: Session = Depends(get_session),
    auth: AuthAccount = Depends(require_admin),
):
    """Abre o cardápio manualmente (para admin/RH)."""
    if _is_weekend():
        raise HTTPException(status_code=403, detail="No sábado e domingo o cardápio não funciona")

    await abre_cardapio()
    return EstadoResponse(estado=estado)


@app.post("/api/estado/fechar", response_model=EstadoResponse)
async def fechar_cardapio_manual(
    session: Session = Depends(get_session),
    auth: AuthAccount = Depends(require_admin),
):
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
def relatorio_mensal(
    session: Session = Depends(get_session),
    auth: AuthAccount = Depends(require_admin),
):
    """Relatório mensal detalhado (período 26→25) — mês atual."""
    month_start, month_end = _periodo_mensal()
    return _gerar_relatorio_mensal(session, month_start, month_end)


@app.get("/api/relatorios/mensal-anterior", response_model=ResumoMensalResponse)
def relatorio_mensal_anterior(
    session: Session = Depends(get_session),
    auth: AuthAccount = Depends(require_admin),
):
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

def _enviar_email_debug(session: Session) -> dict[str, str]:
    """Monta e envia e-mail de debug com pedidos do dia."""
    from app.config import settings as _s

    if not _s.mail_smtp_server:
        raise HTTPException(status_code=400, detail="SMTP não configurado (MAIL_SMTP_SERVER vazio).")
    if not _s.mail_to:
        raise HTTPException(status_code=400, detail="Destinatário não configurado (MAIL_TO vazio).")

    pedidos = processar_pedidos(session)
    resumo = agrupar_pedidos(pedidos)
    html = renderizar_email_pedidos(pedidos, resumo)
    try:
        enviados = enviar_email(html)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao enviar: {e}")

    return {"status": "ok", "message": f"E-mail enviado para {';'.join(enviados)}"}


@app.post("/api/mail/debug")
def enviar_email_debug(
    session: Session = Depends(get_session),
    auth: AuthAccount = Depends(require_admin),
):
    """Envia e-mail de debug com os pedidos do dia para o destinatário configurado."""
    return _enviar_email_debug(session)


@app.get("/api/mail/test")
def teste_email(
    session: Session = Depends(get_session),
    auth: AuthAccount = Depends(require_admin),
):
    """Compatibilidade: rota antiga de teste de e-mail."""
    return _enviar_email_debug(session)


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


@app.get("/", include_in_schema=False)
@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str = ""):
    """Serve arquivos estáticos do frontend e faz fallback para index.html."""
    if full_path.startswith("api/") or full_path == "api" or full_path.startswith("ws"):
        raise HTTPException(status_code=404, detail="Rota não encontrada")

    frontend_dist_dir = _resolve_frontend_dist_dir()
    if not frontend_dist_dir:
        raise HTTPException(status_code=404, detail="Frontend build não encontrado")

    base_dir = frontend_dist_dir.resolve()
    requested_path = (base_dir / full_path).resolve()

    try:
        requested_path.relative_to(base_dir)
    except ValueError:
        raise HTTPException(status_code=404, detail="Arquivo inválido")

    if requested_path.is_file():
        return FileResponse(requested_path)

    candidates = []
    if full_path:
        candidates.extend([
            (base_dir / f"{full_path}.html").resolve(),
            (base_dir / full_path / "index.html").resolve(),
        ])

    for candidate in candidates:
        try:
            candidate.relative_to(base_dir)
        except ValueError:
            continue
        if candidate.is_file():
            return FileResponse(candidate)

    index_file = base_dir / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html do frontend não encontrado")
    return FileResponse(index_file)
