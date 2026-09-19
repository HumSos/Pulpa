from datetime import date, datetime
from decimal import Decimal

import pytest

from app.modelos import EstadoCompra, EstadoPedido, Producto, Unidad
from app.servicios.catalogo import registrar_precio
from app.servicios.clientes import DatosCliente, crear_cliente
from app.servicios.compras import LineaCompra, agregar_linea, cambiar_estado, crear_orden
from app.servicios.errores import DatoInvalidoError
from app.servicios.pagos import (
    antiguedad_saldos,
    cuentas_por_cobrar,
    cuentas_por_pagar,
    eliminar_cobro,
    registrar_cobro,
    registrar_pago,
)
from app.servicios.pedidos import LineaNueva, crear_pedido
from app.servicios.pedidos import cambiar_estado as cambiar_estado_pedido
from app.servicios.proveedores import DatosProveedor, agregar_suministro, crear_proveedor

FECHA = datetime(2026, 2, 10, 9, 0)


@pytest.fixture
def datos(db):
    kg = Unidad(clave="kg", nombre="Kilogramo", permite_decimales=True)
    bulto = Unidad(clave="bulto", nombre="Bulto")
    mango = Producto(codigo="PUL-001", descripcion="Pulpa de mango", unidad=kg)
    db.add_all([mango, bulto])
    db.flush()
    registrar_precio(db, mango.id, Decimal("100.00"), datetime(2026, 1, 1))

    cliente = crear_cliente(db, DatosCliente("Jugos Doña Mary", dias_credito=15))
    proveedor = crear_proveedor(db, DatosProveedor("Frutas del Norte", dias_credito=30))
    agregar_suministro(db, proveedor.id, mango.id, bulto.id, Decimal("25"), costo=Decimal("900"))
    return {"mango": mango, "cliente": cliente, "proveedor": proveedor}


@pytest.fixture
def pedido(db, datos):
    pedido = crear_pedido(
        db,
        datos["cliente"].id,
        [LineaNueva(datos["mango"].id, Decimal("10"))],
        fecha_pedido=FECHA,
    )
    cambiar_estado_pedido(db, pedido.id, EstadoPedido.CONFIRMADO)
    return pedido


def test_abonos_parciales_reducen_el_saldo(db, pedido):
    assert pedido.total == Decimal("1000.00")

    registrar_cobro(db, pedido.id, "400", fecha=date(2026, 2, 11))
    assert pedido.saldo == Decimal("600.00")

    registrar_cobro(db, pedido.id, "600", fecha=date(2026, 2, 20))
    assert pedido.saldo == Decimal("0.00")
    assert cuentas_por_cobrar(db) == []


def test_no_se_puede_cobrar_mas_del_saldo(db, pedido):
    registrar_cobro(db, pedido.id, "900", fecha=date(2026, 2, 11))
    with pytest.raises(DatoInvalidoError, match="excede el saldo"):
        registrar_cobro(db, pedido.id, "200", fecha=date(2026, 2, 12))


def test_no_se_cobra_un_pedido_en_borrador(db, datos):
    borrador = crear_pedido(
        db, datos["cliente"].id, [LineaNueva(datos["mango"].id, Decimal("1"))], fecha_pedido=FECHA
    )
    with pytest.raises(DatoInvalidoError, match="Confirma el pedido"):
        registrar_cobro(db, borrador.id, "10", fecha=date(2026, 2, 11))


def test_eliminar_cobro_devuelve_el_saldo(db, pedido):
    cobro = registrar_cobro(db, pedido.id, "250", fecha=date(2026, 2, 11))
    assert pedido.saldo == Decimal("750.00")

    eliminar_cobro(db, pedido.id, cobro.id)
    assert pedido.saldo == Decimal("1000.00")
    assert pedido.cobros == []


def test_antiguedad_clasifica_por_dias_vencidos(db, pedido):
    registrar_cobro(db, pedido.id, "100", fecha=date(2026, 2, 11))
    # vence el 25/02/2026 (pedido 10/02 + 15 días de crédito)
    tramos = antiguedad_saldos(db, al=date(2026, 3, 20))

    assert tramos["1-30"] == Decimal("900.00")
    assert tramos["Por vencer"] == Decimal("0.00")


def test_pagos_a_proveedor(db, datos):
    orden = crear_orden(db, datos["proveedor"].id, fecha=FECHA)
    agregar_linea(db, orden.id, LineaCompra(datos["mango"].id, Decimal("2")))
    cambiar_estado(db, orden.id, EstadoCompra.ENVIADA)

    assert orden.total == Decimal("1800.00")
    registrar_pago(db, orden.id, "1000", fecha=date(2026, 2, 11))
    assert orden.saldo == Decimal("800.00")
    assert len(cuentas_por_pagar(db)) == 1

    registrar_pago(db, orden.id, "800", fecha=date(2026, 2, 15))
    assert cuentas_por_pagar(db) == []


def test_no_se_paga_una_orden_en_borrador(db, datos):
    orden = crear_orden(db, datos["proveedor"].id, fecha=FECHA)
    agregar_linea(db, orden.id, LineaCompra(datos["mango"].id, Decimal("1")))
    with pytest.raises(DatoInvalidoError, match="Envía la orden"):
        registrar_pago(db, orden.id, "100", fecha=date(2026, 2, 11))