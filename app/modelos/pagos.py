from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, ConTiempos
from app.modelos.compras import OrdenCompra
from app.modelos.pedidos import PedidoCliente
from app.tipos import DecimalFijo


class MetodoPago(StrEnum):
    EFECTIVO = "efectivo"
    TRANSFERENCIA = "transferencia"
    CHEQUE = "cheque"
    TARJETA = "tarjeta"
    OTRO = "otro"


def _enum_metodo():
    return Enum(
        MetodoPago,
        native_enum=False,
        length=20,
        values_callable=lambda enum: [m.value for m in enum],
    )


class CobroCliente(ConTiempos, Base):
    """Dinero que entra: abonos del cliente a un pedido."""

    __tablename__ = "cobros_cliente"
    __table_args__ = (CheckConstraint("monto > 0", name="monto_positivo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos_cliente.id"), index=True)
    fecha: Mapped[date] = mapped_column(index=True)
    monto: Mapped[Decimal] = mapped_column(DecimalFijo(2))
    metodo: Mapped[MetodoPago] = mapped_column(_enum_metodo(), default=MetodoPago.EFECTIVO)
    referencia: Mapped[str | None] = mapped_column(String(80))
    notas: Mapped[str | None] = mapped_column(String(300))

    pedido: Mapped[PedidoCliente] = relationship(back_populates="cobros")


class PagoProveedor(ConTiempos, Base):
    """Dinero que sale: abonos a una orden de compra."""

    __tablename__ = "pagos_proveedor"
    __table_args__ = (CheckConstraint("monto > 0", name="monto_positivo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    orden_id: Mapped[int] = mapped_column(ForeignKey("ordenes_compra.id"), index=True)
    fecha: Mapped[date] = mapped_column(index=True)
    monto: Mapped[Decimal] = mapped_column(DecimalFijo(2))
    metodo: Mapped[MetodoPago] = mapped_column(_enum_metodo(), default=MetodoPago.TRANSFERENCIA)
    referencia: Mapped[str | None] = mapped_column(String(80))
    notas: Mapped[str | None] = mapped_column(String(300))

    orden: Mapped[OrdenCompra] = relationship(back_populates="pagos")