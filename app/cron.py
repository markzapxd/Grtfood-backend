"""Agendamento de tarefas — abertura e fechamento automático do cardápio."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.cron import CronTrigger

from app.config import settings


scheduler: AsyncIOScheduler | None = None


def get_menu_open_hour() -> tuple[str, str]:
    """Retorna (hora, minuto) de abertura do cardápio."""
    parts = settings.menu_open_hour.split(":")
    return parts[0], parts[1] if len(parts) > 1 else "0"


def get_menu_close_hour() -> tuple[str, str]:
    """Retorna (hora, minuto) de fechamento do cardápio."""
    parts = settings.menu_close_hour.split(":")
    return parts[0], parts[1] if len(parts) > 1 else "0"


def init_scheduler(abre_cardapio_func, fecha_cardapio_func) -> AsyncIOScheduler:
    """Inicializa o scheduler com os jobs de abrir/fechar cardápio."""
    global scheduler

    jobstores = {
        "default": MemoryJobStore()
    }
    job_defaults = {
        "coalesce": False,
        "max_instances": 3,
        "misfire_grace_time": 32400,
    }

    scheduler = AsyncIOScheduler(
        jobstores=jobstores,
        job_defaults=job_defaults,
    )

    hour_open, minute_open = get_menu_open_hour()
    hour_close, minute_close = get_menu_close_hour()

    # Fecha cardápio (seg-sáb)
    trigger_fecha = CronTrigger(
        day_of_week="mon-sat",
        hour=int(hour_close),
        minute=int(minute_close),
        second=0,
    )
    scheduler.add_job(
        fecha_cardapio_func,
        id="fecha_cardapio",
        trigger=trigger_fecha,
        replace_existing=True,
    )

    # Abre cardápio (seg-sáb)
    trigger_abre = CronTrigger(
        day_of_week="mon-sat",
        hour=int(hour_open),
        minute=int(minute_open),
        second=0,
    )
    scheduler.add_job(
        abre_cardapio_func,
        id="abre_cardapio",
        trigger=trigger_abre,
        replace_existing=True,
    )

    scheduler.start()
    return scheduler
