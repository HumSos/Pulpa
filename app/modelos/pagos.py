from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, ConTiempos
from app.modelos.clientes import Cliente
from app.modelos.proveedores import Proveedor
from app.tipos import DecimalFijo

if TYPE_CHECKING:
    from app.modelos.compras import OrdenCompra
    from app.modelos.pedidos import PedidoCliente

CERO = Decimal("0.00")


class TipoMovimiento(StrEnum):
    COBRO = "cobro"  # entra dinero de un cliente
    PAGO = "pago"    # sale dinero a un proveedor


class MetodoPago(StrEnum):
    EFECTIVO = "efectivo"
    TRANSFERENCIA = "transferencia"
    CHEQUE = "cheque"
    TARJETA = "tarjeta"
    OTRO = "otro"


def _enum(tipo):
    return Enum(
        tipo, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e]
    )


class Pago(ConTiempos, Base):
    """Un movimiento de dinero, repartible entre varios documentos."""

    __tablename__ = "pagos"
    __table_args__ = (
        CheckConstraint("monto > 0", name="monto_positivo"),
        CheckConstraint(
            "(tipo = 'cobro' AND cliente_id IS NOT NULL AND proveedor_id IS NULL)"
            " OR (tipo = 'pago' AND proveedor_id IS NOT NULL AND cliente_id IS NULL)",
            name="contraparte_segun_tipo",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[TipoMovimiento] = mapped_column(_enum(TipoMovimiento), index=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"), index=True)
    proveedor_id: Mapped[int | None] = mapped_column(ForeignKey("proveedores.id"), index=True)
    fecha: Mapped[date] = mapped_column(index=True)
    monto: Mapped[Decimal] = mapped_column(DecimalFijo(2))
    metodo: Mapped[MetodoPago] = mapped_column(_enum(MetodoPago), default=MetodoPago.EFECTIVO)
    referencia: Mapped[str | None] = mapped_column(String(80))
    notas: Mapped[str | None] = mapped_column(String(300))

    cliente: Mapped[Cliente | None] = relationship()
    proveedor: Mapped[Proveedor | None] = relationship()
    aplicaciones: Mapped[list["AplicacionPago"]] = relationship(
        back_populates="pago", cascade="all, delete-orphan", order_by="AplicacionPago.id"
    )

    @property
    def folio(self) -> str:
        prefijo = "C" if self.tipo == TipoMovimiento.COBRO else "P"
        return f"{prefijo}-{self.id:06d}" if self.id else f"{prefijo}-nuevo"

    @property
    def aplicado(self) -> Decimal:
        return sum((a.monto for a in self.aplicaciones), CERO)

    @property
    def disponible(self) -> Decimal:
        """Lo que aún no se aplica a ningún documento (saldo a favor)."""
        return self.monto - self.aplicado

    @property
    def contraparte(self) -> str:
        if self.cliente is not None:
            return self.cliente.nombre_negocio
        return self.proveedor.nombre if self.proveedor else ""


class AplicacionPago(ConTiempos, Base):
    """Parte de un pago abonada a un documento."""

    __tablename__ = "aplicaciones_pago"
    __table_args__ = (
        CheckConstraint("monto > 0", name="monto_positivo"),
        CheckConstraint(
            "(pedido_id IS NOT NULL AND orden_id IS NULL)"
            " OR (pedido_id IS NULL AND orden_id IS NOT NULL)",
            name="un_solo_documento",
        ),
        UniqueConstraint("pago_id", "pedido_id"),
        UniqueConstraint("pago_id", "orden_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pago_id: Mapped[int] = mapped_column(ForeignKey("pagos.id"), index=True)
    pedido_id: Mapped[int | None] = mapped_column(ForeignKey("pedidos_cliente.id"), index=True)
    orden_id: Mapped[int | None] = mapped_column(ForeignKey("ordenes_compra.id"), index=True)
    monto: Mapped[Decimal] = mapped_column(DecimalFijo(2))

    pago: Mapped[Pago] = relationship(back_populates="aplicaciones")
    pedido: Mapped["PedidoCliente | None"] = relationship(back_populates="aplicaciones")
    orden: Mapped["OrdenCompra | None"] = relationship(back_populates="aplicaciones")