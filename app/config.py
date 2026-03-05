"""Configurações da aplicação carregadas via variáveis de ambiente."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configurações tipadas do GRT Food."""

    # Servidor
    food_port: int = 8000
    development: bool = False

    # Cardápio — horários
    menu_open_hour: str = "0:00"
    menu_close_hour: str = "9:00"

    # Cardápio — itens automáticos
    automatic_menu_items: str = ""

    # E-mail SMTP
    mail_smtp_server: str = ""
    mail_smtp_port: int = 587
    mail_smtp_user: str = ""
    mail_smtp_password: str = ""
    mail_to: str = ""

    # Banco de dados (PostgreSQL)
    database_url: str = "postgresql://postgres:postgres@localhost:5432/grtfood"

    # Auth / Tokens
    secret_key: str = "troca_pra_uma_chave_secreta_forte"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # CORS
    cors_origins: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
