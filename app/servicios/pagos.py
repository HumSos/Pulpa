from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.modelos import (
    AplicacionPago,
    Cliente,
    EstadoCompra,
    EstadoPedido,
    MetodoPago,
    OrdenCompra,
    Pago,
    PedidoCliente,
    Proveedor,
    TipoMovimiento,
)
from app.servicios.errores import DatoInvalidoError

CENTAVOS = Decimal("0.01")
CERO = Decimal("0.00")
COBRABLES = (EstadoPedido.CONFIRMADO, EstadoPedido.ENTREGADO)
PAGABLES = (EstadoCompra.ENVIADA, EstadoCompra.RECIBIDA)


def _monto(valor, nombre: str = "El monto") -> Decimal:
    try:
        numero = Decimal(str(valor))
    except InvalidOperation as exc:
        raise DatoInvalidoError(f"{nombre} no es un número válido") from exc
    if not numero.is_finite():
        raise DatoInvalidoError(f"{nombre} no es un número válido")
    numero = numero.quantize(CENTAVOS, rounding=ROUND_HALF_UP)
    if numero <= 0:
        raise DatoInvalidoError(f"{nombre} debe ser mayor a cero")
    return numero


def _metodo(valor: str | MetodoPago) -> MetodoPago:
    try:
        return MetodoPago(valor)
    except ValueError as exc:
        raise DatoInvalidoError("El método de pago no es válido") from exc


# ---------- Documentos pendientes ----------

def pedidos_pendientes(db: Session, cliente_id: int | None = None) -> list[PedidoCliente]:
    consulta = (
        select(PedidoCliente)
        .options(
            selectinload(PedidoCliente.lineas),
            selectinload(PedidoCliente.aplicaciones),
            selectinload(PedidoCliente.cliente),
        )
        .where(PedidoCliente.estado.in_(COBRABLES))
        .order_by(PedidoCliente.fecha_pedido, PedidoCliente.id)
    )
    if cliente_id is not None:
        consulta = consulta.where(PedidoCliente.cliente_id == cliente_id)
    return [p for p in db.scalars(consulta) if p.saldo > 0]


def ordenes_pendientes(db: Session, proveedor_id: int | None = None) -> list[OrdenCompra]:
    consulta = (
        select(OrdenCompra)
        .options(
            selectinload(OrdenCompra.lineas),
            selectinload(OrdenCompra.aplicaciones),
            selectinload(OrdenCompra.proveedor),
        )
        .where(OrdenCompra.estado.in_(PAGABLES))
        .order_by(OrdenCompra.fecha, OrdenCompra.id)
    )
    if proveedor_id is not None:
        consulta = consulta.where(OrdenCompra.proveedor_id == proveedor_id)
    return [o for o in db.scalars(consulta) if o.saldo > 0]


# compatibilidad con las pantallas existentes
def cuentas_por_cobrar(db: Session, al: date | None = None) -> list[PedidoCliente]:
    return pedidos_pendientes(db)


def cuentas_por_pagar(db: Session) -> list[OrdenCompra]:
    return ordenes_pendientes(db)


# ---------- Registro de movimientos ----------

def _reparto_automatico(documentos: list, monto: Decimal) -> list[tuple[int, Decimal]]:
    """Aplica de la nota más vieja a la más nueva hasta agotar el monto."""
    restante = monto
    reparto = []
    for documento in documentos:
        if restante <= 0:
            break
        abono = min(restante, documento.saldo)
        reparto.append((documento.id, abono))
        restante -= abono
    return reparto


def _crear(
    db: Session,
    tipo: TipoMovimiento,
    contraparte_id: int,
    monto,
    fecha: date | None,
    metodo,
    referencia: str | None,
    notas: str | None,
    reparto: list[tuple[int, Decimal]] | None,
) -> Pago:
    es_cobro = tipo == TipoMovimiento.COBRO
    if es_cobro:
        contraparte = db.get(Cliente, contraparte_id)
        if contraparte is None or not contraparte.activo:
            raise DatoInvalidoError("El cliente no existe o está inactivo")
        pendientes = pedidos_pendientes(db, contraparte_id)
    else:
        contraparte = db.get(Proveedor, contraparte_id)
        if contraparte is None or not contraparte.activo:
            raise DatoInvalidoError("El proveedor no existe o está inactivo")
        pendientes = ordenes_pendientes(db, contraparte_id)

    cantidad = _monto(monto)
    pago = Pago(
        tipo=tipo,
        cliente_id=contraparte_id if es_cobro else None,
        proveedor_id=None if es_cobro else contraparte_id,
        fecha=fecha or date.today(),
        monto=cantidad,
        metodo=_metodo(metodo),
        referencia=(referencia or "").strip() or None,
        notas=(notas or "").strip() or None,
    )
    db.add(pago)
    db.flush()

    if reparto is None:
        reparto = _reparto_automatico(pendientes, cantidad)
    for documento_id, abono in reparto:
        aplicar(db, pago.id, documento_id, abono)
    return pago


