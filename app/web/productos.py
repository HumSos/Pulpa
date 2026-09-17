from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modelos import Producto
from app.servicios import catalogo
from app.web.deps import DbSession
from app.web.formularios import leer_decimal, leer_fecha
from app.web.plantillas import templates

router = APIRouter(prefix="/productos", tags=["productos"])




def _obtener(db: Session, producto_id: int) -> Producto:
    producto = db.get(Producto, producto_id)
    if producto is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return producto


def _contexto_precios(db: Session, producto: Producto, error: str | None = None) -> dict:
    ahora = datetime.now()
    historial = catalogo.historial_precios(db, producto.id)
    vigente = next((p for p in historial if p.vigente_desde <= ahora), None)
    return {
        "producto": producto,
        "historial": historial,
        "vigente": vigente,
        "ahora": ahora,
        "error": error,
    }


def _formulario_nuevo(request, db, error=None, datos=None, status_code=200):
    contexto = {"unidades": catalogo.listar_unidades(db), "error": error, "datos": datos or {}}
    return templates.TemplateResponse(
        request, "productos/nuevo.html", contexto, status_code=status_code
    )


@router.get("")
def lista(request: Request, db: DbSession, q: str = ""):
    productos = catalogo.listar_productos(db, q)
    contexto = {
        "productos": productos,
        "precios": catalogo.precios_vigentes(db, [p.id for p in productos]),
        "q": q,
    }
    es_htmx = request.headers.get("HX-Request") == "true"
    plantilla = "productos/_filas.html" if es_htmx else "productos/lista.html"
    return templates.TemplateResponse(request, plantilla, contexto)


@router.get("/nuevo")
def nuevo(request: Request, db: DbSession):
    return _formulario_nuevo(request, db)


@router.post("/nuevo")
def crear(
    request: Request,
    db: DbSession,
    codigo: Annotated[str, Form()],
    descripcion: Annotated[str, Form()],
    unidad_id: Annotated[int, Form()],
    precio: Annotated[str, Form()] = "",
):
    try:
        producto = catalogo.crear_producto(
            db, codigo, descripcion, unidad_id, leer_decimal(precio)
        )
        db.commit()
    except catalogo.DatoInvalidoError as error:
        db.rollback()
        datos = {
            "codigo": codigo,
            "descripcion": descripcion,
            "unidad_id": unidad_id,
            "precio": precio,
        }
        return _formulario_nuevo(request, db, str(error), datos, status_code=422)
    return RedirectResponse(f"/productos/{producto.id}", status_code=303)


@router.get("/{producto_id}")
def detalle(request: Request, db: DbSession, producto_id: int):
    producto = _obtener(db, producto_id)
    return templates.TemplateResponse(
        request, "productos/detalle.html", _contexto_precios(db, producto)
    )


@router.post("/{producto_id}/precios")
def agregar_precio(
    request: Request,
    db: DbSession,
    producto_id: int,
    precio: Annotated[str, Form()] = "",
    vigente_desde: Annotated[str, Form()] = "",
):
    producto = _obtener(db, producto_id)
    error = None
    try:
        valor = leer_decimal(precio)
        if valor is None:
            raise catalogo.DatoInvalidoError("Captura el precio")
        catalogo.registrar_precio(db, producto.id, valor, leer_fecha(vigente_desde))
        db.commit()
    except catalogo.DatoInvalidoError as exc:
        db.rollback()
        error = str(exc)
    except IntegrityError:
        db.rollback()
        error = "Ya hay un precio registrado con esa misma fecha de inicio"
    return templates.TemplateResponse(
        request, "productos/_precios.html", _contexto_precios(db, producto, error)
    )