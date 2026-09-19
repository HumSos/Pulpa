from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import settings
from app.web import clientes, cobranza, compras, pedidos, productos, proveedores, tablero
from app.web.deps import DbSession

app = FastAPI(title=settings.app_nombre)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")
app.include_router(productos.router)
app.include_router(clientes.router)
app.include_router(pedidos.router)
app.include_router(proveedores.router)
app.include_router(compras.router)
app.include_router(cobranza.router)
app.include_router(tablero.router)


@app.get("/salud")
def salud(db: DbSession):
    db.execute(text("SELECT 1"))
    return {"estado": "ok", "motor": db.get_bind().dialect.name}