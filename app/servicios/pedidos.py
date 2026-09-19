from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.modelos import (
    Cliente,
    DireccionEntrega,
    EstadoPedido,
    PedidoCliente,
    PedidoClienteLinea,
    Producto,
)
from app.servicios.catalogo import precio_vigente
from app.servicios.errores import DatoInvalidoError, PrecioNoDefinidoError

CENTAVOS = Decimal("0.01")

TRANSICIONES = {
    EstadoPedido.BORRADOR: {EstadoPedido.CONFIRMADO, EstadoPedido.CANCELADO},
    EstadoPedido.CONFIRMADO: {EstadoPedido.ENTREGADO, EstadoPedido.CANCELADO},
    EstadoPedido.ENTREGADO: set(),
    EstadoPedido.CANCELADO: set(),
}


class TransicionInvalidaError(DatoInvalidoError):
    """Cambio de estado no permitido."""


@dataclass(frozen=True)
class LineaNueva:
    producto_id: int
    cantidad: Decimal
    precio_unitario: Decimal | None = None  # None = usar el precio vigente


def _a_decimal(valor, nombre: str, decimales: int) -> Decimal:
    try:
        numero = Decimal(str(valor))
    except InvalidOperation as exc:
        raise DatoInvalidoError(f"{nombre} no es un número válido") from exc
    if not numero.is_finite():
        raise DatoInvalidoError(f"{nombre} no es un número válido")
    if numero != numero.quantize(Decimal(1).scaleb(-decimales)):
        raise DatoInvalidoError(f"{nombre} admite máximo {decimales} decimales")
    return numero


def _validar_lineas(lineas: list[LineaNueva]) -> None:
    if not lineas:
        raise DatoInvalidoError("El pedido debe tener al menos un producto")
    ids = [linea.producto_id for linea in lineas]
    if len(ids) != len(set(ids)):
        raise DatoInvalidoError("Hay productos repetidos, combina las cantidades en una línea")


def _construir_linea(db: Session, nueva: LineaNueva, en: datetime) -> PedidoClienteLinea:
    producto = db.get(Producto, nueva.producto_id)
    if producto is None or not producto.activo:
        raise DatoInvalidoError(f"El producto {nueva.producto_id} no existe o está inactivo")

    cantidad = _a_decimal(nueva.cantidad, f"La cantidad de {producto.codigo}", 3)
    if cantidad <= 0:
        raise DatoInvalidoError(f"La cantidad de {producto.codigo} debe ser mayor a cero")
    if not producto.unidad.permite_decimales and cantidad != cantidad.to_integral_value():
        raise DatoInvalidoError(
            f"{producto.codigo} se vende por {producto.unidad.nombre.lower()}, sin fracciones"
        )

    try:
        precio_lista = precio_vigente(db, producto.id, en)
    except PrecioNoDefinidoError:
        precio_lista = None

    if nueva.precio_unitario is None:
        if precio_lista is None:
            raise DatoInvalidoError(
                f"{producto.codigo} no tiene precio vigente, captura el precio manualmente"
            )
        precio = precio_lista
    else:
        precio = _a_decimal(nueva.precio_unitario, f"El precio de {producto.codigo}", 4)
        if precio < 0:
            raise DatoInvalidoError(f"El precio de {producto.codigo} no puede ser negativo")

    return PedidoClienteLinea(
        producto_id=producto.id,
        descripcion=producto.descripcion,
        unidad_clave=producto.unidad.clave,
        cantidad=cantidad,
        precio_lista=precio_lista,
        precio_unitario=precio,
        importe=(cantidad * precio).quantize(CENTAVOS, rounding=ROUND_HALF_UP),
    )


def obtener_pedido(db: Session, pedido_id: int) -> PedidoCliente:
    pedido = db.get(PedidoCliente, pedido_id)
    if pedido is None:
        raise DatoInvalidoError(f"No existe el pedido {pedido_id}")
    return pedido


def crear_pedido(
    db: Session,
    cliente_id: int,
    lineas: list[LineaNueva],
    *,
    fecha_pedido: datetime | None = None,
    fecha_entrega: date | None = None,
    direccion_entrega_id: int | None = None,
    referencia_cliente: str | None = None,
    notas: str | None = None,
) -> PedidoCliente:
    _validar_lineas(lineas)
    pedido = crear_pedido_vacio(
        db,
        cliente_id,
        fecha_pedido=fecha_pedido,
        fecha_entrega=fecha_entrega,
        direccion_entrega_id=direccion_entrega_id,
        referencia_cliente=referencia_cliente,
        notas=notas,
    )
    pedido.lineas = [_construir_linea(db, linea, pedido.fecha_pedido) for linea in lineas]
    db.flush()
    return pedido


