from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.config import settings
from app.web.deps import DbSession

WEB_DIR = Path(__file__).parent / "web"

app = FastAPI(title=settings.app_nombre)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=WEB_DIR / "templates")


@app.get("/")
def inicio(request: Request):
    return templates.TemplateResponse(request, "index.html", {"titulo": settings.app_nombre})


@app.get("/salud")
def salud(db: DbSession):
    db.execute(text("SELECT 1"))
    return {"estado": "ok", "motor": db.get_bind().dialect.name}