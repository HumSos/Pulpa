from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.modelos import EstadoCompra, MetodoPago, OrdenCompra
from app.servicios import (
    compras as servicio,
)
from app.servicios import (
    pagos as servicio_pagos,
)
from app.servicios import (
    proveedores as servicio_proveedores,
)
from app.servicios.catalogo import costo_vigente
from app.servicios.errores import DatoInvalidoError, PrecioNoDefinidoError
from app.web.deps import DbSession
from app.web.formularios import leer_decimal, leer_entero
from app.web.plantillas import es_htmx, templates

router = APIRouter(prefix="/compras", tags=["compras"])


def _obtener(db: Session, orden_id: int) -> OrdenCompra:
    orden = db.get(OrdenCompra, orden_id)
    if orden is None:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    return orden


def _costos(db: Session, suministros) -> dict[int, str]:
    resultado = {}
    for suministro in suministros:
        try:
            resultado[suministro.producto_id] = str(costo_vigente(db, suministro.id))
        except PrecioNoDefinidoError:
            continue
    return resultado


def _contexto(db: Session, orden: OrdenCompra, error: str | None = None) -> dict:
    editable = orden.estado == EstadoCompra.BORRADOR
    suministros = servicio.productos_del_proveedor(db, orden.proveedor_id) if editable else []
    return {
        "orden": orden,
        "editable": editable,
        "suministros": suministros,
        "costos": _costos(db, suministros),
        "hoy": date.today().isoformat(),
        "pagable": orden.estado in (EstadoCompra.ENVIADA, EstadoCompra.RECIBIDA),
        "metodos": list(MetodoPago),
        "error": error,
    }


def _fragmento(request, db, orden, error=None):
    return templates.TemplateResponse(
        request, "compras/_detalle.html", _contexto(db, orden, error)
    )


@router.get("")
def lista(request: Request, db: DbSession, q: str = "", estado: str = ""):
    contexto = {
        "ordenes": servicio.listar_ordenes(db, q, estado),
        "q": q,
        "estado": estado,
        "estados": list(EstadoCompra),
    }
    plantilla = "compras/_filas.html" if es_htmx(request) else "compras/lista.html"
    return templates.TemplateResponse(request, plantilla, contexto)


@router.get("/nueva")
def nueva(request: Request, db: DbSession):
    contexto = {"proveedores": servicio_proveedores.listar_proveedores(db), "datos": {}}
    return templates.TemplateResponse(request, "compras/nueva.html", contexto)


@router.post("/nueva")
def crear(
    request: Request,
    db: DbSession,
    proveedor_id: Annotated[str, Form()] = "",
    numero_remision: Annotated[str, Form()] = "",
    notas: Annotated[str, Form()] = "",
):
    try:
        identificador = leer_entero(proveedor_id, "El proveedor")
        if identificador is None:
            raise DatoInvalidoError("Selecciona un proveedor")
        orden = servicio.crear_orden(
            db, identificador, numero_remision=numero_remision, notas=notas
        )
        db.commit()
    except DatoInvalidoError as error:
        db.rollback()
        contexto = {
            "proveedores": servicio_proveedores.listar_proveedores(db),
            "datos": {"proveedor_id": proveedor_id, "numero_remision": numero_remision},
            "error": str(error),
        }
        return templates.TemplateResponse(
            request, "compras/nueva.html", contexto, status_code=422
        )
    return RedirectResponse(f"/compras/{orden.id}", status_code=303)


@router.get("/{orden_id}")
def detalle(request: Request, db: DbSession, orden_id: int):
    orden = _obtener(db, orden_id)
    return templates.TemplateResponse(request, "compras/detalle.html", _contexto(db, orden))


@router.post("/{orden_id}/lineas")
def agregar_linea(
    request: Request,
    db: DbSession,
    orden_id: int,
    producto_id: Annotated[str, Form()] = "",
    cantidad: Annotated[str, Form()] = "",
    costo_unitario: Annotated[str, Form()] = "",
):
    orden = _obtener(db, orden_id)
    try:
        producto = leer_entero(producto_id, "El producto")
        cantidad_decimal = leer_decimal(cantidad)
        if producto is None or cantidad_decimal is None:
            raise DatoInvalidoError("Selecciona un producto y captura la cantidad")
        servicio.agregar_linea(
            db,
            orden.id,
            servicio.LineaCompra(producto, cantidad_decimal, leer_decimal(costo_unitario)),
        )
        db.commit()
    except DatoInvalidoError as error:
        db.rollback()
        return _fragmento(request, db, orden, str(error))
    return _fragmento(request, db, orden)


@router.post("/{orden_id}/lineas/{linea_id}/quitar")
def quitar_linea(request: Request, db: DbSession, orden_id: int, linea_id: int):
    orden = _obtener(db, orden_id)
    try:
        servicio.quitar_linea(db, orden.id, linea_id)
        db.commit()
    except DatoInvalidoError as error:
        db.rollback()
        return _fragmento(request, db, orden, str(error))
    return _fragmento(request, db, orden)


@router.post("/{orden_id}/estado")
def cambiar_estado(
    request: Request, db: DbSession, orden_id: int, estado: Annotated[str, Form()]
):
    orden = _obtener(db, orden_id)
    try:
        servicio.cambiar_estado(db, orden.id, estado)
        db.commit()
    except (DatoInvalidoError, ValueError) as error:
        db.rollback()
        return _fragmento(request, db, orden, str(error))
    return _fragmento(request, db, orden)


@router.post("/{orden_id}/recibir")
def recibir(
    request: Request,
    db: DbSession,
    orden_id: int,
    numero_remision: Annotated[str, Form()] = "",
    fecha_recepcion: Annotated[str, Form()] = "",
):
    orden = _obtener(db, orden_id)
    try:
        servicio.recibir(
            db,
            orden.id,
            date.fromisoformat(fecha_recepcion) if fecha_recepcion else None,
            numero_remision,
        )
        db.commit()
    except (DatoInvalidoError, ValueError) as error:
        db.rollback()
        return _fragmento(request, db, orden, str(error))
    return _fragmento(request, db, orden)

@router.post("/{orden_id}/pagos")
def registrar_pago(
    request: Request,
    db: DbSession,
    orden_id: int,
    monto: Annotated[str, Form()] = "",
    fecha: Annotated[str, Form()] = "",
    metodo: Annotated[str, Form()] = "transferencia",
    referencia: Annotated[str, Form()] = "",
):
    orden = _obtener(db, orden_id)
    try:
        cantidad = leer_decimal(monto)
        if cantidad is None:
            raise DatoInvalidoError("Captura el monto del pago")
        servicio_pagos.registrar_pago(
            db,
            orden.id,
            cantidad,
            fecha=date.fromisoformat(fecha) if fecha else None,
            metodo=metodo,
            referencia=referencia,
        )
        db.commit()
    except (DatoInvalidoError, ValueError) as error:
        db.rollback()
        return _fragmento(request, db, orden, str(error))
    return _fragmento(request, db, orden)


@router.post("/{orden_id}/pagos/{pago_id}/eliminar")
def eliminar_pago(request: Request, db: DbSession, orden_id: int, pago_id: int):
    orden = _obtener(db, orden_id)
    try:
        servicio_pagos.eliminar_pago(db, orden.id, pago_id)
        db.commit()
    except DatoInvalidoError as error:
        db.rollback()
        return _fragmento(request, db, orden, str(error))
    return _fragmento(request, db, orden)