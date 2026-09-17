from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modelos import CostoProveedor, PrecioVenta, ProveedorProducto


class PrecioNoDefinidoError(Exception):
    """No hay precio o costo vigente en la fecha pedida."""


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


def registrar_precio(
    db: Session, producto_id: int, precio: Decimal, vigente_desde: datetime | None = None
) -> PrecioVenta:
    precio = Decimal(str(precio))
    if precio < 0:
        raise ValueError("El precio no puede ser negativo")
    nuevo = PrecioVenta(
        producto_id=producto_id, precio=precio, vigente_desde=vigente_desde or datetime.now()
    )
    db.add(nuevo)
    db.flush()
    return nuevo


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
    db: Session, proveedor_producto_id: int, costo: Decimal, vigente_desde: datetime | None = None
) -> CostoProveedor:
    costo = Decimal(str(costo))
    if costo < 0:
        raise ValueError("El costo no puede ser negativo")
    nuevo = CostoProveedor(
        proveedor_producto_id=proveedor_producto_id,
        costo=costo,
        vigente_desde=vigente_desde or datetime.now(),
    )
    db.add(nuevo)
    db.flush()
    return nuevo


def marcar_preferido(db: Session, proveedor_producto_id: int) -> ProveedorProducto:
    relacion = db.get(ProveedorProducto, proveedor_producto_id)
    if relacion is None:
        raise ValueError(f"No existe la relación proveedor-producto {proveedor_producto_id}")

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