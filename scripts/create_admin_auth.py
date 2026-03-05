#!/usr/bin/env python3
import os

from app.database import engine
from app.models import SQLModel, Usuario, AuthAccount
from app.auth import hash_password
from sqlmodel import Session, select

SQLModel.metadata.create_all(engine)

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "garten").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
ADMIN_NOME = os.getenv("ADMIN_NOME", "garten").strip()

if not ADMIN_PASSWORD:
    raise ValueError("ADMIN_PASSWORD não definida. Ex.: ADMIN_PASSWORD='ga76eng' python scripts/create_admin_auth.py")

with Session(engine) as s:
    user = s.exec(select(Usuario).where(Usuario.nome == ADMIN_NOME)).first()
    if not user:
        user = Usuario(nome=ADMIN_NOME, ativo=True)
        s.add(user); s.commit(); s.refresh(user)
    existing = s.exec(select(AuthAccount).where(AuthAccount.username == ADMIN_USERNAME)).first()
    if not existing:
        aa = AuthAccount(
            usuario_id=user.id,
            username=ADMIN_USERNAME,
            senha_hash=hash_password(ADMIN_PASSWORD),
            is_admin=True,
        )
        s.add(aa)
    else:
        existing.usuario_id = user.id
        existing.senha_hash = hash_password(ADMIN_PASSWORD)
        existing.is_admin = True
        s.add(existing)
    s.commit()

    legacy = s.exec(select(AuthAccount).where(AuthAccount.username == "admin")).first()
    if legacy and legacy.username != ADMIN_USERNAME:
        s.delete(legacy)
        s.commit()

    print(f"admin auth upserted for username '{ADMIN_USERNAME}'")
