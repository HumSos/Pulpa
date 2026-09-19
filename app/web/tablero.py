from datetime import date

from fastapi import APIRouter, Request

from app.servicios import kpis
from app.servicios.pagos import antiguedad_saldos, cuentas_por_cobrar, cuentas_por_pagar
from app.web.deps import DbSession
from app.web.plantillas import templates

router = APIRouter(tags=["tablero"])


def _periodo(desde: str, hasta: str) -> kpis.Periodo:
    hoy = date.today()
    try:
        inicio = date.fromisoformat(desde) if desde else hoy.replace(day=1)
        fin = date.fromisoformat(hasta) if hasta else hoy
    except ValueError:
        return kpis.periodo_mes_actual(hoy)
    if fin < inicio:
        inicio, fin = fin, inicio
    return kpis.Periodo(inicio, fin)


@router.get("/")
def tablero(request: Request, db: DbSession, desde: str = "", hasta: str = ""):
    periodo = _periodo(desde, hasta)
    por_cobrar = cuentas_por_cobrar(db)
    por_pagar = cuentas_por_pagar(db)
    datos = kpis.resumen(db, periodo)
    maximo = max((total for _, total in datos["ventas_por_dia"]), default=0)

    tramos = antiguedad_saldos(db)
    contexto = {
        **datos,
        "por_cobrar": sum((p.saldo for p in por_cobrar), kpis.CERO),
        "por_pagar": sum((o.saldo for o in por_pagar), kpis.CERO),
        "vencido": tramos["1-30"] + tramos["31-60"] + tramos["Más de 60"],
        "maximo_dia": maximo,
    }
    return templates.TemplateResponse(request, "tablero.html", contexto)