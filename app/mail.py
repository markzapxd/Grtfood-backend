"""Envio de e-mails via SMTP com templates Jinja2"""

import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.config import settings

SMTP_TIMEOUT_SECONDS = 15

# Carrega templates Jinja2 do diretório templates/
_template_dir = Path(__file__).parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(_template_dir)), autoescape=True)


def renderizar_email_pedidos(pedidos: list[dict], resumo: list[dict]) -> str:
    """Renderiza o template HTML de e-mail com os pedidos do dia."""
    template = _jinja_env.get_template("pedidos.html")
    return template.render(
        pedidos=pedidos,
        resumo=resumo,
        diaDeHoje=datetime.now().strftime("%d/%m/%Y"),
        anoAtual=datetime.now().strftime("%Y"),
    )


def enviar_email(conteudo_html: str) -> list[str]:
    """Envia e-mail HTML via SMTP e retorna destinatários enviados."""
    if not settings.mail_smtp_server:
        raise RuntimeError("Servidor SMTP não configurado (MAIL_SMTP_SERVER vazio).")

    destinatarios = [d.strip() for d in settings.mail_to.split(";") if d.strip()]
    if not destinatarios:
        raise RuntimeError("Nenhum destinatário configurado (MAIL_TO vazio).")

    msg = EmailMessage()
    msg.add_header("Content-Type", "text/html; charset=UTF-8")
    msg.set_payload(conteudo_html, "UTF-8")
    msg["Subject"] = "[GRT FOOD] Pedido de comida {}".format(
        datetime.now().strftime("%d/%m/%Y")
    )
    msg["From"] = settings.mail_smtp_user
    msg["To"] = destinatarios

    etapa = "init"
    try:
        print(
            "[MAIL] Iniciando envio SMTP "
            f"server={settings.mail_smtp_server} port={settings.mail_smtp_port} "
            f"user={settings.mail_smtp_user} destinatarios={len(destinatarios)}"
        )

        etapa = "connect"
        s = smtplib.SMTP(
            settings.mail_smtp_server,
            port=settings.mail_smtp_port,
            timeout=SMTP_TIMEOUT_SECONDS,
        )

        etapa = "ehlo"
        s.ehlo()

        etapa = "starttls"
        s.starttls()

        etapa = "login"
        s.login(settings.mail_smtp_user, settings.mail_smtp_password)

        etapa = "send_message"
        s.send_message(msg)

        etapa = "quit"
        s.quit()
        print(f"[MAIL] E-mail enviado para {destinatarios}")
        return destinatarios
    except Exception as e:
        print(f"[MAIL] Erro na etapa '{etapa}': {e}")
        raise RuntimeError(f"Falha SMTP: {e}") from e
