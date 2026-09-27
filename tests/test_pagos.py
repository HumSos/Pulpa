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
    aplicar,
    cobro_de_pedido,
    pago_de_orden,
    pedidos_pendientes,
    quitar_aplicacion,
    quitar_cobro,
    quitar_pago,
    registrar_cobro,
    registrar_pago,
    saldo_a_favor_cliente,
)
from app.servicios.pedidos import LineaNueva, crear_pedido
from app.servicios.pedidos import cambiar_estado as cambiar_estado_pedido
from app.servicios.proveedores import DatosProveedor, agregar_suministro, crear_proveedor

ENERO = datetime(2026, 1, 1)


@pytest.fixture
def datos(db):
    kg = Unidad(clave="kg", nombre="Kilogramo", permite_decimales=True)
    bulto = Unidad(clave="bulto", nombre="Bulto")
    mango = Producto(codigo="PUL-001", descripcion="Pulpa de mango", unidad=kg)
    db.add_all([mango, bulto])
    db.flush()
    registrar_precio(db, mango.id, Decimal("100.00"), ENERO)

    cliente = crear_cliente(db, DatosCliente("Jugos Doña Mary", dias_credito=15))
    otro = crear_cliente(db, DatosCliente("Paletería Polar"))
    proveedor = crear_proveedor(db, DatosProveedor("Frutas del Norte", dias_credito=30))
    agregar_suministro(db, proveedor.id, mango.id, bulto.id, Decimal("25"), costo=Decimal("900"))
    return {"mango": mango, "cliente": cliente, "otro": otro, "proveedor": proveedor}


def _pedido(db, datos, cantidad, dia, cliente=None):
    pedido = crear_pedido(
        db,
        (cliente or datos["cliente"]).id,
        [LineaNueva(datos["mango"].id, Decimal(cantidad))],
        fecha_pedido=datetime(2026, 2, dia, 9, 0),
    )
    cambiar_estado_pedido(db, pedido.id, EstadoPedido.CONFIRMADO)
    return pedido


def test_un_cobro_salda_varias_notas_en_orden(db, datos):
    a = _pedido(db, datos, "3", 5)   # 300
    b = _pedido(db, datos, "5", 8)   # 500
    c = _pedido(db, datos, "4", 12)  # 400

    registrar_cobro(db, datos["cliente"].id, "1000", fecha=date(2026, 2, 15))

    assert (a.saldo, b.saldo, c.saldo) == (Decimal("0.00"), Decimal("0.00"), Decimal("200.00"))


def test_reparto_manual_respeta_lo_indicado(db, datos):
    a = _pedido(db, datos, "3", 5)
    b = _pedido(db, datos, "5", 8)

    registrar_cobro(
        db,
        datos["cliente"].id,
        "500",
        fecha=date(2026, 2, 15),
        reparto=[(b.id, Decimal("500"))],
    )

    assert (a.saldo, b.saldo) == (Decimal("300.00"), Decimal("0.00"))


def test_lo_no_aplicado_queda_como_saldo_a_favor(db, datos):
    pedido = _pedido(db, datos, "3", 5)
    pago = registrar_cobro(db, datos["cliente"].id, "500", fecha=date(2026, 2, 15))

    assert pedido.saldo == Decimal("0.00")
    assert pago.disponible == Decimal("200.00")
    assert saldo_a_favor_cliente(db, datos["cliente"].id) == Decimal("200.00")


def test_el_saldo_a_favor_se_aplica_despues(db, datos):
    pago = registrar_cobro(db, datos["cliente"].id, "500", fecha=date(2026, 2, 1))
    assert pago.disponible == Decimal("500.00")

    nuevo = _pedido(db, datos, "3", 5)
    aplicar(db, pago.id, nuevo.id, Decimal("300"))

    assert nuevo.saldo == Decimal("0.00")
    assert pago.disponible == Decimal("200.00")


def test_no_se_aplica_mas_de_lo_disponible(db, datos):
    pedido_a = _pedido(db, datos, "3", 5)
    pedido_b = _pedido(db, datos, "5", 8)
    pago = registrar_cobro(
        db,
        datos["cliente"].id,
        "300",
        fecha=date(2026, 2, 15),
        reparto=[(pedido_a.id, Decimal("300"))],
    )

    with pytest.raises(DatoInvalidoError, match="disponible"):
        aplicar(db, pago.id, pedido_b.id, Decimal("100"))


