"""Conexão e inicialização do banco de dados SQLite via SQLModel."""

import os

from sqlmodel import SQLModel, Session, create_engine

from app.config import settings

# Garante que o diretório data/ exista
_db_path = settings.database_url.replace("sqlite:///", "")
os.makedirs(os.path.dirname(_db_path) or ".", exist_ok=True)

engine = create_engine(
    settings.database_url,
    echo=settings.development,
    connect_args={"check_same_thread": False},
)


def create_db_and_tables() -> None:
    """Cria todas as tabelas definidas nos modelos SQLModel."""
    SQLModel.metadata.create_all(engine)


def get_session():
    """Dependency do FastAPI para injetar uma sessão do banco."""
    with Session(engine) as session:
        yield session
