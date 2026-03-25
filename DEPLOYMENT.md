# 部署手册（生产可用）

本文档用于生产环境部署、更新、回滚与排障。推荐使用 Docker Compose 方式。

## 1. 部署前检查

在正式部署前，先确认：

- 服务器已安装 `Docker` 与 `Docker Compose`。
- 端口未占用（默认 `8008`）。
- 已准备独立管理员密码与随机 `SECRET_KEY`。
- 已确认是否需要代理（`PROXY` / `PROXY_ENABLED`）。
- 已确认防火墙放行服务端口。

## 2. Docker 首次部署（推荐）

```bash
git clone https://github.com/CoolXun2111/team-manage-Remake.git
cd team-manage-Remake
cp .env.example .env
mkdir -p data
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:${HOST_PORT:-8008}/health
```

访问地址：

- 用户兑换页：`http://<服务器IP>:<HOST_PORT>/`
- 管理登录页：`http://<服务器IP>:<HOST_PORT>/login`

## 3. 关键环境变量建议

生产环境至少修改以下变量（`.env`）：

```env
DEBUG=False
SECRET_KEY=请替换为高强度随机字符串
ADMIN_PASSWORD=请替换为复杂密码
HOST_PORT=8008
APP_PORT=8008
```

说明：

- Docker 下数据库会使用 `DATABASE_URL=sqlite+aiosqlite:////app/data/team_manage.db`（由 `docker-compose.yml` 注入）。
- 数据文件位于宿主机 `./data/team_manage.db`，容器删除后不会丢失。

## 4. 更新流程（低风险）

```bash
# 拉代码
git pull --ff-only origin main

# 备份数据库（强烈建议）
cp data/team_manage.db "data/team_manage.db.bak.$(date +%F-%H%M%S)"

# 重建并启动
docker compose up -d --build

# 健康检查
docker compose ps
curl http://127.0.0.1:${HOST_PORT:-8008}/health
```

## 5. 快速回滚

如果更新后异常：

1. 回到上一个 commit 并重启容器。
2. 或恢复数据库备份并重启容器。

示例：

```bash
# 回到上一个版本（示例）
git checkout <上一个稳定提交ID>
docker compose up -d --build

# 恢复数据库（示例）
cp data/team_manage.db.bak.2026-03-25-140000 data/team_manage.db
docker compose restart
```

## 6. 常见部署问题与处理

### 6.1 端口冲突（服务起不来）

现象：`docker compose up` 报端口已占用。  
处理：修改 `.env` 中 `HOST_PORT`，例如 `HOST_PORT=8009`。

### 6.2 `.env` 不存在或变量未生效

现象：容器启动后配置不是预期值。  
处理：确认项目根目录存在 `.env`，并执行 `docker compose up -d --build` 重新加载。

### 6.3 数据未持久化

现象：重建容器后数据丢失。  
处理：确认存在宿主机目录 `./data`，且容器内映射 `/app/data` 正常。

### 6.4 GitHub 拉取失败（代理导致）

现象：`git pull` 报 `Failed to connect to github.com via 127.0.0.1`。  
处理：

```bash
git config --global --unset http.proxy
git config --global --unset https.proxy
```

如确实需要代理，请确保代理软件已运行且端口正确。

### 6.5 安全风险（默认值未修改）

现象：`DEBUG=True`、`SECRET_KEY` 默认值、`ADMIN_PASSWORD` 默认值。  
处理：上线前务必改为生产值，并限制管理入口访问来源。

### 6.6 访问正常但功能请求失败

建议排查顺序：

1. `docker compose logs -f`
2. 检查 `PROXY` 配置
3. 检查 Team Token 是否有效
4. 检查服务器网络与 DNS

## 7. 运维常用命令

```bash
# 查看运行状态
docker compose ps

# 实时日志
docker compose logs -f

# 重启服务
docker compose restart

# 停止服务
docker compose down
```

## 8. 可选：非 Docker 部署（Python）

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python init_db.py
python -m uvicorn app.main:app --host 0.0.0.0 --port 8008
```

生产环境建议配合 `systemd` 或进程管理器守护，不建议直接前台运行。