def test_no_se_aplica_a_la_nota_de_otro_cliente(db, datos):
    ajeno = _pedido(db, datos, "3", 5, cliente=datos["otro"])
    pago = registrar_cobro(db, datos["cliente"].id, "300", fecha=date(2026, 2, 15))

    with pytest.raises(DatoInvalidoError, match="no pertenece"):
        aplicar(db, pago.id, ajeno.id, Decimal("100"))


def test_no_se_abona_dos_veces_el_mismo_pago_a_una_nota(db, datos):
    pedido = _pedido(db, datos, "10", 5)
    pago = registrar_cobro(
        db,
        datos["cliente"].id,
        "600",
        fecha=date(2026, 2, 15),
        reparto=[(pedido.id, Decimal("400"))],
    )

    with pytest.raises(DatoInvalidoError, match="ya tiene un abono"):
        aplicar(db, pago.id, pedido.id, Decimal("200"))


def test_cobro_de_una_sola_nota_y_su_borrado(db, datos):
    pedido = _pedido(db, datos, "10", 5)
    cobro_de_pedido(db, pedido.id, "400")
    assert pedido.saldo == Decimal("600.00")

    quitar_cobro(db, pedido.id, pedido.aplicaciones[0].id)
    assert pedido.saldo == Decimal("1000.00")
    assert pedido.aplicaciones == []


def test_no_se_borra_desde_la_nota_un_cobro_compartido(db, datos):
    a = _pedido(db, datos, "3", 5)
    _pedido(db, datos, "5", 8)
    registrar_cobro(db, datos["cliente"].id, "800", fecha=date(2026, 2, 15))

    with pytest.raises(DatoInvalidoError, match="varias notas"):
        quitar_cobro(db, a.id, a.aplicaciones[0].id)


def test_no_se_cobra_un_pedido_en_borrador(db, datos):
    borrador = crear_pedido(
        db,
        datos["cliente"].id,
        [LineaNueva(datos["mango"].id, Decimal("1"))],
        fecha_pedido=datetime(2026, 2, 10),
    )
    with pytest.raises(DatoInvalidoError, match="Confirma el pedido"):
        cobro_de_pedido(db, borrador.id, "10")


def test_antiguedad_usa_el_saldo_vivo(db, datos):
    pedido = _pedido(db, datos, "10", 10)  # vence 25/02
    registrar_cobro(db, datos["cliente"].id, "100", fecha=date(2026, 2, 11))

    tramos = antiguedad_saldos(db, al=date(2026, 3, 20))
    assert tramos["1-30"] == Decimal("900.00")
    assert pedido.saldo == Decimal("900.00")


def test_pago_a_proveedor_cubre_dos_ordenes(db, datos):
    ordenes = []
    for dia in (4, 6):
        orden = crear_orden(db, datos["proveedor"].id, fecha=datetime(2026, 2, dia))
        agregar_linea(db, orden.id, LineaCompra(datos["mango"].id, Decimal("1")))
        cambiar_estado(db, orden.id, EstadoCompra.ENVIADA)
        ordenes.append(orden)

    registrar_pago(db, datos["proveedor"].id, "1500", fecha=date(2026, 2, 10))

    assert ordenes[0].saldo == Decimal("0.00")
    assert ordenes[1].saldo == Decimal("300.00")


def test_pendientes_excluye_lo_saldado(db, datos):
    _pedido(db, datos, "3", 5)
    registrar_cobro(db, datos["cliente"].id, "300", fecha=date(2026, 2, 15))

    assert pedidos_pendientes(db, datos["cliente"].id) == []

def test_pago_de_una_sola_orden_y_su_borrado(db, datos):
    orden = crear_orden(db, datos["proveedor"].id, fecha=datetime(2026, 2, 4))
    agregar_linea(db, orden.id, LineaCompra(datos["mango"].id, Decimal("2")))
    cambiar_estado(db, orden.id, EstadoCompra.ENVIADA)

    pago_de_orden(db, orden.id, "800")
    assert orden.saldo == Decimal("1000.00")

    quitar_pago(db, orden.id, orden.aplicaciones[0].id)
    assert orden.saldo == Decimal("1800.00")
    assert orden.aplicaciones == []


def test_quitar_una_aplicacion_deja_el_resto_del_pago(db, datos):
    a = _pedido(db, datos, "3", 5)
    b = _pedido(db, datos, "5", 8)
    pago = registrar_cobro(db, datos["cliente"].id, "800", fecha=date(2026, 2, 15))

    quitar_aplicacion(db, a.aplicaciones[0].id)

    assert a.saldo == Decimal("300.00")
    assert b.saldo == Decimal("0.00")
    assert pago.disponible == Decimal("300.00")