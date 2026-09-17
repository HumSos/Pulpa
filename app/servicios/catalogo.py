from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from app.modelos import CostoProveedor, PrecioVenta, Producto, ProveedorProducto, Unidad


class PrecioNoDefinidoError(Exception):
    """No hay precio o costo vigente en la fecha pedida."""


class DatoInvalidoError(ValueError):
    """Datos capturados que no cumplen las reglas del catálogo."""


def _validar_monto(valor, nombre: str) -> Decimal:
    monto = Decimal(str(valor))
    if not monto.is_finite():
        raise DatoInvalidoError(f"El {nombre} no es un número válido")
    if monto < 0:
        raise DatoInvalidoError(f"El {nombre} no puede ser negativo")
    return monto


# ---------- Unidades y productos ----------

def listar_unidades(db: Session) -> list[Unidad]:
    return list(db.scalars(select(Unidad).order_by(Unidad.nombre)))


def listar_productos(
    db: Session, buscar: str = "", incluir_inactivos: bool = False
) -> list[Producto]:
    consulta = select(Producto).options(joinedload(Producto.unidad)).order_by(Producto.codigo)
    buscar = buscar.strip()
    if buscar:
        patron = f"%{buscar}%"
        consulta = consulta.where(
            or_(Producto.codigo.ilike(patron), Producto.descripcion.ilike(patron))
        )
    if not incluir_inactivos:
        consulta = consulta.where(Producto.activo.is_(True))
    return list(db.scalars(consulta))


def crear_producto(
    db: Session,
    codigo: str,
    descripcion: str,
    unidad_id: int,
    precio_inicial: Decimal | None = None,
) -> Producto:
    codigo = codigo.strip().upper()
    descripcion = descripcion.strip()
    if not codigo or not descripcion:
        raise DatoInvalidoError("El código y la descripción son obligatorios")
    if db.scalar(select(Producto.id).where(Producto.codigo == codigo)):
        raise DatoInvalidoError(f"Ya existe un producto con el código {codigo}")
    if db.get(Unidad, unidad_id) is None:
        raise DatoInvalidoError("La unidad seleccionada no existe")

    producto = Producto(codigo=codigo, descripcion=descripcion, unidad_id=unidad_id)
    db.add(producto)
    db.flush()
    if precio_inicial is not None:
        registrar_precio(db, producto.id, precio_inicial)
    return producto


# ---------- Precios de venta ----------

def precio_vigente(db: Session, producto_id: int, en: datetime | None = None) -> Decimal:
    en = en or datetime.now()
    precio = db.scalar(
        select(PrecioVenta.precio)
        .where(PrecioVenta.producto_id == producto_id, PrecioVenta.vigente_desde <= en)
        .order_by(PrecioVenta.vigente_desde.desc())
        .limit(1)
    )
    if precio is None:
        raise PrecioNoDefinidoError(
            f"Producto {producto_id} sin precio vigente al {en:%Y-%m-%d %H:%M}"
        )
    return precio


def precios_vigentes(
    db: Session, producto_ids: list[int], en: datetime | None = None
) -> dict[int, Decimal]:
    """Precio vigente de varios productos en dos consultas, sin N+1."""
    en = en or datetime.now()
    ultimo = (
        select(PrecioVenta.producto_id, func.max(PrecioVenta.vigente_desde).label("desde"))
        .where(PrecioVenta.producto_id.in_(producto_ids), PrecioVenta.vigente_desde <= en)
        .group_by(PrecioVenta.producto_id)
        .subquery()
    )
    filas = db.execute(
        select(PrecioVenta.producto_id, PrecioVenta.precio).join(
            ultimo,
            (PrecioVenta.producto_id == ultimo.c.producto_id)
            & (PrecioVenta.vigente_desde == ultimo.c.desde),
        )
    )
    return {producto_id: precio for producto_id, precio in filas}


def historial_precios(db: Session, producto_id: int) -> list[PrecioVenta]:
    return list(
        db.scalars(
            select(PrecioVenta)
            .where(PrecioVenta.producto_id == producto_id)
            .order_by(PrecioVenta.vigente_desde.desc())
        )
    )


def registrar_precio(
    db: Session, producto_id: int, precio, vigente_desde: datetime | None = None
) -> PrecioVenta:
    nuevo = PrecioVenta(
        producto_id=producto_id,
        precio=_validar_monto(precio, "precio"),
        vigente_desde=vigente_desde or datetime.now(),
    )
    db.add(nuevo)
    db.flush()
    return nuevo


# ---------- Costos y proveedores ----------

def costo_vigente(
    db: Session, proveedor_producto_id: int, en: datetime | None = None
) -> Decimal:
    en = en or datetime.now()
    costo = db.scalar(
        select(CostoProveedor.costo)
        .where(
            CostoProveedor.proveedor_producto_id == proveedor_producto_id,
            CostoProveedor.vigente_desde <= en,
        )
        .order_by(CostoProveedor.vigente_desde.desc())
        .limit(1)
    )
    if costo is None:
        raise PrecioNoDefinidoError(
            f"Relación {proveedor_producto_id} sin costo vigente al {en:%Y-%m-%d %H:%M}"
        )
    return costo


def registrar_costo(
    db: Session, proveedor_producto_id: int, costo, vigente_desde: datetime | None = None
) -> CostoProveedor:
    nuevo = CostoProveedor(
        proveedor_producto_id=proveedor_producto_id,
        costo=_validar_monto(costo, "costo"),
        vigente_desde=vigente_desde or datetime.now(),
    )
    db.add(nuevo)
    db.flush()
    return nuevo


def marcar_preferido(db: Session, proveedor_producto_id: int) -> ProveedorProducto:
    relacion = db.get(ProveedorProducto, proveedor_producto_id)
    if relacion is None:
        raise DatoInvalidoError(
            f"No existe la relación proveedor-producto {proveedor_producto_id}"
        )
    db.execute(
        update(ProveedorProducto)
        .where(
            ProveedorProducto.producto_id == relacion.producto_id,
            ProveedorProducto.es_preferido.is_(True),
        )
        .values(es_preferido=False)
    )
    relacion.es_preferido = True
    db.flush()
    return relacion