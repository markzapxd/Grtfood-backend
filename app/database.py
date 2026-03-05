
import os
from datetime import datetime, timedelta

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

    if "refreshtoken" in tabelas:
        refresh_cols = {c["name"] for c in inspector.get_columns("refreshtoken")}
        if "auth_account_id" not in refresh_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE refreshtoken ADD COLUMN auth_account_id INTEGER"))
                if "user_id" in refresh_cols:
                    conn.execute(
                        text(
                            "UPDATE refreshtoken SET auth_account_id = user_id "
                            "WHERE auth_account_id IS NULL"
                        )
                    )
                if "usuario_id" in refresh_cols:
                    conn.execute(
                        text(
                            "UPDATE refreshtoken SET auth_account_id = usuario_id "
                            "WHERE auth_account_id IS NULL"
                        )
                    )
                conn.execute(
                    text("DELETE FROM refreshtoken WHERE auth_account_id IS NULL")
                )

        refresh_cols = {c["name"] for c in inspector.get_columns("refreshtoken")}
        with engine.begin() as conn:
            if "expires_at" not in refresh_cols:
                conn.execute(text("ALTER TABLE refreshtoken ADD COLUMN expires_at DATETIME"))
                conn.execute(
                    text(
                        "UPDATE refreshtoken SET expires_at = :expires_at "
                        "WHERE expires_at IS NULL"
                    )
                    , {"expires_at": datetime.utcnow() + timedelta(days=7)}
                )

            if "created_at" not in refresh_cols:
                conn.execute(text("ALTER TABLE refreshtoken ADD COLUMN created_at DATETIME"))
                conn.execute(
                    text(
                        "UPDATE refreshtoken SET created_at = :created_at "
                        "WHERE created_at IS NULL"
                    )
                    , {"created_at": datetime.utcnow()}
                )

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

