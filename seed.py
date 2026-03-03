"""Script para migrar dados do banco antigo (Peewee food.db) para o novo banco SQLModel."""

import os
import sqlite3
import sys

from sqlmodel import Session, select

from app.database import create_db_and_tables, engine
from app.models import Usuario


DEFAULT_OLD_DB = os.path.join(
    os.path.dirname(__file__), "..", "..", "app", "food.db"
)


def main(old_db_path: str | None = None):
    """Migra usuários do banco antigo para o novo."""
    old_db_path = old_db_path or DEFAULT_OLD_DB

    if not os.path.exists(old_db_path):
        print(f"Banco antigo não encontrado em: {old_db_path}")
        sys.exit(1)

    print(f"Lendo banco antigo: {old_db_path}")

    # Conecta ao banco antigo (SQLite direto, sem Peewee)
    conn = sqlite3.connect(old_db_path)
    cursor = conn.cursor()

    # Inicializa o banco novo
    create_db_and_tables()

    # ─── Migrar Usuários ────────────────────────────────────
    cursor.execute("SELECT id, nome FROM usuario ORDER BY nome")
    usuarios_antigos = cursor.fetchall()
    print(f"\nEncontrados {len(usuarios_antigos)} usuários no banco antigo.\n")

    with Session(engine) as session:
        count = 0
        for old_id, nome in usuarios_antigos:
            nome = nome.strip()
            if not nome:
                continue

            existing = session.exec(
                select(Usuario).where(Usuario.nome == nome)
            ).first()
            if existing:
                print(f"  Já existe: {nome}")
                continue

            usuario = Usuario(nome=nome)
            session.add(usuario)
            count += 1
            print(f"  Importando: {nome}")

        session.commit()
        print(f"\nTotal: {count} usuários importados.")

    conn.close()
    print("Migração concluída!")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    main(path)
