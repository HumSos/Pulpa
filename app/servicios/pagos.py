from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.modelos import (
    Cliente,
    CobroCliente,
    EstadoCompra,
    EstadoPedido,
    MetodoPago,
    OrdenCompra,
    PagoProveedor,
    PedidoCliente,
    Proveedor,
)
from app.servicios.errores import DatoInvalidoError

CENTAVOS = Decimal("0.01")


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


def _metodo(valor: str | MetodoPago) -> MetodoPago:
    try:
        return MetodoPago(valor)
    except ValueError as exc:
        raise DatoInvalidoError("El método de pago no es válido") from exc


# ---------- Cobros a clientes ----------

def registrar_cobro(
    db: Session,
    pedido_id: int,
    monto,
    *,
    fecha: date | None = None,
    metodo: str | MetodoPago = MetodoPago.EFECTIVO,
    referencia: str | None = None,
    notas: str | None = None,
) -> CobroCliente:
    pedido = db.get(PedidoCliente, pedido_id)
    if pedido is None:
        raise DatoInvalidoError(f"No existe el pedido {pedido_id}")
    if pedido.estado == EstadoPedido.CANCELADO:
        raise DatoInvalidoError("El pedido está cancelado")
    if pedido.estado == EstadoPedido.BORRADOR:
        raise DatoInvalidoError("Confirma el pedido antes de registrar cobros")

    cantidad = _monto(monto)
    if cantidad > pedido.saldo:
        raise DatoInvalidoError(
            f"El cobro excede el saldo pendiente de {pedido.saldo:.2f}"
        )

    fecha = fecha or date.today()
    if fecha < pedido.fecha_pedido.date():
        raise DatoInvalidoError("El cobro no puede ser anterior al pedido")

    cobro = CobroCliente(
        fecha=fecha,
        monto=cantidad,
        metodo=_metodo(metodo),
        referencia=(referencia or "").strip() or None,
        notas=(notas or "").strip() or None,
    )
    pedido.cobros.append(cobro)
    db.flush()
    return cobro


def eliminar_cobro(db: Session, pedido_id: int, cobro_id: int) -> None:
    cobro = db.get(CobroCliente, cobro_id)
    if cobro is None or cobro.pedido_id != pedido_id:
        raise DatoInvalidoError("Ese cobro no pertenece a este pedido")
    cobro.pedido.cobros.remove(cobro)
    db.flush()


def cuentas_por_cobrar(db: Session, al: date | None = None) -> list[PedidoCliente]:
    al = al or date.today()
    pedidos = db.scalars(
        select(PedidoCliente)
        .options(
            selectinload(PedidoCliente.lineas),
            selectinload(PedidoCliente.cobros),
            selectinload(PedidoCliente.cliente),
        )
        .where(
            PedidoCliente.estado.in_([EstadoPedido.CONFIRMADO, EstadoPedido.ENTREGADO])
        )
        .order_by(PedidoCliente.fecha_pedido)
    )
    return [pedido for pedido in pedidos if pedido.saldo > 0]


# ---------- Pagos a proveedores ----------

def registrar_pago(
    db: Session,
    orden_id: int,
    monto,
    *,
    fecha: date | None = None,
    metodo: str | MetodoPago = MetodoPago.TRANSFERENCIA,
    referencia: str | None = None,
    notas: str | None = None,
) -> PagoProveedor:
    orden = db.get(OrdenCompra, orden_id)
    if orden is None:
        raise DatoInvalidoError(f"No existe la orden {orden_id}")
    if orden.estado == EstadoCompra.CANCELADA:
        raise DatoInvalidoError("La orden está cancelada")
    if orden.estado == EstadoCompra.BORRADOR:
        raise DatoInvalidoError("Envía la orden antes de registrar pagos")

    cantidad = _monto(monto)
    if cantidad > orden.saldo:
        raise DatoInvalidoError(f"El pago excede el saldo pendiente de {orden.saldo:.2f}")

    fecha = fecha or date.today()
    if fecha < orden.fecha.date():
        raise DatoInvalidoError("El pago no puede ser anterior a la orden")

    pago = PagoProveedor(
        fecha=fecha,
        monto=cantidad,
        metodo=_metodo(metodo),
        referencia=(referencia or "").strip() or None,
        notas=(notas or "").strip() or None,
    )
    orden.pagos.append(pago)
    db.flush()
    return pago


def eliminar_pago(db: Session, orden_id: int, pago_id: int) -> None:
    pago = db.get(PagoProveedor, pago_id)
    if pago is None or pago.orden_id != orden_id:
        raise DatoInvalidoError("Ese pago no pertenece a esta orden")
    pago.orden.pagos.remove(pago)
    db.flush()


def cuentas_por_pagar(db: Session) -> list[OrdenCompra]:
    ordenes = db.scalars(
        select(OrdenCompra)
        .options(
            selectinload(OrdenCompra.lineas),
            selectinload(OrdenCompra.pagos),
            selectinload(OrdenCompra.proveedor),
        )
        .where(OrdenCompra.estado.in_([EstadoCompra.ENVIADA, EstadoCompra.RECIBIDA]))
        .order_by(OrdenCompra.fecha)
    )
    return [orden for orden in ordenes if orden.saldo > 0]


# ---------- Estados de cuenta ----------

def estado_cuenta_cliente(db: Session, cliente_id: int) -> dict:
    cliente = db.get(Cliente, cliente_id)
    if cliente is None:
        raise DatoInvalidoError(f"No existe el cliente {cliente_id}")
    pendientes = [p for p in cuentas_por_cobrar(db) if p.cliente_id == cliente_id]
    return {
        "cliente": cliente,
        "pedidos": pendientes,
        "saldo": sum((p.saldo for p in pendientes), Decimal("0.00")),
    }


def estado_cuenta_proveedor(db: Session, proveedor_id: int) -> dict:
    proveedor = db.get(Proveedor, proveedor_id)
    if proveedor is None:
        raise DatoInvalidoError(f"No existe el proveedor {proveedor_id}")
    pendientes = [o for o in cuentas_por_pagar(db) if o.proveedor_id == proveedor_id]
    return {
        "proveedor": proveedor,
        "ordenes": pendientes,
        "saldo": sum((o.saldo for o in pendientes), Decimal("0.00")),
    }


def antiguedad_saldos(db: Session, al: date | None = None) -> dict[str, Decimal]:
    """Cuánto se debe por rango de días vencidos."""
    al = al or date.today()
    tramos = {"Por vencer": Decimal("0.00"), "1-30": Decimal("0.00"),
              "31-60": Decimal("0.00"), "Más de 60": Decimal("0.00")}
    for pedido in cuentas_por_cobrar(db, al):
        dias = (al - pedido.fecha_vencimiento).days
        if dias <= 0:
            tramo = "Por vencer"
        elif dias <= 30:
            tramo = "1-30"
        elif dias <= 60:
            tramo = "31-60"
        else:
            tramo = "Más de 60"
        tramos[tramo] += pedido.saldo
    return tramos