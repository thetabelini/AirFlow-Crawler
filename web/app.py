"""Tela e API de leitura. Cada projeto com projects/<nome>/web.py ganha as rotas /<nome>/.

Acesso:
- cabeçalho X-API-Key com uma chave criada por scripts/api-keys.sh (para quem consome a API),
  com limite por minuto e por dia (web/apikeys.py); passando dele, a resposta é 429 com Retry-After
- WEB_USERS="usuario:senha,outro:senha2" libera esses usuários (HTTP Basic, vale para a tela e a API)
- WEB_PUBLIC=true abre para qualquer pessoa
"""

import importlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import APIKeyHeader, HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from core.projects import NAME, projects_dir
from web import apikeys

log = logging.getLogger(__name__)
security = HTTPBasic(auto_error=False)
api_key_header = APIKeyHeader(
    name="X-API-Key", auto_error=False, description="Chave de API recebida do administrador"
)


def parse_users(raw: str) -> dict[str, str]:
    users = {}
    for item in raw.split(","):
        user, sep, password = item.strip().partition(":")
        if sep and user and password:
            users[user] = password
    return users


def is_public() -> bool:
    return os.environ.get("WEB_PUBLIC", "false").strip().lower() in ("1", "true", "yes", "sim")


def unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": 'Basic realm="dados", charset="UTF-8"'},
    )


def seconds_until_next(window: str, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    if window == "minute":
        start = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return max(1, int((start - now).total_seconds()) + 1)


def enforce_limits(usage: apikeys.KeyUsage, response: Response) -> None:
    per_minute, per_day = apikeys.limits()
    if usage.minute_hits > per_minute:
        window, limit = "minute", per_minute
    elif usage.day_hits > per_day:
        window, limit = "day", per_day
    else:
        response.headers["X-RateLimit-Limit-Minute"] = str(per_minute)
        response.headers["X-RateLimit-Remaining-Minute"] = str(per_minute - usage.minute_hits)
        response.headers["X-RateLimit-Limit-Day"] = str(per_day)
        response.headers["X-RateLimit-Remaining-Day"] = str(per_day - usage.day_hits)
        return
    label = "por minuto" if window == "minute" else "por dia"
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Limite de {limit} requisições {label} atingido para esta chave",
        headers={"Retry-After": str(seconds_until_next(window))},
    )


def require_user(
    response: Response,
    credentials: HTTPBasicCredentials | None = Depends(security),
    api_key: str | None = Depends(api_key_header),
) -> str | None:
    if is_public():
        return None
    if api_key:
        usage = apikeys.check_api_key(api_key)
        if usage is None:
            raise unauthorized("Chave de API inválida ou revogada")
        enforce_limits(usage, response)
        return f"chave:{usage.name}"
    users = parse_users(os.environ.get("WEB_USERS", ""))
    if credentials is not None:
        expected = users.get(credentials.username)
        if expected is not None and secrets.compare_digest(
            credentials.password.encode(), expected.encode()
        ):
            return credentials.username
    raise unauthorized()


def web_projects() -> list[str]:
    return sorted(
        path.parent.name
        for path in projects_dir().glob("*/web.py")
        if NAME.match(path.parent.name)
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="AirFlow-Crawler: dados",
        description=(
            "Leitura dos dados coletados. Autentique com a chave de API no cabeçalho "
            "`X-API-Key` (botão Authorize) ou com usuário e senha."
        ),
    )
    templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
    protected = [Depends(require_user)]
    projects = web_projects()

    if not is_public() and not parse_users(os.environ.get("WEB_USERS", "")):
        log.warning("WEB_USERS vazio e WEB_PUBLIC desligado: ninguém consegue entrar")

    @app.get("/health", include_in_schema=False)
    def health() -> dict:
        return {"status": "ok"}

    home = APIRouter(dependencies=protected)

    @home.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index(request: Request):
        if len(projects) == 1:
            return RedirectResponse(f"/{projects[0]}/")
        return templates.TemplateResponse(request, "index.html", {"projects": projects})

    app.include_router(home)
    for project in projects:
        module = importlib.import_module(f"projects.{project}.web")
        app.include_router(module.router, prefix=f"/{project}", dependencies=protected)
    return app


app = create_app()
