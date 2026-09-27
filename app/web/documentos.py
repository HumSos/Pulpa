from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response

from app.config import settings
from app.modelos import OrdenCompra, PedidoCliente
from app.servicios import exportar
from app.servicios import pagos as servicio_pagos
from app.servicios.errores import DatoInvalidoError
from app.web.deps import DbSession
from app.web.plantillas import templates

router = APIRouter(tags=["documentos"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _empresa() -> dict:
    return {
        "nombre": settings.empresa_nombre,
        "direccion": settings.empresa_direccion,
        "telefono": settings.empresa_telefono,
        "rfc": settings.empresa_rfc,
    }


def _archivo(contenido: bytes, nombre: str) -> Response:
    disposicion = f"attachment; filename*=UTF-8''{quote(nombre)}"
    return Response(contenido, media_type=XLSX, headers={"Content-Disposition": disposicion})


@router.get("/pedidos/{pedido_id}/nota")
def nota_de_entrega(request: Request, db: DbSession, pedido_id: int):
    pedido = db.get(PedidoCliente, pedido_id)
    if pedido is None:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    contexto = {"pedido": pedido, "empresa": _empresa(), "hoy": date.today()}
    return templates.TemplateResponse(request, "documentos/nota.html", contexto)


@router.get("/compras/{orden_id}/orden")
def orden_impresa(request: Request, db: DbSession, orden_id: int):
    orden = db.get(OrdenCompra, orden_id)
    if orden is None:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    contexto = {"orden": orden, "empresa": _empresa(), "hoy": date.today()}
    return templates.TemplateResponse(request, "documentos/orden.html", contexto)


@router.get("/clientes/{cliente_id}/estado-cuenta")
def estado_cuenta_cliente(request: Request, db: DbSession, cliente_id: int):
    try:
        datos = servicio_pagos.estado_cuenta_cliente(db, cliente_id)
    except DatoInvalidoError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    contexto = {**datos, "empresa": _empresa(), "hoy": date.today()}
    return templates.TemplateResponse(request, "documentos/estado_cliente.html", contexto)


@router.get("/proveedores/{proveedor_id}/estado-cuenta")
def estado_cuenta_proveedor(request: Request, db: DbSession, proveedor_id: int):
    try:
        datos = servicio_pagos.estado_cuenta_proveedor(db, proveedor_id)
    except DatoInvalidoError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    contexto = {**datos, "empresa": _empresa(), "hoy": date.today()}
    return templates.TemplateResponse(request, "documentos/estado_proveedor.html", contexto)


@router.get("/cobranza/por-cobrar.xlsx")
def excel_por_cobrar(db: DbSession):
    hoy = date.today()
    contenido = exportar.cuentas_por_cobrar(servicio_pagos.pedidos_pendientes(db), hoy)
    return _archivo(contenido, f"por_cobrar_{hoy:%Y%m%d}.xlsx")


@router.get("/cobranza/por-pagar.xlsx")
def excel_por_pagar(db: DbSession):
    hoy = date.today()
    contenido = exportar.cuentas_por_pagar(servicio_pagos.ordenes_pendientes(db), hoy)
    return _archivo(contenido, f"por_pagar_{hoy:%Y%m%d}.xlsx")


@router.get("/pedidos.xlsx")
def excel_ventas(db: DbSession, q: str = "", estado: str = ""):
    from app.servicios import pedidos as servicio_pedidos

    pedidos = servicio_pedidos.listar_pedidos(db, q, estado, limite=5000)
    return _archivo(exportar.ventas_detalladas(pedidos), f"ventas_{date.today():%Y%m%d}.xlsx")