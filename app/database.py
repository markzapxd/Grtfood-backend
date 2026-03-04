
import os

from sqlalchemy import inspect, text
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

    inspector = inspect(engine)
    tabelas = inspector.get_table_names()
    if "usuario" not in tabelas:
        return

    colunas = {c["name"] for c in inspector.get_columns("usuario")}
    if "ativo" in colunas:
        return

    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE usuario ADD COLUMN ativo BOOLEAN NOT NULL DEFAULT TRUE")
        )


def get_session():
    """Dependency do FastAPI para injetar uma sessão do banco."""
    with Session(engine) as session:
        yield session

