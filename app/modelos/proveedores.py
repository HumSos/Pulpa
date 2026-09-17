from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, ConTiempos
from app.modelos.catalogo import Producto, Unidad
from app.tipos import DecimalFijo


class Proveedor(ConTiempos, Base):
    __tablename__ = "proveedores"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(150), unique=True)
    contacto: Mapped[str | None] = mapped_column(String(150))
    telefono: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(150))
    dias_credito: Mapped[int] = mapped_column(default=0)
    activo: Mapped[bool] = mapped_column(default=True)

    productos: Mapped[list["ProveedorProducto"]] = relationship(back_populates="proveedor")


class ProveedorProducto(ConTiempos, Base):
    """Qué producto surte cada proveedor y en qué presentación lo vende."""

    __tablename__ = "proveedor_producto"
    __table_args__ = (
        UniqueConstraint("proveedor_id", "producto_id"),
        CheckConstraint("factor_conversion > 0", name="factor_positivo"),
        Index(
            "uq_proveedor_producto_un_preferido",
            "producto_id",
            unique=True,
            sqlite_where=text("es_preferido = 1"),
            postgresql_where=text("es_preferido"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"))
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    unidad_compra_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"))
    factor_conversion: Mapped[Decimal] = mapped_column(DecimalFijo(4))
    solo_unidades_completas: Mapped[bool] = mapped_column(default=True)
    es_preferido: Mapped[bool] = mapped_column(default=False)
    codigo_proveedor: Mapped[str | None] = mapped_column(String(50))
    activo: Mapped[bool] = mapped_column(default=True)

    proveedor: Mapped[Proveedor] = relationship(back_populates="productos")
    producto: Mapped[Producto] = relationship(back_populates="proveedores")
    unidad_compra: Mapped[Unidad] = relationship()
    costos: Mapped[list["CostoProveedor"]] = relationship(back_populates="proveedor_producto")


class CostoProveedor(ConTiempos, Base):
    __tablename__ = "costos_proveedor"
    __table_args__ = (
        UniqueConstraint("proveedor_producto_id", "vigente_desde"),
        CheckConstraint("costo >= 0", name="costo_no_negativo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    proveedor_producto_id: Mapped[int] = mapped_column(ForeignKey("proveedor_producto.id"))
    costo: Mapped[Decimal] = mapped_column(DecimalFijo(4))
    vigente_desde: Mapped[datetime]

    proveedor_producto: Mapped[ProveedorProducto] = relationship(back_populates="costos")