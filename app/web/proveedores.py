from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.modelos import Proveedor, ProveedorProducto
from app.servicios import catalogo
from app.servicios import proveedores as servicio
from app.servicios.errores import DatoInvalidoError
from app.web.deps import DbSession
from app.web.formularios import leer_decimal, leer_entero
from app.web.plantillas import es_htmx, templates

router = APIRouter(prefix="/proveedores", tags=["proveedores"])


def campos_proveedor(
    nombre: Annotated[str, Form()] = "",
    contacto: Annotated[str, Form()] = "",
    telefono: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    dias_credito: Annotated[str, Form()] = "0",
) -> dict[str, str]:
    return {
        "nombre": nombre,
        "contacto": contacto,
        "telefono": telefono,
        "email": email,
        "dias_credito": dias_credito,
    }


CamposProveedor = Annotated[dict[str, str], Depends(campos_proveedor)]


def _a_datos(campos: dict[str, str]) -> servicio.DatosProveedor:
    dias = leer_entero(campos["dias_credito"], "Los días de crédito") or 0
    return servicio.DatosProveedor(**{**campos, "dias_credito": dias})


def _obtener(db: Session, proveedor_id: int) -> Proveedor:
    proveedor = db.get(Proveedor, proveedor_id)
    if proveedor is None:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    return proveedor


def _fragmento_datos(request, proveedor, datos=None, mensaje=None, error=None):
    contexto = {
        "proveedor": proveedor,
        "datos": datos or proveedor,
        "mensaje": mensaje,
        "error": error,
    }
    return templates.TemplateResponse(request, "proveedores/_datos.html", contexto)


def _fragmento_suministros(request, db, proveedor, error=None):
    suministros = servicio.listar_suministros(db, proveedor.id)
    contexto = {
        "proveedor": proveedor,
        "suministros": suministros,
        "costos": servicio.costos_vigentes(db, suministros),
        "productos": catalogo.listar_productos(db),
        "unidades": catalogo.listar_unidades(db),
        "error": error,
    }
    return templates.TemplateResponse(request, "proveedores/_suministros.html", contexto)


@router.get("")
def lista(request: Request, db: DbSession, q: str = ""):
    contexto = {"proveedores": servicio.listar_proveedores(db, q), "q": q}
    plantilla = "proveedores/_filas.html" if es_htmx(request) else "proveedores/lista.html"
    return templates.TemplateResponse(request, plantilla, contexto)


@router.get("/nuevo")
def nuevo(request: Request):
    return templates.TemplateResponse(request, "proveedores/nuevo.html", {"datos": {}})


@router.post("/nuevo")
def crear(request: Request, db: DbSession, campos: CamposProveedor):
    try:
        proveedor = servicio.crear_proveedor(db, _a_datos(campos))
        db.commit()
    except DatoInvalidoError as error:
        db.rollback()
        contexto = {"datos": campos, "error": str(error)}
        return templates.TemplateResponse(
            request, "proveedores/nuevo.html", contexto, status_code=422
        )
    return RedirectResponse(f"/proveedores/{proveedor.id}", status_code=303)


@router.get("/{proveedor_id}")
def detalle(request: Request, db: DbSession, proveedor_id: int):
    proveedor = _obtener(db, proveedor_id)
    suministros = servicio.listar_suministros(db, proveedor.id)
    contexto = {
        "proveedor": proveedor,
        "datos": proveedor,
        "suministros": suministros,
        "costos": servicio.costos_vigentes(db, suministros),
        "productos": catalogo.listar_productos(db),
        "unidades": catalogo.listar_unidades(db),
    }
    return templates.TemplateResponse(request, "proveedores/detalle.html", contexto)


@router.post("/{proveedor_id}")
def guardar(request: Request, db: DbSession, proveedor_id: int, campos: CamposProveedor):
    proveedor = _obtener(db, proveedor_id)
    try:
        servicio.actualizar_proveedor(db, proveedor.id, _a_datos(campos))
        db.commit()
    except DatoInvalidoError as error:
        db.rollback()
        return _fragmento_datos(request, proveedor, datos=campos, error=str(error))
    return _fragmento_datos(request, proveedor, mensaje="Cambios guardados")


@router.post("/{proveedor_id}/suministros")
def agregar_suministro(
    request: Request,
    db: DbSession,
    proveedor_id: int,
    producto_id: Annotated[str, Form()] = "",
    unidad_compra_id: Annotated[str, Form()] = "",
    factor_conversion: Annotated[str, Form()] = "",
    costo: Annotated[str, Form()] = "",
):
    proveedor = _obtener(db, proveedor_id)
    error = None
    try:
        producto = leer_entero(producto_id, "El producto")
        unidad = leer_entero(unidad_compra_id, "La unidad de compra")
        factor = leer_decimal(factor_conversion)
        if producto is None or unidad is None or factor is None:
            raise DatoInvalidoError("Completa producto, unidad de compra y factor")
        servicio.agregar_suministro(
            db, proveedor.id, producto, unidad, factor, leer_decimal(costo)
        )
        db.commit()
    except DatoInvalidoError as exc:
        db.rollback()
        error = str(exc)
    return _fragmento_suministros(request, db, proveedor, error)


@router.post("/{proveedor_id}/suministros/{suministro_id}/costo")
def actualizar_costo(
    request: Request,
    db: DbSession,
    proveedor_id: int,
    suministro_id: int,
    costo: Annotated[str, Form()] = "",
):
    proveedor = _obtener(db, proveedor_id)
    error = None
    try:
        monto = leer_decimal(costo)
        if monto is None:
            raise DatoInvalidoError("Captura el costo")
        suministro = db.get(ProveedorProducto, suministro_id)
        if suministro is None or suministro.proveedor_id != proveedor.id:
            raise DatoInvalidoError("Ese producto no pertenece a este proveedor")
        catalogo.registrar_costo(db, suministro_id, monto)
        db.commit()
    except DatoInvalidoError as exc:
        db.rollback()
        error = str(exc)
    return _fragmento_suministros(request, db, proveedor, error)


@router.post("/{proveedor_id}/suministros/{suministro_id}/quitar")
def quitar_suministro(request: Request, db: DbSession, proveedor_id: int, suministro_id: int):
    proveedor = _obtener(db, proveedor_id)
    error = None
    try:
        servicio.quitar_suministro(db, proveedor.id, suministro_id)
        db.commit()
    except DatoInvalidoError as exc:
        db.rollback()
        error = str(exc)
    return _fragmento_suministros(request, db, proveedor, error)


@router.post("/{proveedor_id}/suministros/{suministro_id}/preferido")
def marcar_preferido(request: Request, db: DbSession, proveedor_id: int, suministro_id: int):
    proveedor = _obtener(db, proveedor_id)
    error = None
    try:
        suministro = db.get(ProveedorProducto, suministro_id)
        if suministro is None or suministro.proveedor_id != proveedor.id:
            raise DatoInvalidoError("Ese producto no pertenece a este proveedor")
        catalogo.marcar_preferido(db, suministro_id)
        db.commit()
    except DatoInvalidoError as exc:
        db.rollback()
        error = str(exc)
    return _fragmento_suministros(request, db, proveedor, error)