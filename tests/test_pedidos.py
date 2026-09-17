from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.modelos import Cliente, EstadoPedido, Producto, Unidad
from app.servicios.catalogo import DatoInvalidoError, registrar_precio
from app.servicios.pedidos import (
    LineaNueva,
    TransicionInvalidaError,
    cambiar_estado,
    crear_pedido,
    reemplazar_lineas,
)

FECHA = datetime(2026, 2, 10, 9, 0)


@pytest.fixture
def base(db):
    kg = Unidad(clave="kg", nombre="Kilogramo", permite_decimales=True)
    pza = Unidad(clave="pza", nombre="Pieza")
    mango = Producto(codigo="PUL-001", descripcion="Pulpa de mango", unidad=kg)
    guayaba = Producto(codigo="PUL-002", descripcion="Pulpa de guayaba 1 L", unidad=pza)
    cliente = Cliente(nombre_negocio="Jugos Doña Mary", direccion="Calle 1 #10", dias_credito=15)
    db.add_all([mango, guayaba, cliente])
    db.flush()
    registrar_precio(db, mango.id, Decimal("45.50"), datetime(2026, 1, 1))
    registrar_precio(db, guayaba.id, Decimal("38.00"), datetime(2026, 1, 1))
    return SimpleNamespace(mango=mango, guayaba=guayaba, cliente=cliente)


def test_toma_precio_vigente_y_calcula_totales(db, base):
    pedido = crear_pedido(
        db,
        base.cliente.id,
        [LineaNueva(base.mango.id, Decimal("2.5")), LineaNueva(base.guayaba.id, Decimal("4"))],
        fecha_pedido=FECHA,
    )

    assert [linea.importe for linea in pedido.lineas] == [Decimal("113.75"), Decimal("152.00")]
    assert pedido.total == Decimal("265.75")
    assert pedido.estado == EstadoPedido.BORRADOR


def test_cambio_de_precio_no_altera_pedidos_existentes(db, base):
    pedido = crear_pedido(
        db, base.cliente.id, [LineaNueva(base.mango.id, Decimal("1"))], fecha_pedido=FECHA
    )
    registrar_precio(db, base.mango.id, Decimal("50.00"), datetime(2026, 3, 1))
    db.expire_all()

    posterior = crear_pedido(
        db,
        base.cliente.id,
        [LineaNueva(base.mango.id, Decimal("1"))],
        fecha_pedido=datetime(2026, 3, 5),
    )

    assert pedido.lineas[0].precio_unitario == Decimal("45.50")
    assert posterior.lineas[0].precio_unitario == Decimal("50.00")


def test_precio_negociado_conserva_precio_de_lista(db, base):
    pedido = crear_pedido(
        db,
        base.cliente.id,
        [LineaNueva(base.mango.id, Decimal("10"), precio_unitario=Decimal("42"))],
        fecha_pedido=FECHA,
    )
    linea = pedido.lineas[0]

    assert (linea.precio_unitario, linea.precio_lista) == (Decimal("42"), Decimal("45.50"))
    assert linea.precio_modificado


def test_importe_redondea_mitad_hacia_arriba(db, base):
    pedido = crear_pedido(
        db, base.cliente.id, [LineaNueva(base.mango.id, Decimal("0.125"))], fecha_pedido=FECHA
    )
    assert pedido.lineas[0].importe == Decimal("5.69")


def test_pieza_no_admite_fracciones(db, base):
    with pytest.raises(DatoInvalidoError, match="sin fracciones"):
        crear_pedido(db, base.cliente.id, [LineaNueva(base.guayaba.id, Decimal("1.5"))])


def test_vencimiento_suma_dias_de_credito_a_la_entrega(db, base):
    pedido = crear_pedido(
        db,
        base.cliente.id,
        [LineaNueva(base.mango.id, Decimal("1"))],
        fecha_pedido=FECHA,
        fecha_entrega=date(2026, 2, 12),
    )
    assert pedido.fecha_vencimiento == date(2026, 2, 27)


def test_transiciones_de_estado(db, base):
    pedido = crear_pedido(
        db, base.cliente.id, [LineaNueva(base.mango.id, Decimal("1"))], fecha_pedido=FECHA
    )

    with pytest.raises(TransicionInvalidaError):
        cambiar_estado(db, pedido.id, EstadoPedido.ENTREGADO)

    cambiar_estado(db, pedido.id, EstadoPedido.CONFIRMADO)
    cambiar_estado(db, pedido.id, "entregado")

    with pytest.raises(TransicionInvalidaError):
        cambiar_estado(db, pedido.id, EstadoPedido.CANCELADO)


def test_reemplazar_lineas_con_el_mismo_producto(db, base):
    pedido = crear_pedido(
        db, base.cliente.id, [LineaNueva(base.mango.id, Decimal("1"))], fecha_pedido=FECHA
    )

    try:
        reemplazar_lineas(db, pedido.id, [LineaNueva(base.mango.id, Decimal("3"))])
    except IntegrityError:
        pytest.fail("Reemplazar las líneas chocó con el UniqueConstraint")

    assert len(pedido.lineas) == 1
    assert pedido.lineas[0].cantidad == Decimal("3")