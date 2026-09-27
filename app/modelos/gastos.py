from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, ConTiempos
from app.modelos.pagos import MetodoPago, _enum
from app.modelos.proveedores import Proveedor
from app.tipos import DecimalFijo


class Gasto(ConTiempos, Base):
    """Salidas de dinero que no son compra de mercancía."""

    __tablename__ = "gastos"
    __table_args__ = (CheckConstraint("monto > 0", name="monto_positivo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[date] = mapped_column(index=True)
    categoria: Mapped[str] = mapped_column(String(40), index=True)
    concepto: Mapped[str] = mapped_column(String(200))
    monto: Mapped[Decimal] = mapped_column(DecimalFijo(2))
    metodo: Mapped[MetodoPago] = mapped_column(_enum(MetodoPago), default=MetodoPago.EFECTIVO)
    proveedor_id: Mapped[int | None] = mapped_column(ForeignKey("proveedores.id"))
    referencia: Mapped[str | None] = mapped_column(String(80))
    notas: Mapped[str | None] = mapped_column(String(300))

    proveedor: Mapped[Proveedor | None] = relationship()