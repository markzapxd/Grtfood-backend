"""Envio de e-mails via SMTP com templates Jinja2"""

import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.config import settings

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


def enviar_email(conteudo_html: str) -> None:
    """Envia e-mail HTML via SMTP."""
    if not settings.mail_smtp_server:
        print("[MAIL] Servidor SMTP não configurado, e-mail não enviado.")
        return

    destinatarios = [d.strip() for d in settings.mail_to.split(";") if d.strip()]
    if not destinatarios:
        print("[MAIL] Nenhum destinatário configurado.")
        return

    msg = EmailMessage()
    msg.add_header("Content-Type", "text/html; charset=UTF-8")
    msg.set_payload(conteudo_html, "UTF-8")
    msg["Subject"] = "[GRT FOOD] Pedido de comida {}".format(
        datetime.now().strftime("%d/%m/%Y")
    )
    msg["From"] = settings.mail_smtp_user
    msg["To"] = destinatarios

    try:
        s = smtplib.SMTP(settings.mail_smtp_server, port=settings.mail_smtp_port)
        s.ehlo()
        s.starttls()
        s.login(settings.mail_smtp_user, settings.mail_smtp_password)
        s.send_message(msg)
        s.quit()
        print(f"[MAIL] E-mail enviado para {destinatarios}")
    except Exception as e:
        print(f"[MAIL] Erro ao enviar e-mail: {e}")
