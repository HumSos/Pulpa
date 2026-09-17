from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, ConTiempos
from app.tipos import DecimalFijo

if TYPE_CHECKING:
    from app.modelos.proveedores import ProveedorProducto


class Unidad(ConTiempos, Base):
    __tablename__ = "unidades"

    id: Mapped[int] = mapped_column(primary_key=True)
    clave: Mapped[str] = mapped_column(String(20), unique=True)
    nombre: Mapped[str] = mapped_column(String(50))
    permite_decimales: Mapped[bool] = mapped_column(default=False)


class Producto(ConTiempos, Base):
    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(30), unique=True)
    descripcion: Mapped[str] = mapped_column(String(200))
    unidad_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"))
    activo: Mapped[bool] = mapped_column(default=True)

    unidad: Mapped[Unidad] = relationship()
    precios: Mapped[list["PrecioVenta"]] = relationship(back_populates="producto")
    proveedores: Mapped[list["ProveedorProducto"]] = relationship(back_populates="producto")


class PrecioVenta(ConTiempos, Base):
    __tablename__ = "precios_venta"
    __table_args__ = (
        UniqueConstraint("producto_id", "vigente_desde"),
        CheckConstraint("precio >= 0", name="precio_no_negativo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    precio: Mapped[Decimal] = mapped_column(DecimalFijo(4))
    vigente_desde: Mapped[datetime]

    producto: Mapped[Producto] = relationship(back_populates="precios")