def reemplazar_lineas(
    db: Session, pedido_id: int, lineas: list[LineaNueva]
) -> PedidoCliente:
    pedido = obtener_pedido(db, pedido_id)
    if pedido.estado != EstadoPedido.BORRADOR:
        raise TransicionInvalidaError("Solo se pueden editar pedidos en borrador")
    _validar_lineas(lineas)

    nuevas = [_construir_linea(db, linea, pedido.fecha_pedido) for linea in lineas]
    pedido.lineas.clear()
    db.flush()
    pedido.lineas.extend(nuevas)
    db.flush()
    return pedido


def cambiar_estado(db: Session, pedido_id: int, nuevo: EstadoPedido | str) -> PedidoCliente:
    pedido = obtener_pedido(db, pedido_id)
    nuevo = EstadoPedido(nuevo)
    if nuevo not in TRANSICIONES[pedido.estado]:
        raise TransicionInvalidaError(f"No se puede pasar de {pedido.estado} a {nuevo}")
    pedido.estado = nuevo
    db.flush()
    return pedido




def listar_pedidos(
    db: Session, buscar: str = "", estado: str = "", limite: int = 100
) -> list[PedidoCliente]:
    consulta = (
        select(PedidoCliente)
        .options(joinedload(PedidoCliente.cliente), selectinload(PedidoCliente.lineas))
        .order_by(PedidoCliente.fecha_pedido.desc(), PedidoCliente.id.desc())
        .limit(limite)
    )
    buscar = buscar.strip()
    if buscar:
        consulta = consulta.join(PedidoCliente.cliente).where(
            Cliente.nombre_negocio.ilike(f"%{buscar}%")
        )
    if estado:
        consulta = consulta.where(PedidoCliente.estado == EstadoPedido(estado))
    return list(db.scalars(consulta))


def agregar_linea(db: Session, pedido_id: int, nueva: LineaNueva) -> PedidoCliente:
    pedido = obtener_pedido(db, pedido_id)
    if pedido.estado != EstadoPedido.BORRADOR:
        raise TransicionInvalidaError("Solo se pueden editar pedidos en borrador")
    if any(linea.producto_id == nueva.producto_id for linea in pedido.lineas):
        raise DatoInvalidoError("Ese producto ya está en el pedido, edita su cantidad")

    pedido.lineas.append(_construir_linea(db, nueva, pedido.fecha_pedido))
    db.flush()
    return pedido


def quitar_linea(db: Session, pedido_id: int, linea_id: int) -> PedidoCliente:
    pedido = obtener_pedido(db, pedido_id)
    if pedido.estado != EstadoPedido.BORRADOR:
        raise TransicionInvalidaError("Solo se pueden editar pedidos en borrador")

    linea = next((linea for linea in pedido.lineas if linea.id == linea_id), None)
    if linea is None:
        raise DatoInvalidoError("Esa línea no pertenece a este pedido")
    pedido.lineas.remove(linea)
    db.flush()
    return pedido


def confirmar_pedido(db: Session, pedido_id: int) -> PedidoCliente:
    pedido = obtener_pedido(db, pedido_id)
    if not pedido.lineas:
        raise DatoInvalidoError("No se puede confirmar un pedido sin productos")
    return cambiar_estado(db, pedido.id, EstadoPedido.CONFIRMADO)


def totales_por_estado(db: Session) -> dict[str, int]:
    filas = db.execute(
        select(PedidoCliente.estado, func.count()).group_by(PedidoCliente.estado)
    )
    return {estado.value: cantidad for estado, cantidad in filas}

def crear_pedido_vacio(
    db: Session,
    cliente_id: int,
    *,
    fecha_pedido: datetime | None = None,
    fecha_entrega: date | None = None,
    direccion_entrega_id: int | None = None,
    referencia_cliente: str | None = None,
    notas: str | None = None,
) -> PedidoCliente:
    cliente = db.get(Cliente, cliente_id)
    if cliente is None or not cliente.activo:
        raise DatoInvalidoError("El cliente no existe o está inactivo")

    fecha_pedido = fecha_pedido or datetime.now()
    if fecha_entrega and fecha_entrega < fecha_pedido.date():
        raise DatoInvalidoError("La fecha de entrega no puede ser anterior al pedido")

    direccion_texto = cliente.direccion
    if direccion_entrega_id is not None:
        direccion = db.get(DireccionEntrega, direccion_entrega_id)
        if direccion is None or direccion.cliente_id != cliente.id or not direccion.activo:
            raise DatoInvalidoError("La dirección de entrega no es válida para este cliente")
        direccion_texto = direccion.direccion

    pedido = PedidoCliente(
        cliente_id=cliente.id,
        direccion_entrega_id=direccion_entrega_id,
        direccion_entrega=direccion_texto,
        referencia_cliente=(referencia_cliente or "").strip() or None,
        fecha_pedido=fecha_pedido,
        fecha_entrega=fecha_entrega,
        dias_credito=cliente.dias_credito,
        estado=EstadoPedido.BORRADOR,
        notas=(notas or "").strip() or None,
    )
    db.add(pedido)
    db.flush()
    return pedido