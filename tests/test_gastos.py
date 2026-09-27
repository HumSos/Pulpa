from datetime import date, datetime
from decimal import Decimal

import pytest

from app.modelos import EstadoPedido, Producto, Unidad
from app.servicios.catalogo import margenes_vigentes, registrar_precio
from app.servicios.clientes import DatosCliente, crear_cliente
from app.servicios.errores import DatoInvalidoError
from app.servicios.gastos import DatosGasto, por_categoria, registrar, total
from app.servicios.kpis import Periodo, resumen
from app.servicios.pedidos import LineaNueva, cambiar_estado, crear_pedido
from app.servicios.proveedores import DatosProveedor, agregar_suministro, crear_proveedor

ENERO = datetime(2026, 1, 1)
FEBRERO = Periodo(date(2026, 2, 1), date(2026, 2, 28))


@pytest.fixture
def datos(db):
    kg = Unidad(clave="kg", nombre="Kilogramo", permite_decimales=True)
    bulto = Unidad(clave="bulto", nombre="Bulto")
    mango = Producto(codigo="PUL-001", descripcion="Pulpa de mango", unidad=kg)
    db.add_all([mango, bulto])
    db.flush()
    registrar_precio(db, mango.id, Decimal("100.00"), ENERO)
    cliente = crear_cliente(db, DatosCliente("Jugos Doña Mary"))
    proveedor = crear_proveedor(db, DatosProveedor("Frutas del Norte"))
    suministro = agregar_suministro(
        db, proveedor.id, mango.id, bulto.id, Decimal("25"), costo=Decimal("1875")
    )
    return {"mango": mango, "cliente": cliente, "proveedor": proveedor, "suministro": suministro}


def test_el_monto_debe_ser_positivo(db):
    with pytest.raises(DatoInvalidoError, match="mayor a cero"):
        registrar(db, DatosGasto("Gasolina", "Carga", Decimal("0")))


def test_la_categoria_es_obligatoria(db):
    with pytest.raises(DatoInvalidoError, match="categoría"):
        registrar(db, DatosGasto("  ", "Carga", Decimal("400")))


def test_totales_y_agrupacion_por_categoria(db):
    registrar(db, DatosGasto("Gasolina", "Ruta Saltillo", Decimal("400"), date(2026, 2, 5)))
    registrar(db, DatosGasto("Gasolina", "Ruta Monterrey", Decimal("350"), date(2026, 2, 12)))
    registrar(db, DatosGasto("Flete", "Envío foráneo", Decimal("900"), date(2026, 2, 20)))
    registrar(db, DatosGasto("Gasolina", "Fuera de rango", Decimal("999"), date(2026, 3, 2)))

    assert total(db, date(2026, 2, 1), date(2026, 2, 28)) == Decimal("1650.00")
    assert por_categoria(db, date(2026, 2, 1), date(2026, 2, 28)) == [
        ("Flete", Decimal("900.00")),
        ("Gasolina", Decimal("750.00")),
    ]


def test_la_utilidad_descuenta_los_gastos(db, datos):
    pedido = crear_pedido(
        db,
        datos["cliente"].id,
        [LineaNueva(datos["mango"].id, Decimal("10"))],
        fecha_pedido=datetime(2026, 2, 10),
    )
    cambiar_estado(db, pedido.id, EstadoPedido.CONFIRMADO)
    registrar(db, DatosGasto("Gasolina", "Ruta", Decimal("400"), date(2026, 2, 11)))

    kpis = resumen(db, FEBRERO)
    assert kpis["ventas"] == Decimal("1000.00")
    assert kpis["gastos"] == Decimal("400.00")
    assert kpis["utilidad"] == Decimal("600.00")


def test_el_margen_convierte_el_costo_a_unidad_de_venta(db, datos):
    """El bulto cuesta 1875 y trae 25 kg, así que el costo por kg es 75."""
    margenes = margenes_vigentes(db, [datos["mango"].id])
    assert margenes == {}  # sin proveedor preferido no hay margen

    datos["suministro"].es_preferido = True
    db.flush()

    margen = margenes_vigentes(db, [datos["mango"].id])[datos["mango"].id]
    assert margen["costo"] == Decimal("75.0000")
    assert margen["margen"] == Decimal("25.0000")
    assert margen["pct"] == Decimal("25.0")


def test_captura_desde_la_pantalla(client, db):
    respuesta = client.post(
        "/gastos",
        data={
            "categoria": "Gasolina",
            "concepto": "Carga camioneta",
            "monto": "450.50",
            "fecha": "",
            "metodo": "efectivo",
            "proveedor_id": "",
        },
        headers={"HX-Request": "true"},
    )
    assert respuesta.status_code == 200
    assert "$450.50" in respuesta.text
    assert "Carga camioneta" in respuesta.text