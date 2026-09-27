from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelos import Cliente, PedidoCliente, Producto


def _distintos(db: Session, columna) -> list[str]:
    valores = db.scalars(
        select(columna).where(columna.is_not(None)).distinct().order_by(columna)
    )
    return [valor for valor in valores if valor and valor.strip()]


def tipos_de_negocio(db: Session) -> list[str]:
    return _distintos(db, Cliente.tipo_negocio)


def plazas(db: Session) -> list[str]:
    return _distintos(db, Cliente.plaza)


def categorias(db: Session) -> list[str]:
    return _distintos(db, Producto.categoria)


def vendedores(db: Session) -> list[str]:
    return _distintos(db, PedidoCliente.vendedor)