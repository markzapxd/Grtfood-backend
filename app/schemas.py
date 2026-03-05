"""Schemas Pydantic para validação de request/response da API."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


# ─── Cardápio ───────────────────────────────────────────────

class CardapioPayload(BaseModel):
    """Corpo do cardápio — itens fixos + opções múltiplas."""

    items: list[str] = []
    multiplos: dict[str, list[str]] = {}


class CardapioResponse(BaseModel):
    """Resposta com o cardápio do dia."""

    id: int
    data: date
    items: list[str] = []
    multiplos: dict[str, list[str]] = {}


# ─── Pedido ─────────────────────────────────────────────────

class PedidoPayload(BaseModel):
    """Seleções feitas pelo usuário no pedido."""

    items: list[str] = []
    multiplos: dict[str, str] = {}


class PedidoCreate(BaseModel):
    """Corpo de criação de um novo pedido."""

    usuario_id: int
    pedido: PedidoPayload
    obs: str = ""


class PedidoResponse(BaseModel):
    """Pedido retornado pela API."""

    id: int
    usuario: str
    dataDoPedido: str
    pedido: PedidoPayload


class PedidoProcessado(BaseModel):
    """Pedido processado — itens removidos e opções selecionadas."""

    usuario: str
    removidos: list[str]
    selecionados: list[str]
    data: str


class ResumoAgrupado(BaseModel):
    """Resumo agrupado de pedidos (para e-mail/relatório)."""

    selecionados: str
    removidos: str
    quantidade: int


# ─── Usuário ────────────────────────────────────────────────

class UsuarioResponse(BaseModel):
    """Usuário retornado pela API."""

    id: int
    nome: str
    ativo: bool


class UsuarioCreate(BaseModel):
    """Criação de um novo usuário."""

    nome: str
    ativo: bool = True


class UsuarioStatusUpdate(BaseModel):
    """Atualização de status do usuário (ativo/inativo)."""

    ativo: bool


class AutoPedidoSemanalCreate(BaseModel):
    """Ativa pedido automático semanal para um usuário."""

    usuario_id: int


class AutoPedidoSemanalResponse(BaseModel):
    """Configuração de pedido automático semanal retornada pela API."""

    id: int
    usuario_id: int
    usuario_nome: str
    ativo: bool
    semana_referencia: date
    criado_em: datetime
    atualizado_em: datetime


# ─── Estado ─────────────────────────────────────────────────

class EstadoResponse(BaseModel):
    """Estado atual do cardápio."""

    estado: str


# ─── Relatório Mensal ───────────────────────────────────────

class ResumoMensalItem(BaseModel):
    """Resumo mensal por usuário."""

    usuario: str
    usuario_id: int
    qtde: int
    dias: dict[int, int] = {}


class ResumoMensalResponse(BaseModel):
    """Resposta completa do relatório mensal."""

    resumo: list[ResumoMensalItem]
    data_inicio: str
    data_fim: str
    gerado: str
    dias_no_mes: list[int] = []
