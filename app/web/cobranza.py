from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Request

from app.modelos import MetodoPago
from app.servicios import pagos as servicio
from app.web.deps import DbSession
from app.web.plantillas import templates

router = APIRouter(prefix="/cobranza", tags=["cobranza"])


@router.get("")
def resumen(request: Request, db: DbSession):
    por_cobrar = servicio.cuentas_por_cobrar(db)
    por_pagar = servicio.cuentas_por_pagar(db)
    hoy = date.today()
    contexto = {
        "por_cobrar": por_cobrar,
        "por_pagar": por_pagar,
        "total_por_cobrar": sum((p.saldo for p in por_cobrar), Decimal("0.00")),
        "total_por_pagar": sum((o.saldo for o in por_pagar), Decimal("0.00")),
        "tramos": servicio.antiguedad_saldos(db, hoy),
        "hoy": hoy,
        "metodos": list(MetodoPago),
    }
    return templates.TemplateResponse(request, "cobranza/resumen.html", contexto)