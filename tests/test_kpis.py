from datetime import date, datetime
from decimal import Decimal

import pytest

from app.modelos import EstadoCompra, EstadoPedido, Producto, Unidad
from app.servicios.catalogo import registrar_precio
from app.servicios.clientes import DatosCliente, crear_cliente
from app.servicios.compras import LineaCompra, agregar_linea, cambiar_estado, crear_orden
from app.servicios.kpis import Periodo, resumen
from app.servicios.pagos import registrar_cobro
from app.servicios.pedidos import LineaNueva, crear_pedido
from app.servicios.pedidos import cambiar_estado as cambiar_estado_pedido
from app.servicios.proveedores import DatosProveedor, agregar_suministro, crear_proveedor

FEBRERO = Periodo(date(2026, 2, 1), date(2026, 2, 28))


@pytest.fixture
def datos(db):
    kg = Unidad(clave="kg", nombre="Kilogramo", permite_decimales=True)
    bulto = Unidad(clave="bulto", nombre="Bulto")
    mango = Producto(codigo="PUL-001", descripcion="Pulpa de mango", unidad=kg)
    db.add_all([mango, bulto])
    db.flush()
    registrar_precio(db, mango.id, Decimal("100.00"), datetime(2026, 1, 1))

    cliente = crear_cliente(db, DatosCliente("Jugos Doña Mary", dias_credito=15))
    proveedor = crear_proveedor(db, DatosProveedor("Frutas del Norte"))
    agregar_suministro(db, proveedor.id, mango.id, bulto.id, Decimal("25"), costo=Decimal("900"))
    return {"mango": mango, "cliente": cliente, "proveedor": proveedor}


def _vender(db, datos, cantidad, cuando, precio=None):
    pedido = crear_pedido(
        db,
        datos["cliente"].id,
        [LineaNueva(datos["mango"].id, Decimal(cantidad), precio)],
        fecha_pedido=cuando,
    )
    cambiar_estado_pedido(db, pedido.id, EstadoPedido.CONFIRMADO)
    return pedido


def test_resumen_suma_solo_pedidos_confirmados(db, datos):
    _vender(db, datos, "10", datetime(2026, 2, 5))
    crear_pedido(  # borrador, no debe contar
        db,
        datos["cliente"].id,
        [LineaNueva(datos["mango"].id, Decimal("50"))],
        fecha_pedido=datetime(2026, 2, 6),
    )

    datos_kpi = resumen(db, FEBRERO)
    assert datos_kpi["ventas"] == Decimal("1000.00")
    assert datos_kpi["pedidos"] == 1


def test_el_periodo_excluye_lo_de_afuera(db, datos):
    _vender(db, datos, "10", datetime(2026, 1, 31, 23, 0))
    _vender(db, datos, "3", datetime(2026, 2, 1, 0, 30))
    _vender(db, datos, "2", datetime(2026, 2, 28, 23, 59))
    _vender(db, datos, "20", datetime(2026, 3, 1, 0, 1))

    assert resumen(db, FEBRERO)["ventas"] == Decimal("500.00")


def test_margen_y_ticket_promedio(db, datos):
    _vender(db, datos, "10", datetime(2026, 2, 5))
    _vender(db, datos, "5", datetime(2026, 2, 6))

    orden = crear_orden(db, datos["proveedor"].id, fecha=datetime(2026, 2, 4))
    agregar_linea(db, orden.id, LineaCompra(datos["mango"].id, Decimal("1")))
    cambiar_estado(db, orden.id, EstadoCompra.ENVIADA)

    datos_kpi = resumen(db, FEBRERO)
    assert datos_kpi["compras"] == Decimal("900.00")
    assert datos_kpi["margen"] == Decimal("600.00")
    assert datos_kpi["ticket_promedio"] == Decimal("750.00")


def test_descuentos_y_cobros(db, datos):
    pedido = _vender(db, datos, "10", datetime(2026, 2, 5), precio=Decimal("90"))
    registrar_cobro(db, pedido.id, "400", fecha=date(2026, 2, 10))
    registrar_cobro(db, pedido.id, "200", fecha=date(2026, 3, 2))

    datos_kpi = resumen(db, FEBRERO)
    assert datos_kpi["descuentos"] == Decimal("100.00")
    assert datos_kpi["cobrado"] == Decimal("400.00")


def test_top_productos_y_ventas_por_dia(db, datos):
    _vender(db, datos, "10", datetime(2026, 2, 5))
    _vender(db, datos, "4", datetime(2026, 2, 5, 16, 0))
    _vender(db, datos, "1", datetime(2026, 2, 9))

    datos_kpi = resumen(db, FEBRERO)
    assert datos_kpi["top_productos"][0] == ("Pulpa de mango", Decimal("1500.00"))
    assert datos_kpi["top_clientes"][0][0] == "Jugos Doña Mary"
    assert datos_kpi["ventas_por_dia"] == [
        (date(2026, 2, 5), Decimal("1400.00")),
        (date(2026, 2, 9), Decimal("100.00")),
    ]


def test_el_tablero_responde(client, db, datos):
    _vender(db, datos, "10", datetime(2026, 2, 5))
    db.commit()

    respuesta = client.get("/?desde=2026-02-01&hasta=2026-02-28")
    assert respuesta.status_code == 200
    assert "$1,000.00" in respuesta.text

def test_los_descuentos_no_arrastran_la_escala_interna(db, datos):
    """Multiplicar columnas DecimalFijo en SQL daría un número escalado 10^7."""
    _vender(db, datos, "2.5", datetime(2026, 2, 7), precio=Decimal("99.9999"))

    descuentos = resumen(db, FEBRERO)["descuentos"]
    assert descuentos == Decimal("0.00")
    assert descuentos < Decimal("1000")