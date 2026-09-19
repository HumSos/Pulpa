from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, ConTiempos
from app.modelos.catalogo import Producto
from app.modelos.proveedores import Proveedor
from app.tipos import DecimalFijo

if TYPE_CHECKING:
    from app.modelos.pagos import PagoProveedor


class EstadoCompra(StrEnum):
    BORRADOR = "borrador"
    ENVIADA = "enviada"
    RECIBIDA = "recibida"
    CANCELADA = "cancelada"


class OrdenCompra(ConTiempos, Base):
    __tablename__ = "ordenes_compra"

    id: Mapped[int] = mapped_column(primary_key=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), index=True)
    numero_remision: Mapped[str | None] = mapped_column(String(50))
    fecha: Mapped[datetime] = mapped_column(index=True)
    fecha_recepcion: Mapped[date | None]
    dias_credito: Mapped[int] = mapped_column(default=0)
    estado: Mapped[EstadoCompra] = mapped_column(
        Enum(
            EstadoCompra,
            native_enum=False,
            length=20,
            values_callable=lambda enum: [m.value for m in enum],
        ),
        default=EstadoCompra.BORRADOR,
        index=True,
    )
    notas: Mapped[str | None] = mapped_column(String(500))

    proveedor: Mapped[Proveedor] = relationship()
    lineas: Mapped[list["OrdenCompraLinea"]] = relationship(
        back_populates="orden", cascade="all, delete-orphan", order_by="OrdenCompraLinea.id"
    )
    pagos: Mapped[list["PagoProveedor"]] = relationship(
        back_populates="orden", cascade="all, delete-orphan", order_by="PagoProveedor.fecha"
    )

    @property
    def pagado(self) -> Decimal:
        return sum((pago.monto for pago in self.pagos), Decimal("0.00"))

    @property
    def saldo(self) -> Decimal:
        return self.total - self.pagado

    @property
    def folio(self) -> str:
        return f"OC-{self.id:06d}" if self.id else "OC-nueva"

    @property
    def total(self) -> Decimal:
        return sum((linea.importe for linea in self.lineas), Decimal("0.00"))

    @property
    def fecha_vencimiento(self) -> date:
        base = self.fecha_recepcion or self.fecha.date()
        return base + timedelta(days=self.dias_credito)


class OrdenCompraLinea(ConTiempos, Base):
    __tablename__ = "orden_compra_lineas"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="cantidad_positiva"),
        CheckConstraint("costo_unitario >= 0", name="costo_no_negativo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    orden_id: Mapped[int] = mapped_column(ForeignKey("ordenes_compra.id"), index=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), index=True)
    descripcion: Mapped[str] = mapped_column(String(200))
    unidad_clave: Mapped[str] = mapped_column(String(20))
    cantidad: Mapped[Decimal] = mapped_column(DecimalFijo(3))
    costo_unitario: Mapped[Decimal] = mapped_column(DecimalFijo(4))
    importe: Mapped[Decimal] = mapped_column(DecimalFijo(2))

    orden: Mapped[OrdenCompra] = relationship(back_populates="lineas")
    producto: Mapped[Producto] = relationship()