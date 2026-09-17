from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, ConTiempos
from app.modelos.catalogo import Producto
from app.modelos.clientes import Cliente, DireccionEntrega
from app.tipos import DecimalFijo


class EstadoPedido(StrEnum):
    BORRADOR = "borrador"
    CONFIRMADO = "confirmado"
    ENTREGADO = "entregado"
    CANCELADO = "cancelado"


class PedidoCliente(ConTiempos, Base):
    __tablename__ = "pedidos_cliente"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    direccion_entrega_id: Mapped[int | None] = mapped_column(
        ForeignKey("direcciones_entrega.id")
    )
    direccion_entrega: Mapped[str | None] = mapped_column(String(300))
    referencia_cliente: Mapped[str | None] = mapped_column(String(50))
    fecha_pedido: Mapped[datetime] = mapped_column(index=True)
    fecha_entrega: Mapped[date | None]
    dias_credito: Mapped[int] = mapped_column(default=0)
    estado: Mapped[EstadoPedido] = mapped_column(
        Enum(
            EstadoPedido,
            native_enum=False,
            length=20,
            values_callable=lambda enum: [m.value for m in enum],
        ),
        default=EstadoPedido.BORRADOR,
        index=True,
    )
    notas: Mapped[str | None] = mapped_column(String(500))

    cliente: Mapped[Cliente] = relationship()
    direccion: Mapped[DireccionEntrega | None] = relationship()
    lineas: Mapped[list["PedidoClienteLinea"]] = relationship(
        back_populates="pedido",
        cascade="all, delete-orphan",
        order_by="PedidoClienteLinea.id",
    )

    @property
    def folio(self) -> str:
        return f"P-{self.id:06d}" if self.id else "P-nuevo"

    @property
    def total(self) -> Decimal:
        return sum((linea.importe for linea in self.lineas), Decimal("0.00"))

    @property
    def fecha_vencimiento(self) -> date:
        base = self.fecha_entrega or self.fecha_pedido.date()
        return base + timedelta(days=self.dias_credito)


class PedidoClienteLinea(ConTiempos, Base):
    __tablename__ = "pedido_cliente_lineas"
    __table_args__ = (
        UniqueConstraint("pedido_id", "producto_id"),
        CheckConstraint("cantidad > 0", name="cantidad_positiva"),
        CheckConstraint("precio_unitario >= 0", name="precio_no_negativo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos_cliente.id"), index=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), index=True)
    descripcion: Mapped[str] = mapped_column(String(200))
    unidad_clave: Mapped[str] = mapped_column(String(20))
    cantidad: Mapped[Decimal] = mapped_column(DecimalFijo(3))
    precio_lista: Mapped[Decimal | None] = mapped_column(DecimalFijo(4))
    precio_unitario: Mapped[Decimal] = mapped_column(DecimalFijo(4))
    importe: Mapped[Decimal] = mapped_column(DecimalFijo(2))

    pedido: Mapped[PedidoCliente] = relationship(back_populates="lineas")
    producto: Mapped[Producto] = relationship()

    @property
    def precio_modificado(self) -> bool:
        return self.precio_lista is not None and self.precio_unitario != self.precio_lista