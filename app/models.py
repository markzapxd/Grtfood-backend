"""Modelos SQLModel — equivalentes às tabelas Peewee do sistema antigo."""

from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel, Relationship


class Usuario(SQLModel, table=True):
    """Tabela de usuários (colaboradores)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str = Field(unique=True, index=True)
    ativo: bool = Field(default=True, index=True)
    
    auth_accounts: list["AuthAccount"] = Relationship(back_populates="usuario")


class AuthAccount(SQLModel, table=True):
    """Conta de autenticação separada do `Usuario`.

    Guarda `username` e `senha_hash` e referencia o colaborador em `usuario_id`.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuario.id", index=True)
    username: str = Field(index=True, unique=True)
    senha_hash: Optional[str] = None
    is_admin: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    usuario: Optional["Usuario"] = Relationship(back_populates="auth_accounts")


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


class AutoPedidoSemanal(SQLModel, table=True):
    """Configuração de pedido automático semanal por usuário."""

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuario.id", unique=True, index=True)
    ativo: bool = Field(default=True, index=True)
    criado_por_auth_id: int = Field(foreign_key="authaccount.id", index=True)
    criado_em: datetime = Field(default_factory=datetime.utcnow)
    atualizado_em: datetime = Field(default_factory=datetime.utcnow)
    semana_referencia: date = Field(default_factory=date.today, index=True)

class RefreshToken(SQLModel, table=True):

    id: Optional[int] = Field(default=None, primary_key=True)
    auth_account_id: int = Field(foreign_key="authaccount.id", index=True)
    token: str
    expires_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)