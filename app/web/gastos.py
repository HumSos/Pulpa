from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, Request

from app.modelos import MetodoPago
from app.servicios import gastos as servicio
from app.servicios import proveedores as servicio_proveedores
from app.servicios.errores import DatoInvalidoError
from app.servicios.kpis import periodo_mes_actual
from app.web.deps import DbSession
from app.web.formularios import leer_decimal, leer_entero
from app.web.plantillas import templates

router = APIRouter(prefix="/gastos", tags=["gastos"])


def _periodo(desde: str, hasta: str):
    actual = periodo_mes_actual()
    try:
        inicio = date.fromisoformat(desde) if desde else actual.desde
        fin = date.fromisoformat(hasta) if hasta else actual.hasta
    except ValueError:
        return actual.desde, actual.hasta
    return (fin, inicio) if fin < inicio else (inicio, fin)


def _contexto(db, desde: date, hasta: date, error: str | None = None) -> dict:
    return {
        "gastos": servicio.listar(db, desde, hasta),
        "total": servicio.total(db, desde, hasta),
        "por_categoria": servicio.por_categoria(db, desde, hasta),
        "categorias": servicio.categorias_usadas(db),
        "proveedores": servicio_proveedores.listar_proveedores(db),
        "metodos": list(MetodoPago),
        "desde": desde,
        "hasta": hasta,
        "hoy": date.today().isoformat(),
        "error": error,
    }


@router.get("")
def lista(request: Request, db: DbSession, desde: str = "", hasta: str = ""):
    inicio, fin = _periodo(desde, hasta)
    return templates.TemplateResponse(request, "gastos/lista.html", _contexto(db, inicio, fin))


@router.post("")
def crear(
    request: Request,
    db: DbSession,
    categoria: Annotated[str, Form()] = "",
    concepto: Annotated[str, Form()] = "",
    monto: Annotated[str, Form()] = "",
    fecha: Annotated[str, Form()] = "",
    metodo: Annotated[str, Form()] = "efectivo",
    proveedor_id: Annotated[str, Form()] = "",
    referencia: Annotated[str, Form()] = "",
):
    inicio, fin = _periodo("", "")
    error = None
    try:
        cantidad = leer_decimal(monto)
        if cantidad is None:
            raise DatoInvalidoError("Captura el monto del gasto")
        servicio.registrar(
            db,
            servicio.DatosGasto(
                categoria=categoria,
                concepto=concepto,
                monto=cantidad,
                fecha=date.fromisoformat(fecha) if fecha else None,
                metodo=metodo,
                proveedor_id=leer_entero(proveedor_id, "El proveedor"),
                referencia=referencia,
            ),
        )
        db.commit()
    except (DatoInvalidoError, ValueError) as exc:
        db.rollback()
        error = str(exc)
    return templates.TemplateResponse(
        request, "gastos/_contenido.html", _contexto(db, inicio, fin, error)
    )


@router.post("/{gasto_id}/eliminar")
def eliminar(request: Request, db: DbSession, gasto_id: int):
    inicio, fin = _periodo("", "")
    error = None
    try:
        servicio.eliminar(db, gasto_id)
        db.commit()
    except DatoInvalidoError as exc:
        db.rollback()
        error = str(exc)
    return templates.TemplateResponse(
        request, "gastos/_contenido.html", _contexto(db, inicio, fin, error)
    )