def registrar_cobro(
    db: Session,
    cliente_id: int,
    monto,
    *,
    fecha: date | None = None,
    metodo: str | MetodoPago = MetodoPago.EFECTIVO,
    referencia: str | None = None,
    notas: str | None = None,
    reparto: list[tuple[int, Decimal]] | None = None,
) -> Pago:
    """Dinero que entra de un cliente. Sin reparto, se aplica de la nota más vieja."""
    return _crear(
        db, TipoMovimiento.COBRO, cliente_id, monto, fecha, metodo, referencia, notas, reparto
    )


def registrar_pago(
    db: Session,
    proveedor_id: int,
    monto,
    *,
    fecha: date | None = None,
    metodo: str | MetodoPago = MetodoPago.TRANSFERENCIA,
    referencia: str | None = None,
    notas: str | None = None,
    reparto: list[tuple[int, Decimal]] | None = None,
) -> Pago:
    """Dinero que sale a un proveedor."""
    return _crear(
        db, TipoMovimiento.PAGO, proveedor_id, monto, fecha, metodo, referencia, notas, reparto
    )


def aplicar(db: Session, pago_id: int, documento_id: int, monto) -> AplicacionPago:
    pago = obtener_pago(db, pago_id)
    abono = _monto(monto, "El abono")
    if abono > pago.disponible:
        raise DatoInvalidoError(
            f"El abono excede lo disponible del pago ({pago.disponible:.2f})"
        )

    if pago.tipo == TipoMovimiento.COBRO:
        documento = db.get(PedidoCliente, documento_id)
        if documento is None or documento.cliente_id != pago.cliente_id:
            raise DatoInvalidoError("Ese pedido no pertenece a este cliente")
        if documento.estado not in COBRABLES:
            raise DatoInvalidoError(f"El pedido {documento.folio} no admite cobros")
        ya = next((a for a in documento.aplicaciones if a.pago_id == pago.id), None)
        campos = {"pedido_id": documento.id}
    else:
        documento = db.get(OrdenCompra, documento_id)
        if documento is None or documento.proveedor_id != pago.proveedor_id:
            raise DatoInvalidoError("Esa orden no pertenece a este proveedor")
        if documento.estado not in PAGABLES:
            raise DatoInvalidoError(f"La orden {documento.folio} no admite pagos")
        ya = next((a for a in documento.aplicaciones if a.pago_id == pago.id), None)
        campos = {"orden_id": documento.id}

    if ya is not None:
        raise DatoInvalidoError(f"Este pago ya tiene un abono en {documento.folio}")
    if abono > documento.saldo:
        raise DatoInvalidoError(
            f"El abono a {documento.folio} excede su saldo de {documento.saldo:.2f}"
        )

    aplicacion = AplicacionPago(monto=abono, **campos)
    pago.aplicaciones.append(aplicacion)
    documento.aplicaciones.append(aplicacion)
    db.flush()
    return aplicacion


def _desligar(aplicacion: AplicacionPago) -> None:
    """Saca la aplicación de la colección del documento para que su saldo quede al día."""
    documento = aplicacion.pedido or aplicacion.orden
    if documento is not None and aplicacion in documento.aplicaciones:
        documento.aplicaciones.remove(aplicacion)


def quitar_aplicacion(db: Session, aplicacion_id: int) -> None:
    aplicacion = db.get(AplicacionPago, aplicacion_id)
    if aplicacion is None:
        raise DatoInvalidoError("Ese abono no existe")
    _desligar(aplicacion)
    aplicacion.pago.aplicaciones.remove(aplicacion)
    db.flush()


def obtener_pago(db: Session, pago_id: int) -> Pago:
    pago = db.get(Pago, pago_id)
    if pago is None:
        raise DatoInvalidoError(f"No existe el movimiento {pago_id}")
    return pago


def eliminar_pago(db: Session, pago_id: int) -> None:
    pago = obtener_pago(db, pago_id)
    for aplicacion in list(pago.aplicaciones):
        _desligar(aplicacion)
    db.delete(pago)
    db.flush()


# ---------- Atajos de una sola nota ----------

def cobro_de_pedido(
    db: Session,
    pedido_id: int,
    monto,
    *,
    fecha: date | None = None,
    metodo: str | MetodoPago = MetodoPago.EFECTIVO,
    referencia: str | None = None,
) -> Pago:
    pedido = db.get(PedidoCliente, pedido_id)
    if pedido is None:
        raise DatoInvalidoError(f"No existe el pedido {pedido_id}")
    if pedido.estado == EstadoPedido.BORRADOR:
        raise DatoInvalidoError("Confirma el pedido antes de registrar cobros")
    if pedido.estado not in COBRABLES:
        raise DatoInvalidoError("El pedido está cancelado")

    cantidad = _monto(monto)
    if cantidad > pedido.saldo:
        raise DatoInvalidoError(f"El cobro excede el saldo pendiente de {pedido.saldo:.2f}")
    return registrar_cobro(
        db,
        pedido.cliente_id,
        cantidad,
        fecha=fecha,
        metodo=metodo,
        referencia=referencia,
        reparto=[(pedido.id, cantidad)],
    )


