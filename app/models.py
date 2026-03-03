"""Modelos SQLModel — equivalentes às tabelas Peewee do sistema antigo."""

from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Usuario(SQLModel, table=True):
    """Tabela de usuários (colaboradores)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str = Field(unique=True, index=True)


class Cardapio(SQLModel, table=True):
    """Cardápio do dia — armazena os itens e opções múltiplas como JSON."""

    id: Optional[int] = Field(default=None, primary_key=True)
    data: date = Field(unique=True, index=True)
    cardapio_json: str = Field(default="{}")


class Pedido(SQLModel, table=True):
    """Pedido de almoço feito por um usuário."""

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuario.id", index=True)
    pedido_json: str = Field(default="{}")
    obs: str = Field(default="")
    data: datetime = Field(default_factory=datetime.now)
