from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.modelos import EstadoPedido, PedidoCliente
from app.servicios import catalogo
from app.servicios import clientes as servicio_clientes
from app.servicios import pedidos as servicio
from app.servicios.errores import DatoInvalidoError
from app.web.deps import DbSession
from app.web.formularios import leer_decimal, leer_entero
from app.web.plantillas import es_htmx, templates

router = APIRouter(prefix="/pedidos", tags=["pedidos"])


def _obtener(db: Session, pedido_id: int) -> PedidoCliente:
    pedido = db.get(PedidoCliente, pedido_id)
    if pedido is None:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    return pedido


def _contexto(db: Session, pedido: PedidoCliente, error: str | None = None) -> dict:
    editable = pedido.estado == EstadoPedido.BORRADOR
    return {
        "pedido": pedido,
        "editable": editable,
        "productos": catalogo.listar_productos(db) if editable else [],
        "precios": catalogo.precios_vigentes(
            db, [p.id for p in catalogo.listar_productos(db)], pedido.fecha_pedido
        )
        if editable
        else {},
        "error": error,
    }


def _fragmento(request, db, pedido, error=None, status_code=200):
    return templates.TemplateResponse(
        request, "pedidos/_detalle.html", _contexto(db, pedido, error), status_code=status_code
    )


@router.get("")
def lista(request: Request, db: DbSession, q: str = "", estado: str = ""):
    contexto = {
        "pedidos": servicio.listar_pedidos(db, q, estado),
        "q": q,
        "estado": estado,
        "estados": list(EstadoPedido),
    }
    plantilla = "pedidos/_filas.html" if es_htmx(request) else "pedidos/lista.html"
    return templates.TemplateResponse(request, plantilla, contexto)


@router.get("/nuevo")
def nuevo(request: Request, db: DbSession, cliente_id: int | None = None):
    contexto = {
        "clientes": servicio_clientes.listar_clientes(db),
        "direcciones": servicio_clientes.direcciones_activas(db, cliente_id)
        if cliente_id
        else [],
        "datos": {"cliente_id": cliente_id, "fecha_entrega": ""},
        "hoy": date.today().isoformat(),
    }
    plantilla = "pedidos/_direcciones.html" if es_htmx(request) else "pedidos/nuevo.html"
    return templates.TemplateResponse(request, plantilla, contexto)


@router.post("/nuevo")
def crear(
    request: Request,
    db: DbSession,
    cliente_id: Annotated[str, Form()] = "",
    direccion_entrega_id: Annotated[str, Form()] = "",
    fecha_entrega: Annotated[str, Form()] = "",
    referencia_cliente: Annotated[str, Form()] = "",
    notas: Annotated[str, Form()] = "",
):
    try:
        identificador = leer_entero(cliente_id, "El cliente")
        if identificador is None:
            raise DatoInvalidoError("Selecciona un cliente")
        pedido = servicio.crear_pedido_vacio(
            db,
            identificador,
            fecha_entrega=date.fromisoformat(fecha_entrega) if fecha_entrega else None,
            direccion_entrega_id=leer_entero(direccion_entrega_id, "La dirección"),
            referencia_cliente=referencia_cliente,
            notas=notas,
        )
        db.commit()
    except (DatoInvalidoError, ValueError) as error:
        db.rollback()
        contexto = {
            "clientes": servicio_clientes.listar_clientes(db),
            "direcciones": [],
            "datos": {"cliente_id": cliente_id, "fecha_entrega": fecha_entrega},
            "hoy": date.today().isoformat(),
            "error": str(error),
        }
        return templates.TemplateResponse(
            request, "pedidos/nuevo.html", contexto, status_code=422
        )
    return RedirectResponse(f"/pedidos/{pedido.id}", status_code=303)


@router.get("/{pedido_id}")
def detalle(request: Request, db: DbSession, pedido_id: int):
    pedido = _obtener(db, pedido_id)
    return templates.TemplateResponse(request, "pedidos/detalle.html", _contexto(db, pedido))


@router.post("/{pedido_id}/lineas")
def agregar_linea(
    request: Request,
    db: DbSession,
    pedido_id: int,
    producto_id: Annotated[str, Form()] = "",
    cantidad: Annotated[str, Form()] = "",
    precio_unitario: Annotated[str, Form()] = "",
):
    pedido = _obtener(db, pedido_id)
    try:
        identificador = leer_entero(producto_id, "El producto")
        cantidad_decimal = leer_decimal(cantidad)
        if identificador is None or cantidad_decimal is None:
            raise DatoInvalidoError("Selecciona un producto y captura la cantidad")
        servicio.agregar_linea(
            db,
            pedido.id,
            servicio.LineaNueva(identificador, cantidad_decimal, leer_decimal(precio_unitario)),
        )
        db.commit()
    except DatoInvalidoError as error:
        db.rollback()
        return _fragmento(request, db, pedido, str(error))
    return _fragmento(request, db, pedido)


@router.post("/{pedido_id}/lineas/{linea_id}/quitar")
def quitar_linea(request: Request, db: DbSession, pedido_id: int, linea_id: int):
    pedido = _obtener(db, pedido_id)
    try:
        servicio.quitar_linea(db, pedido.id, linea_id)
        db.commit()
    except DatoInvalidoError as error:
        db.rollback()
        return _fragmento(request, db, pedido, str(error))
    return _fragmento(request, db, pedido)


@router.post("/{pedido_id}/estado")
def cambiar_estado(
    request: Request, db: DbSession, pedido_id: int, estado: Annotated[str, Form()]
):
    pedido = _obtener(db, pedido_id)
    try:
        if estado == EstadoPedido.CONFIRMADO:
            servicio.confirmar_pedido(db, pedido.id)
        else:
            servicio.cambiar_estado(db, pedido.id, estado)
        db.commit()
    except (DatoInvalidoError, ValueError) as error:
        db.rollback()
        return _fragmento(request, db, pedido, str(error))
    return _fragmento(request, db, pedido)