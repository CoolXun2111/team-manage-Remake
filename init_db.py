"""
数据库初始化脚本。
创建表结构、执行轻量迁移，并写入默认系统设置。
"""

import asyncio
from pathlib import Path

import bcrypt
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal, init_db
from app.db_migrations import run_auto_migration
from app.models import Setting


def ensure_database_directory() -> None:
    """确保 SQLite 数据库文件所在目录存在。"""
    database_url = settings.database_url
    if not database_url.startswith("sqlite"):
        return

    db_path = database_url.split("///", 1)[-1].split("?", 1)[0]
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)


async def create_default_settings() -> None:
    """创建默认系统设置。"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Setting).where(Setting.key == "initialized")
        )
        existing = result.scalar_one_or_none()

        if existing:
            print("数据库已初始化，跳过默认数据写入")
            return

        password_hash = bcrypt.hashpw(
            settings.admin_password.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")

        default_settings = [
            Setting(
                key="initialized",
                value="true",
                description="数据库初始化标记",
            ),
            Setting(
                key="admin_password_hash",
                value=password_hash,
                description="管理员密码哈希",
            ),
            Setting(
                key="proxy",
                value=settings.proxy,
                description="代理地址 (支持 http:// 和 socks5://)",
            ),
            Setting(
                key="proxy_enabled",
                value=str(settings.proxy_enabled).lower(),
                description="是否启用代理",
            ),
            Setting(
                key="log_level",
                value=settings.log_level,
                description="日志级别",
            ),
            Setting(
                key="default_team_seat_limit",
                value="6",
                description="新导入 Team 的默认席位上限",
            ),
            Setting(
                key="auto_reinvite_enabled",
                value="false",
                description="是否启用失效母号自动补邀",
            ),
            Setting(
                key="auto_reinvite_interval_seconds",
                value="300",
                description="自动补邀巡检间隔(秒)",
            ),
        ]

        session.add_all(default_settings)
        await session.commit()
        print("默认设置已创建")


async def main() -> None:
    """初始化数据库。"""
    print("开始初始化数据库...")

    ensure_database_directory()

    await init_db()
    print("数据库表创建完成")

    run_auto_migration()
    print("数据库迁移检查完成")

    await create_default_settings()

    print("数据库初始化完成!")


if __name__ == "__main__":
    asyncio.run(main())
