from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from sqlalchemy.orm import Session

from app.modelos import MetodoPago, Pago, TipoMovimiento
from app.servicios import clientes as servicio_clientes
from app.servicios import pagos as servicio
from app.servicios import proveedores as servicio_proveedores
from app.servicios.errores import DatoInvalidoError
from app.web.deps import DbSession
from app.web.formularios import leer_decimal, leer_entero
from app.web.plantillas import es_htmx, templates

router = APIRouter(prefix="/cobranza", tags=["cobranza"])

CERO = Decimal("0.00")


def _obtener(db: Session, pago_id: int) -> Pago:
    pago = db.get(Pago, pago_id)
    if pago is None:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")
    return pago


def _resumen(db: Session) -> dict:
    por_cobrar = servicio.pedidos_pendientes(db)
    por_pagar = servicio.ordenes_pendientes(db)
    hoy = date.today()
    return {
        "por_cobrar": por_cobrar,
        "por_pagar": por_pagar,
        "total_por_cobrar": sum((p.saldo for p in por_cobrar), CERO),
        "total_por_pagar": sum((o.saldo for o in por_pagar), CERO),
        "tramos": servicio.antiguedad_saldos(db, hoy),
        "movimientos": servicio.movimientos(db, limite=25),
        "hoy": hoy,
    }


def _formulario(db: Session, tipo: str, contraparte_id: int | None) -> dict:
    es_cobro = tipo != "pago"
    documentos = []
    if contraparte_id is not None:
        documentos = (
            servicio.pedidos_pendientes(db, contraparte_id)
            if es_cobro
            else servicio.ordenes_pendientes(db, contraparte_id)
        )
    return {
        "tipo": "cobro" if es_cobro else "pago",
        "es_cobro": es_cobro,
        "contraparte_id": contraparte_id,
        "contrapartes": (
            servicio_clientes.listar_clientes(db)
            if es_cobro
            else servicio_proveedores.listar_proveedores(db)
        ),
        "documentos": documentos,
        "pendiente": sum((d.saldo for d in documentos), CERO),
        "metodos": list(MetodoPago),
        "hoy": date.today().isoformat(),
    }


@router.get("")
def resumen(request: Request, db: DbSession):
    return templates.TemplateResponse(request, "cobranza/resumen.html", _resumen(db))


@router.get("/nuevo")
def nuevo(request: Request, db: DbSession, tipo: str = "cobro", contraparte_id: str = ""):
    contexto = _formulario(db, tipo, leer_entero(contraparte_id, "La contraparte"))
    plantilla = "cobranza/_documentos.html" if es_htmx(request) else "cobranza/nuevo.html"
    return templates.TemplateResponse(request, plantilla, contexto)


@router.post("/nuevo")
async def crear(
    request: Request,
    db: DbSession,
    tipo: Annotated[str, Form()] = "cobro",
    contraparte_id: Annotated[str, Form()] = "",
    monto: Annotated[str, Form()] = "",
    fecha: Annotated[str, Form()] = "",
    metodo: Annotated[str, Form()] = "efectivo",
    referencia: Annotated[str, Form()] = "",
    notas: Annotated[str, Form()] = "",
):
    formulario = await request.form()
    identificador = leer_entero(contraparte_id, "La contraparte")
    contexto = _formulario(db, tipo, identificador)
    try:
        cantidad = leer_decimal(monto)
        if identificador is None or cantidad is None:
            raise DatoInvalidoError("Selecciona la contraparte y captura el monto")

        reparto = []
        for documento in contexto["documentos"]:
            abono = leer_decimal(formulario.get(f"abono_{documento.id}", ""))
            if abono:
                reparto.append((documento.id, abono))
        if reparto and sum(abono for _, abono in reparto) > cantidad:
            raise DatoInvalidoError("La suma de los abonos excede el monto del pago")

        registrar = (
            servicio.registrar_cobro if tipo != "pago" else servicio.registrar_pago
        )
        registrar(
            db,
            identificador,
            cantidad,
            fecha=date.fromisoformat(fecha) if fecha else None,
            metodo=metodo,
            referencia=referencia,
            notas=notas,
            reparto=reparto or None,
        )
        db.commit()
    except (DatoInvalidoError, ValueError) as error:
        db.rollback()
        contexto["error"] = str(error)
        contexto["datos"] = {"monto": monto, "referencia": referencia, "fecha": fecha}
        return templates.TemplateResponse(
            request, "cobranza/nuevo.html", contexto, status_code=422
        )
    return templates.TemplateResponse(request, "cobranza/_resumen.html", _resumen(db))


@router.post("/{pago_id}/aplicar")
def aplicar(
    request: Request,
    db: DbSession,
    pago_id: int,
    documento_id: Annotated[str, Form()] = "",
    monto: Annotated[str, Form()] = "",
):
    pago = _obtener(db, pago_id)
    contexto = {}
    try:
        documento = leer_entero(documento_id, "El documento")
        cantidad = leer_decimal(monto)
        if documento is None or cantidad is None:
            raise DatoInvalidoError("Selecciona el documento y captura el abono")
        servicio.aplicar(db, pago.id, documento, cantidad)
        db.commit()
    except DatoInvalidoError as error:
        db.rollback()
        contexto["error"] = str(error)
    return templates.TemplateResponse(
        request, "cobranza/_resumen.html", {**_resumen(db), **contexto}
    )


@router.post("/aplicaciones/{aplicacion_id}/quitar")
def quitar(request: Request, db: DbSession, aplicacion_id: int):
    contexto = {}
    try:
        servicio.quitar_aplicacion(db, aplicacion_id)
        db.commit()
    except DatoInvalidoError as error:
        db.rollback()
        contexto["error"] = str(error)
    return templates.TemplateResponse(
        request, "cobranza/_resumen.html", {**_resumen(db), **contexto}
    )


@router.post("/{pago_id}/eliminar")
def eliminar(request: Request, db: DbSession, pago_id: int):
    pago = _obtener(db, pago_id)
    contexto = {}
    try:
        servicio.eliminar_pago(db, pago.id)
        db.commit()
    except DatoInvalidoError as error:
        db.rollback()
        contexto["error"] = str(error)
    return templates.TemplateResponse(
        request, "cobranza/_resumen.html", {**_resumen(db), **contexto}
    )


@router.get("/saldos-a-favor")
def saldos_a_favor(request: Request, db: DbSession):
    pagos = [
        p
        for p in servicio.movimientos(db, tipo=TipoMovimiento.COBRO, limite=200)
        if p.disponible > 0
    ]
    contexto = {
        "pagos": pagos,
        "pendientes": {
            p.id: servicio.pedidos_pendientes(db, p.cliente_id) for p in pagos
        },
    }
    return templates.TemplateResponse(request, "cobranza/saldos.html", contexto)