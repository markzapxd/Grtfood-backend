from datetime import datetime, timedelta
from typing import Optional
import uuid

from passlib.context import CryptContext
from jose import jwt, JWTError
from sqlalchemy import inspect, text
from sqlmodel import Session, select

from app.config import settings
from app.database import engine
from app.models import AuthAccount, RefreshToken

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def create_access_token(sub_auth_id: int, expires_minutes: Optional[int] = None) -> str:
    if expires_minutes is None:
        expires_minutes = settings.access_token_expire_minutes
    now = datetime.utcnow()
    exp = now + timedelta(minutes=expires_minutes)
    payload = {"sub": str(sub_auth_id), "exp": int(exp.timestamp())}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        sub = payload.get("sub")
        return int(sub)
    except JWTError:
        return None


def create_refresh_token(auth_account_id: int, days: Optional[int] = None) -> str:
    if days is None:
        days = settings.refresh_token_expire_days
    token = str(uuid.uuid4())
    expires = datetime.utcnow() + timedelta(days=days)
    with Session(engine) as session:
        usuario_id = None
        auth_account = session.get(AuthAccount, auth_account_id)
        if auth_account:
            usuario_id = auth_account.usuario_id

        columns = {c["name"] for c in inspect(engine).get_columns("refreshtoken")}
        values = {
            "token": token,
            "auth_account_id": auth_account_id,
            "expires_at": expires,
            "created_at": datetime.utcnow(),
            "usuario_id": usuario_id,
            "user_id": usuario_id,
        }

        insert_columns = [
            "token",
            "auth_account_id",
            "expires_at",
            "created_at",
            "usuario_id",
            "user_id",
        ]
        insert_columns = [name for name in insert_columns if name in columns]

        placeholders = ", ".join(f":{name}" for name in insert_columns)
        sql = f"INSERT INTO refreshtoken ({', '.join(insert_columns)}) VALUES ({placeholders})"
        session.execute(text(sql), {name: values[name] for name in insert_columns})
        session.commit()
    return token


def validate_refresh_token(token: str) -> Optional[int]:
    with Session(engine) as session:
        stmt = select(RefreshToken).where(RefreshToken.token == token)
        rt = session.exec(stmt).first()
        if not rt:
            return None
        if rt.expires_at < datetime.utcnow():
            session.delete(rt)
            session.commit()
            return None
        return rt.auth_account_id


def revoke_refresh_token(token: str) -> None:
    with Session(engine) as session:
        stmt = select(RefreshToken).where(RefreshToken.token == token)
        rt = session.exec(stmt).first()
        if rt:
            session.delete(rt)
            session.commit()


def get_auth_account_by_id(auth_id: int) -> Optional[AuthAccount]:
    with Session(engine) as session:
        return session.get(AuthAccount, auth_id)


def get_auth_account_by_username(username: str) -> Optional[AuthAccount]:
    normalized = username.strip().lower()
    with Session(engine) as session:
        stmt = select(AuthAccount).where(AuthAccount.username == normalized)
        return session.exec(stmt).first()
