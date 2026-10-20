"""Tela e API de leitura. Cada projeto com projects/<nome>/web.py ganha as rotas /<nome>/.

Acesso:
- WEB_USERS="usuario:senha,outro:senha2" libera esses usuários (HTTP Basic, vale para a tela e a API)
- WEB_PUBLIC=true abre para qualquer pessoa
"""

import importlib
import logging
import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from core.projects import NAME, projects_dir

log = logging.getLogger(__name__)
security = HTTPBasic(auto_error=False)


def parse_users(raw: str) -> dict[str, str]:
    users = {}
    for item in raw.split(","):
        user, sep, password = item.strip().partition(":")
        if sep and user and password:
            users[user] = password
    return users


def is_public() -> bool:
    return os.environ.get("WEB_PUBLIC", "false").strip().lower() in ("1", "true", "yes", "sim")


def require_user(credentials: HTTPBasicCredentials | None = Depends(security)) -> str | None:
    if is_public():
        return None
    users = parse_users(os.environ.get("WEB_USERS", ""))
    if credentials is not None:
        expected = users.get(credentials.username)
        if expected is not None and secrets.compare_digest(
            credentials.password.encode(), expected.encode()
        ):
            return credentials.username
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        headers={"WWW-Authenticate": 'Basic realm="dados", charset="UTF-8"'},
    )


def web_projects() -> list[str]:
    return sorted(
        path.parent.name
        for path in projects_dir().glob("*/web.py")
        if NAME.match(path.parent.name)
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="AirFlow-Crawler: dados",
        description="Leitura dos dados coletados. Autentique com o mesmo usuário e senha da tela.",
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