def pago_de_orden(
    db: Session,
    orden_id: int,
    monto,
    *,
    fecha: date | None = None,
    metodo: str | MetodoPago = MetodoPago.TRANSFERENCIA,
    referencia: str | None = None,
) -> Pago:
    orden = db.get(OrdenCompra, orden_id)
    if orden is None:
        raise DatoInvalidoError(f"No existe la orden {orden_id}")
    if orden.estado == EstadoCompra.BORRADOR:
        raise DatoInvalidoError("Envía la orden antes de registrar pagos")
    if orden.estado not in PAGABLES:
        raise DatoInvalidoError("La orden está cancelada")

    cantidad = _monto(monto)
    if cantidad > orden.saldo:
        raise DatoInvalidoError(f"El pago excede el saldo pendiente de {orden.saldo:.2f}")
    return registrar_pago(
        db,
        orden.proveedor_id,
        cantidad,
        fecha=fecha,
        metodo=metodo,
        referencia=referencia,
        reparto=[(orden.id, cantidad)],
    )


def quitar_cobro(db: Session, pedido_id: int, aplicacion_id: int) -> None:
    aplicacion = db.get(AplicacionPago, aplicacion_id)
    if aplicacion is None or aplicacion.pedido_id != pedido_id:
        raise DatoInvalidoError("Ese cobro no pertenece a este pedido")
    if len(aplicacion.pago.aplicaciones) > 1:
        raise DatoInvalidoError(
            "Este cobro cubre varias notas, edítalo desde la pantalla de Cobranza"
        )
    eliminar_pago(db, aplicacion.pago_id)


def quitar_pago(db: Session, orden_id: int, aplicacion_id: int) -> None:
    aplicacion = db.get(AplicacionPago, aplicacion_id)
    if aplicacion is None or aplicacion.orden_id != orden_id:
        raise DatoInvalidoError("Ese pago no pertenece a esta orden")
    if len(aplicacion.pago.aplicaciones) > 1:
        raise DatoInvalidoError(
            "Este pago cubre varias órdenes, edítalo desde la pantalla de Cobranza"
        )
    eliminar_pago(db, aplicacion.pago_id)


# ---------- Saldos a favor y estados de cuenta ----------

def saldo_a_favor_cliente(db: Session, cliente_id: int) -> Decimal:
    pagos = db.scalars(
        select(Pago)
        .options(selectinload(Pago.aplicaciones))
        .where(Pago.tipo == TipoMovimiento.COBRO, Pago.cliente_id == cliente_id)
    )
    return sum((p.disponible for p in pagos), CERO)


def estado_cuenta_cliente(db: Session, cliente_id: int) -> dict:
    cliente = db.get(Cliente, cliente_id)
    if cliente is None:
        raise DatoInvalidoError(f"No existe el cliente {cliente_id}")
    pendientes = pedidos_pendientes(db, cliente_id)
    return {
        "cliente": cliente,
        "pedidos": pendientes,
        "saldo": sum((p.saldo for p in pendientes), CERO),
        "a_favor": saldo_a_favor_cliente(db, cliente_id),
    }


def estado_cuenta_proveedor(db: Session, proveedor_id: int) -> dict:
    proveedor = db.get(Proveedor, proveedor_id)
    if proveedor is None:
        raise DatoInvalidoError(f"No existe el proveedor {proveedor_id}")
    pendientes = ordenes_pendientes(db, proveedor_id)
    return {
        "proveedor": proveedor,
        "ordenes": pendientes,
        "saldo": sum((o.saldo for o in pendientes), CERO),
    }


def antiguedad_saldos(db: Session, al: date | None = None) -> dict[str, Decimal]:
    al = al or date.today()
    tramos = {
        "Por vencer": CERO,
        "1-30": CERO,
        "31-60": CERO,
        "Más de 60": CERO,
    }
    for pedido in pedidos_pendientes(db):
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


def movimientos(
    db: Session, tipo: TipoMovimiento | None = None, limite: int = 100
) -> list[Pago]:
    consulta = (
        select(Pago)
        .options(
            selectinload(Pago.aplicaciones),
            selectinload(Pago.cliente),
            selectinload(Pago.proveedor),
        )
        .order_by(Pago.fecha.desc(), Pago.id.desc())
        .limit(limite)
    )
    if tipo is not None:
        consulta = consulta.where(Pago.tipo == tipo)
    return list(db.scalars(consulta))