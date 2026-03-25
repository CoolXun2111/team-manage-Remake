"""
FastAPI application entrypoint for the GPT Team management system.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import AsyncSessionLocal, close_db, init_db
from app.routes import admin, api, auth, redeem, user, warranty
from app.services.auth import auth_service
from app.services.auto_reinvite import auto_reinvite_service
from app.services.auto_status_refresh import auto_status_refresh_service
from app.webui import render_template_response


BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Initialize and clean up application resources."""
    logger.info("系统正在启动，正在初始化数据库...")

    try:
        db_file = settings.database_url.split("///")[-1]
        Path(db_file).parent.mkdir(parents=True, exist_ok=True)

        await init_db()

        from app.db_migrations import run_auto_migration

        run_auto_migration()

        async with AsyncSessionLocal() as session:
            await auth_service.initialize_admin_password(session)

        await auto_reinvite_service.start()
        await auto_status_refresh_service.start()
        logger.info("数据库初始化完成")
    except Exception as exc:
        logger.error(f"数据库初始化失败: {exc}")

    yield

    await auto_reinvite_service.stop()
    await auto_status_refresh_service.stop()
    await close_db()
    logger.info("系统正在关闭，已释放数据库连接")


app = FastAPI(
    title=settings.app_name,
    description="ChatGPT Team 账号管理和兑换码自动邀请系统",
    version=settings.app_version,
    lifespan=lifespan,
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Redirect HTML auth failures to the login page."""
    if exc.status_code in (401, 403):
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse(url="/login")

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="session",
    max_age=14 * 24 * 60 * 60,
    same_site="lax",
    https_only=False,
)

app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

app.include_router(user.router)
app.include_router(redeem.router)
app.include_router(warranty.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(api.router)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render the login page."""
    return render_template_response(
        request,
        "auth/login.html",
        {"user": None},
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Serve the site favicon."""
    return FileResponse(APP_DIR / "static" / "favicon.png")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )
