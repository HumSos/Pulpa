from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.modelos import (
    Cliente,
    EstadoCompra,
    EstadoPedido,
    OrdenCompra,
    OrdenCompraLinea,
    Pago,
    PedidoCliente,
    PedidoClienteLinea,
    Producto,
    TipoMovimiento,
)

CERO = Decimal("0.00")
CENTAVOS = Decimal("0.01")
VENDIDOS = (EstadoPedido.CONFIRMADO, EstadoPedido.ENTREGADO)
COMPRADAS = (EstadoCompra.ENVIADA, EstadoCompra.RECIBIDA)


@dataclass(frozen=True)
class Periodo:
    desde: date
    hasta: date

    @property
    def inicio(self) -> datetime:
        return datetime.combine(self.desde, time.min)

    @property
    def fin(self) -> datetime:
        return datetime.combine(self.hasta, time.max)

    @property
    def dias(self) -> int:
        return (self.hasta - self.desde).days + 1

    def anterior(self) -> "Periodo":
        return Periodo(self.desde - timedelta(days=self.dias), self.desde - timedelta(days=1))


def periodo_mes_actual(hoy: date | None = None) -> Periodo:
    hoy = hoy or date.today()
    return Periodo(hoy.replace(day=1), hoy)


def _ventas(periodo: Periodo) -> Select:
    return (
        select(PedidoCliente)
        .where(
            PedidoCliente.estado.in_(VENDIDOS),
            PedidoCliente.fecha_pedido.between(periodo.inicio, periodo.fin),
        )
    )


def _escalar(db: Session, consulta: Select) -> Decimal:
    return db.scalar(consulta) or CERO


def ventas_del_periodo(db: Session, periodo: Periodo) -> Decimal:
    return _escalar(
        db,
        select(func.sum(PedidoClienteLinea.importe))
        .join(PedidoClienteLinea.pedido)
        .where(
            PedidoCliente.estado.in_(VENDIDOS),
            PedidoCliente.fecha_pedido.between(periodo.inicio, periodo.fin),
        ),
    )


def compras_del_periodo(db: Session, periodo: Periodo) -> Decimal:
    return _escalar(
        db,
        select(func.sum(OrdenCompraLinea.importe))
        .join(OrdenCompraLinea.orden)
        .where(
            OrdenCompra.estado.in_(COMPRADAS),
            OrdenCompra.fecha.between(periodo.inicio, periodo.fin),
        ),
    )


def cobrado_del_periodo(db: Session, periodo: Periodo) -> Decimal:
    return _escalar(
        db,
        select(func.sum(Pago.monto)).where(
            Pago.tipo == TipoMovimiento.COBRO,
            Pago.fecha.between(periodo.desde, periodo.hasta),
        ),
    )


def pagado_del_periodo(db: Session, periodo: Periodo) -> Decimal:
    return _escalar(
        db,
        select(func.sum(Pago.monto)).where(
            Pago.tipo == TipoMovimiento.PAGO,
            Pago.fecha.between(periodo.desde, periodo.hasta),
        ),
    )


def numero_de_pedidos(db: Session, periodo: Periodo) -> int:
    return db.scalar(select(func.count()).select_from(_ventas(periodo).subquery())) or 0


def clientes_atendidos(db: Session, periodo: Periodo) -> int:
    return (
        db.scalar(
            select(func.count(func.distinct(PedidoCliente.cliente_id))).where(
                PedidoCliente.estado.in_(VENDIDOS),
                PedidoCliente.fecha_pedido.between(periodo.inicio, periodo.fin),
            )
        )
        or 0
    )


def descuentos_otorgados(db: Session, periodo: Periodo) -> Decimal:
    """Cuánto se dejó de cobrar por vender debajo del precio de lista.

    El cálculo se hace en Python porque multiplicar dos columnas DecimalFijo
    dentro de SQL devuelve el producto de los enteros escalados, no el valor real.
    """
    filas = db.execute(
        select(
            PedidoClienteLinea.precio_lista,
            PedidoClienteLinea.precio_unitario,
            PedidoClienteLinea.cantidad,
        )
        .join(PedidoClienteLinea.pedido)
        .where(
            PedidoCliente.estado.in_(VENDIDOS),
            PedidoCliente.fecha_pedido.between(periodo.inicio, periodo.fin),
            PedidoClienteLinea.precio_lista.is_not(None),
            PedidoClienteLinea.precio_unitario < PedidoClienteLinea.precio_lista,
        )
    )
    total = sum(((lista - cobrado) * cantidad for lista, cobrado, cantidad in filas), CERO)
    return total.quantize(CENTAVOS)


def top_productos(db: Session, periodo: Periodo, limite: int = 5) -> list[tuple[str, Decimal]]:
    filas = db.execute(
        select(Producto.descripcion, func.sum(PedidoClienteLinea.importe).label("total"))
        .join(PedidoClienteLinea.producto)
        .join(PedidoClienteLinea.pedido)
        .where(
            PedidoCliente.estado.in_(VENDIDOS),
            PedidoCliente.fecha_pedido.between(periodo.inicio, periodo.fin),
        )
        .group_by(Producto.id, Producto.descripcion)
        .order_by(func.sum(PedidoClienteLinea.importe).desc())
        .limit(limite)
    )
    return [(descripcion, total) for descripcion, total in filas]


def top_clientes(db: Session, periodo: Periodo, limite: int = 5) -> list[tuple[str, Decimal]]:
    filas = db.execute(
        select(Cliente.nombre_negocio, func.sum(PedidoClienteLinea.importe).label("total"))
        .join(PedidoCliente, PedidoCliente.cliente_id == Cliente.id)
        .join(PedidoClienteLinea, PedidoClienteLinea.pedido_id == PedidoCliente.id)
        .where(
            PedidoCliente.estado.in_(VENDIDOS),
            PedidoCliente.fecha_pedido.between(periodo.inicio, periodo.fin),
        )
        .group_by(Cliente.id, Cliente.nombre_negocio)
        .order_by(func.sum(PedidoClienteLinea.importe).desc())
        .limit(limite)
    )
    return [(nombre, total) for nombre, total in filas]


def ventas_por_dia(db: Session, periodo: Periodo) -> list[tuple[date, Decimal]]:
    filas = db.execute(
        select(
            func.date(PedidoCliente.fecha_pedido).label("dia"),
            func.sum(PedidoClienteLinea.importe),
        )
        .join(PedidoClienteLinea, PedidoClienteLinea.pedido_id == PedidoCliente.id)
        .where(
            PedidoCliente.estado.in_(VENDIDOS),
            PedidoCliente.fecha_pedido.between(periodo.inicio, periodo.fin),
        )
        .group_by("dia")
        .order_by("dia")
    )
    return [
        (dia if isinstance(dia, date) else date.fromisoformat(dia), total) for dia, total in filas
    ]


def _ventas_agrupadas(
    db: Session, periodo: Periodo, columna, por: str = "cliente", limite: int = 8
) -> list[tuple[str, Decimal]]:
    etiqueta = func.coalesce(func.nullif(func.trim(columna), ""), "Sin clasificar")
    consulta = select(etiqueta, func.sum(PedidoClienteLinea.importe)).join(
        PedidoCliente, PedidoClienteLinea.pedido_id == PedidoCliente.id
    )
    if por == "cliente":
        consulta = consulta.join(Cliente, PedidoCliente.cliente_id == Cliente.id)
    elif por == "producto":
        consulta = consulta.join(Producto, PedidoClienteLinea.producto_id == Producto.id)

    filas = db.execute(
        consulta.where(
            PedidoCliente.estado.in_(VENDIDOS),
            PedidoCliente.fecha_pedido.between(periodo.inicio, periodo.fin),
        )
        .group_by(etiqueta)
        .order_by(func.sum(PedidoClienteLinea.importe).desc())
        .limit(limite)
    )
    return [(str(etiqueta_valor), total) for etiqueta_valor, total in filas]


def ventas_por_categoria(db: Session, periodo: Periodo) -> list[tuple[str, Decimal]]:
    return _ventas_agrupadas(db, periodo, Producto.categoria, por="producto")


def ventas_por_plaza(db: Session, periodo: Periodo) -> list[tuple[str, Decimal]]:
    return _ventas_agrupadas(db, periodo, Cliente.plaza)


def ventas_por_tipo_negocio(db: Session, periodo: Periodo) -> list[tuple[str, Decimal]]:
    return _ventas_agrupadas(db, periodo, Cliente.tipo_negocio)


def ventas_por_vendedor(db: Session, periodo: Periodo) -> list[tuple[str, Decimal]]:
    return _ventas_agrupadas(db, periodo, PedidoCliente.vendedor, por="pedido")


def resumen(db: Session, periodo: Periodo) -> dict:
    ventas = ventas_del_periodo(db, periodo)
    compras = compras_del_periodo(db, periodo)
    pedidos = numero_de_pedidos(db, periodo)
    previo = periodo.anterior()
    ventas_previas = ventas_del_periodo(db, previo)

    return {
        "periodo": periodo,
        "ventas": ventas,
        "compras": compras,
        "margen": ventas - compras,
        "margen_pct": (ventas - compras) / ventas * 100 if ventas else CERO,
        "cobrado": cobrado_del_periodo(db, periodo),
        "pagado": pagado_del_periodo(db, periodo),
        "pedidos": pedidos,
        "ticket_promedio": ventas / pedidos if pedidos else CERO,
        "clientes": clientes_atendidos(db, periodo),
        "descuentos": descuentos_otorgados(db, periodo),
        "ventas_previas": ventas_previas,
        "variacion_pct": (ventas - ventas_previas) / ventas_previas * 100
        if ventas_previas
        else None,
        "top_productos": top_productos(db, periodo),
        "top_clientes": top_clientes(db, periodo),
        "ventas_por_dia": ventas_por_dia(db, periodo),
        "por_categoria": ventas_por_categoria(db, periodo),
        "por_plaza": ventas_por_plaza(db, periodo),
        "por_tipo_negocio": ventas_por_tipo_negocio(db, periodo),
        "por_vendedor": ventas_por_vendedor(db, periodo),
    }