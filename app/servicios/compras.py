from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.modelos import (
    EstadoCompra,
    OrdenCompra,
    OrdenCompraLinea,
    Producto,
    Proveedor,
    ProveedorProducto,
)
from app.servicios.catalogo import costo_vigente
from app.servicios.errores import DatoInvalidoError, PrecioNoDefinidoError

CENTAVOS = Decimal("0.01")

TRANSICIONES = {
    EstadoCompra.BORRADOR: {EstadoCompra.ENVIADA, EstadoCompra.CANCELADA},
    EstadoCompra.ENVIADA: {EstadoCompra.RECIBIDA, EstadoCompra.CANCELADA},
    EstadoCompra.RECIBIDA: set(),
    EstadoCompra.CANCELADA: set(),
}


class TransicionInvalidaError(DatoInvalidoError):
    """Cambio de estado no permitido."""


@dataclass(frozen=True)
class LineaCompra:
    producto_id: int
    cantidad: Decimal
    costo_unitario: Decimal | None = None  # None = usar el costo vigente del proveedor


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


def _suministro(db: Session, proveedor_id: int, producto_id: int) -> ProveedorProducto | None:
    return db.scalar(
        select(ProveedorProducto).where(
            ProveedorProducto.proveedor_id == proveedor_id,
            ProveedorProducto.producto_id == producto_id,
            ProveedorProducto.activo.is_(True),
        )
    )


def obtener_orden(db: Session, orden_id: int) -> OrdenCompra:
    orden = db.get(OrdenCompra, orden_id)
    if orden is None:
        raise DatoInvalidoError(f"No existe la orden {orden_id}")
    return orden


def _editable(orden: OrdenCompra) -> None:
    if orden.estado != EstadoCompra.BORRADOR:
        raise TransicionInvalidaError("Solo se pueden editar órdenes en borrador")


def crear_orden(
    db: Session,
    proveedor_id: int,
    *,
    fecha: datetime | None = None,
    numero_remision: str | None = None,
    notas: str | None = None,
) -> OrdenCompra:
    proveedor = db.get(Proveedor, proveedor_id)
    if proveedor is None or not proveedor.activo:
        raise DatoInvalidoError("El proveedor no existe o está inactivo")

    orden = OrdenCompra(
        proveedor_id=proveedor.id,
        fecha=fecha or datetime.now(),
        numero_remision=(numero_remision or "").strip() or None,
        dias_credito=proveedor.dias_credito,
        estado=EstadoCompra.BORRADOR,
        notas=(notas or "").strip() or None,
    )
    db.add(orden)
    db.flush()
    return orden


def agregar_linea(db: Session, orden_id: int, nueva: LineaCompra) -> OrdenCompra:
    orden = obtener_orden(db, orden_id)
    _editable(orden)

    producto = db.get(Producto, nueva.producto_id)
    if producto is None or not producto.activo:
        raise DatoInvalidoError("El producto no existe o está inactivo")

    suministro = _suministro(db, orden.proveedor_id, producto.id)
    if suministro is None:
        raise DatoInvalidoError(
            f"{producto.codigo} no está en el catálogo de {orden.proveedor.nombre}"
        )

    cantidad = _a_decimal(nueva.cantidad, f"La cantidad de {producto.codigo}", 3)
    if cantidad <= 0:
        raise DatoInvalidoError(f"La cantidad de {producto.codigo} debe ser mayor a cero")
    if suministro.solo_unidades_completas and cantidad != cantidad.to_integral_value():
        raise DatoInvalidoError(
            f"{producto.codigo} se compra por {suministro.unidad_compra.nombre.lower()} "
            "completo, sin fracciones"
        )

    if nueva.costo_unitario is None:
        try:
            costo = costo_vigente(db, suministro.id)
        except PrecioNoDefinidoError as exc:
            raise DatoInvalidoError(
                f"{producto.codigo} no tiene costo registrado, captúralo manualmente"
            ) from exc
    else:
        costo = _a_decimal(nueva.costo_unitario, f"El costo de {producto.codigo}", 4)
        if costo < 0:
            raise DatoInvalidoError(f"El costo de {producto.codigo} no puede ser negativo")

    orden.lineas.append(
        OrdenCompraLinea(
            producto_id=producto.id,
            descripcion=producto.descripcion,
            unidad_clave=suministro.unidad_compra.clave,
            cantidad=cantidad,
            costo_unitario=costo,
            importe=(cantidad * costo).quantize(CENTAVOS, rounding=ROUND_HALF_UP),
        )
    )
    db.flush()
    return orden


