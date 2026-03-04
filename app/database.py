"""Conexão e inicialização do banco de dados via SQLModel.

Suporta SQLite (desenvolvimento local) e PostgreSQL (Railway/produção).
O tipo de banco é detectado automaticamente pela DATABASE_URL.
"""

import os

from sqlmodel import SQLModel, Session, create_engine

from app.config import settings

_url = settings.database_url

# Railway fornece URLs com prefixo "postgres://" que o SQLAlchemy
# não reconhece — precisa ser "postgresql://".
if _url.startswith("postgres://"):
    _url = _url.replace("postgres://", "postgresql://", 1)

_is_sqlite = False

# Configuração do engine (exclusivo para PostgreSQL)
engine = create_engine(
    _url,
    echo=settings.development,
)


def create_db_and_tables() -> None:
    """Cria todas as tabelas definidas nos modelos SQLModel."""
    SQLModel.metadata.create_all(engine)


def get_session():
    """Dependency do FastAPI para injetar uma sessão do banco."""
    with Session(engine) as session:
        yield session

