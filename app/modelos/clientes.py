from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, ConTiempos


class Cliente(ConTiempos, Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre_negocio: Mapped[str] = mapped_column(String(150), index=True)
    nombre_contacto: Mapped[str | None] = mapped_column(String(150))
    telefono: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(150))
    direccion: Mapped[str | None] = mapped_column(String(300))
    dias_credito: Mapped[int] = mapped_column(default=0)
    activo: Mapped[bool] = mapped_column(default=True)

    direcciones_entrega: Mapped[list["DireccionEntrega"]] = relationship(back_populates="cliente")


class DireccionEntrega(ConTiempos, Base):
    __tablename__ = "direcciones_entrega"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    alias: Mapped[str] = mapped_column(String(60))
    direccion: Mapped[str] = mapped_column(String(300))
    referencia: Mapped[str | None] = mapped_column(String(300))
    activo: Mapped[bool] = mapped_column(default=True)

    cliente: Mapped[Cliente] = relationship(back_populates="direcciones_entrega")