def quitar_linea(db: Session, orden_id: int, linea_id: int) -> OrdenCompra:
    orden = obtener_orden(db, orden_id)
    _editable(orden)
    linea = next((linea for linea in orden.lineas if linea.id == linea_id), None)
    if linea is None:
        raise DatoInvalidoError("Esa línea no pertenece a esta orden")
    orden.lineas.remove(linea)
    db.flush()
    return orden


def actualizar_datos(
    db: Session, orden_id: int, numero_remision: str | None, notas: str | None
) -> OrdenCompra:
    orden = obtener_orden(db, orden_id)
    if orden.estado == EstadoCompra.CANCELADA:
        raise TransicionInvalidaError("La orden está cancelada")
    orden.numero_remision = (numero_remision or "").strip() or None
    orden.notas = (notas or "").strip() or None
    db.flush()
    return orden


def cambiar_estado(db: Session, orden_id: int, nuevo: EstadoCompra | str) -> OrdenCompra:
    orden = obtener_orden(db, orden_id)
    nuevo = EstadoCompra(nuevo)
    if nuevo not in TRANSICIONES[orden.estado]:
        raise TransicionInvalidaError(f"No se puede pasar de {orden.estado} a {nuevo}")
    if nuevo == EstadoCompra.ENVIADA and not orden.lineas:
        raise DatoInvalidoError("No se puede enviar una orden sin productos")
    orden.estado = nuevo
    db.flush()
    return orden


def recibir(
    db: Session, orden_id: int, fecha_recepcion: date | None = None, numero_remision: str = ""
) -> OrdenCompra:
    orden = obtener_orden(db, orden_id)
    fecha_recepcion = fecha_recepcion or date.today()
    if fecha_recepcion < orden.fecha.date():
        raise DatoInvalidoError("La recepción no puede ser anterior a la orden")

    remision = numero_remision.strip() or orden.numero_remision
    if not remision:
        raise DatoInvalidoError("Captura el número de remisión para recibir la mercancía")

    cambiar_estado(db, orden.id, EstadoCompra.RECIBIDA)
    orden.numero_remision = remision
    orden.fecha_recepcion = fecha_recepcion
    db.flush()
    return orden


def listar_ordenes(
    db: Session, buscar: str = "", estado: str = "", limite: int = 100
) -> list[OrdenCompra]:
    consulta = (
        select(OrdenCompra)
        .options(joinedload(OrdenCompra.proveedor), selectinload(OrdenCompra.lineas))
        .order_by(OrdenCompra.fecha.desc(), OrdenCompra.id.desc())
        .limit(limite)
    )
    buscar = buscar.strip()
    if buscar:
        patron = f"%{buscar}%"
        consulta = consulta.join(OrdenCompra.proveedor).where(
            func.coalesce(OrdenCompra.numero_remision, "").ilike(patron)
            | Proveedor.nombre.ilike(patron)
        )
    if estado:
        consulta = consulta.where(OrdenCompra.estado == EstadoCompra(estado))
    return list(db.scalars(consulta))


def productos_del_proveedor(db: Session, proveedor_id: int) -> list[ProveedorProducto]:
    return list(
        db.scalars(
            select(ProveedorProducto)
            .options(
                joinedload(ProveedorProducto.producto), joinedload(ProveedorProducto.unidad_compra)
            )
            .join(ProveedorProducto.producto)
            .where(
                ProveedorProducto.proveedor_id == proveedor_id,
                ProveedorProducto.activo.is_(True),
            )
            .order_by(Producto.codigo)
        )
    )