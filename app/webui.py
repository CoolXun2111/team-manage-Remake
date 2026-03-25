from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import settings


BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def format_datetime(dt):
    """格式化日期时间。"""
    if not dt:
        return "-"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return dt

    import pytz

    if dt.tzinfo is not None:
        tz = pytz.timezone(settings.timezone)
        dt = dt.astimezone(tz)

    return dt.strftime("%Y-%m-%d %H:%M")


def escape_js(value):
    """转义字符串用于 JavaScript。"""
    if not value:
        return ""
    return (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


templates.env.filters["format_datetime"] = format_datetime
templates.env.filters["escape_js"] = escape_js


def render_template_response(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """稳定渲染模板，规避不同 Starlette 版本的 TemplateResponse 参数差异。"""
    template_context = dict(context or {})
    template_context.setdefault("request", request)

    for context_processor in templates.context_processors:
        template_context.update(context_processor(request))

    content = templates.get_template(name).render(template_context)
    return HTMLResponse(content=content, status_code=status_code)
