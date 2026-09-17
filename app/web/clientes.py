from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.modelos import Cliente
from app.servicios import clientes as servicio
from app.servicios.errores import DatoInvalidoError
from app.web.deps import DbSession
from app.web.formularios import leer_entero
from app.web.plantillas import es_htmx, templates

router = APIRouter(prefix="/clientes", tags=["clientes"])


def campos_cliente(
    nombre_negocio: Annotated[str, Form()] = "",
    nombre_contacto: Annotated[str, Form()] = "",
    telefono: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    direccion: Annotated[str, Form()] = "",
    dias_credito: Annotated[str, Form()] = "0",
) -> dict[str, str]:
    return {
        "nombre_negocio": nombre_negocio,
        "nombre_contacto": nombre_contacto,
        "telefono": telefono,
        "email": email,
        "direccion": direccion,
        "dias_credito": dias_credito,
    }


CamposCliente = Annotated[dict[str, str], Depends(campos_cliente)]


def _a_datos(campos: dict[str, str]) -> servicio.DatosCliente:
    dias = leer_entero(campos["dias_credito"], "Los días de crédito") or 0
    return servicio.DatosCliente(**{**campos, "dias_credito": dias})


def _obtener(db: Session, cliente_id: int) -> Cliente:
    cliente = db.get(Cliente, cliente_id)
    if cliente is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return cliente


def _fragmento_datos(request, cliente, datos=None, mensaje=None, error=None):
    contexto = {"cliente": cliente, "datos": datos or cliente, "mensaje": mensaje, "error": error}
    return templates.TemplateResponse(request, "clientes/_datos.html", contexto)


def _fragmento_direcciones(request, db, cliente, error=None):
    contexto = {
        "cliente": cliente,
        "direcciones": servicio.direcciones_activas(db, cliente.id),
        "error": error,
    }
    return templates.TemplateResponse(request, "clientes/_direcciones.html", contexto)


@router.get("")
def lista(request: Request, db: DbSession, q: str = ""):
    contexto = {"clientes": servicio.listar_clientes(db, q), "q": q}
    plantilla = "clientes/_filas.html" if es_htmx(request) else "clientes/lista.html"
    return templates.TemplateResponse(request, plantilla, contexto)


@router.get("/nuevo")
def nuevo(request: Request):
    return templates.TemplateResponse(request, "clientes/nuevo.html", {"datos": {}})


@router.post("/nuevo")
def crear(request: Request, db: DbSession, campos: CamposCliente):
    try:
        cliente = servicio.crear_cliente(db, _a_datos(campos))
        db.commit()
    except DatoInvalidoError as error:
        db.rollback()
        contexto = {"datos": campos, "error": str(error)}
        return templates.TemplateResponse(
            request, "clientes/nuevo.html", contexto, status_code=422
        )
    return RedirectResponse(f"/clientes/{cliente.id}", status_code=303)


@router.get("/{cliente_id}")
def detalle(request: Request, db: DbSession, cliente_id: int):
    cliente = _obtener(db, cliente_id)
    contexto = {
        "cliente": cliente,
        "datos": cliente,
        "direcciones": servicio.direcciones_activas(db, cliente.id),
    }
    return templates.TemplateResponse(request, "clientes/detalle.html", contexto)


@router.post("/{cliente_id}")
def guardar(request: Request, db: DbSession, cliente_id: int, campos: CamposCliente):
    cliente = _obtener(db, cliente_id)
    try:
        servicio.actualizar_cliente(db, cliente.id, _a_datos(campos))
        db.commit()
    except DatoInvalidoError as error:
        db.rollback()
        return _fragmento_datos(request, cliente, datos=campos, error=str(error))
    return _fragmento_datos(request, cliente, mensaje="Cambios guardados")


@router.post("/{cliente_id}/direcciones")
def agregar_direccion(
    request: Request,
    db: DbSession,
    cliente_id: int,
    alias: Annotated[str, Form()] = "",
    direccion: Annotated[str, Form()] = "",
    referencia: Annotated[str, Form()] = "",
):
    cliente = _obtener(db, cliente_id)
    error = None
    try:
        servicio.agregar_direccion(db, cliente.id, alias, direccion, referencia)
        db.commit()
    except DatoInvalidoError as exc:
        db.rollback()
        error = str(exc)
    return _fragmento_direcciones(request, db, cliente, error)


@router.post("/{cliente_id}/direcciones/{direccion_id}/desactivar")
def desactivar_direccion(request: Request, db: DbSession, cliente_id: int, direccion_id: int):
    cliente = _obtener(db, cliente_id)
    error = None
    try:
        servicio.desactivar_direccion(db, cliente.id, direccion_id)
        db.commit()
    except DatoInvalidoError as exc:
        db.rollback()
        error = str(exc)
    return _fragmento_direcciones(request, db, cliente, error)