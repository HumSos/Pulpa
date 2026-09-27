from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.modelos import Gasto, MetodoPago, Proveedor
from app.servicios.errores import DatoInvalidoError

CENTAVOS = Decimal("0.01")
CERO = Decimal("0.00")

SUGERIDAS = ["Gasolina", "Flete", "Mantenimiento", "Renta", "Sueldos", "Servicios", "Otros"]


@dataclass(frozen=True)
class DatosGasto:
    categoria: str
    concepto: str
    monto: Decimal
    fecha: date | None = None
    metodo: str | MetodoPago = MetodoPago.EFECTIVO
    proveedor_id: int | None = None
    referencia: str | None = None
    notas: str | None = None


def _limpio(texto: str | None) -> str | None:
    texto = " ".join((texto or "").split())
    return texto or None


def _monto(valor) -> Decimal:
    try:
        numero = Decimal(str(valor))
    except InvalidOperation as exc:
        raise DatoInvalidoError("El monto no es un número válido") from exc
    if not numero.is_finite():
        raise DatoInvalidoError("El monto no es un número válido")
    numero = numero.quantize(CENTAVOS, rounding=ROUND_HALF_UP)
    if numero <= 0:
        raise DatoInvalidoError("El monto debe ser mayor a cero")
    return numero


def registrar(db: Session, datos: DatosGasto) -> Gasto:
    categoria = _limpio(datos.categoria)
    concepto = _limpio(datos.concepto)
    if categoria is None:
        raise DatoInvalidoError("La categoría es obligatoria")
    if concepto is None:
        raise DatoInvalidoError("El concepto es obligatorio")

    try:
        metodo = MetodoPago(datos.metodo)
    except ValueError as exc:
        raise DatoInvalidoError("El método de pago no es válido") from exc

    if datos.proveedor_id is not None and db.get(Proveedor, datos.proveedor_id) is None:
        raise DatoInvalidoError("El proveedor no existe")

    gasto = Gasto(
        fecha=datos.fecha or date.today(),
        categoria=categoria,
        concepto=concepto,
        monto=_monto(datos.monto),
        metodo=metodo,
        proveedor_id=datos.proveedor_id,
        referencia=_limpio(datos.referencia),
        notas=_limpio(datos.notas),
    )
    db.add(gasto)
    db.flush()
    return gasto


def eliminar(db: Session, gasto_id: int) -> None:
    gasto = db.get(Gasto, gasto_id)
    if gasto is None:
        raise DatoInvalidoError(f"No existe el gasto {gasto_id}")
    db.delete(gasto)
    db.flush()


def listar(db: Session, desde: date, hasta: date, categoria: str = "") -> list[Gasto]:
    consulta = (
        select(Gasto)
        .options(joinedload(Gasto.proveedor))
        .where(Gasto.fecha.between(desde, hasta))
        .order_by(Gasto.fecha.desc(), Gasto.id.desc())
    )
    if categoria.strip():
        consulta = consulta.where(Gasto.categoria == categoria.strip())
    return list(db.scalars(consulta))


def total(db: Session, desde: date, hasta: date) -> Decimal:
    return db.scalar(
        select(func.sum(Gasto.monto)).where(Gasto.fecha.between(desde, hasta))
    ) or CERO


def por_categoria(db: Session, desde: date, hasta: date) -> list[tuple[str, Decimal]]:
    filas = db.execute(
        select(Gasto.categoria, func.sum(Gasto.monto))
        .where(Gasto.fecha.between(desde, hasta))
        .group_by(Gasto.categoria)
        .order_by(func.sum(Gasto.monto).desc())
    )
    return [(categoria, monto) for categoria, monto in filas]


def categorias_usadas(db: Session) -> list[str]:
    usadas = db.scalars(select(Gasto.categoria).distinct())
    return sorted(set(SUGERIDAS) | {c for c in usadas if c})