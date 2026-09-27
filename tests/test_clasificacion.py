from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modelos import EstadoPedido, Producto, Unidad
from app.servicios.catalogo import crear_producto, registrar_precio
from app.servicios.clientes import DatosCliente, actualizar_cliente, crear_cliente
from app.servicios.errores import DatoInvalidoError
from app.servicios.kpis import Periodo, resumen
from app.servicios.pedidos import LineaNueva, cambiar_estado, crear_pedido
from app.servicios.sugerencias import plazas, tipos_de_negocio

ENERO = datetime(2026, 1, 1)
FEBRERO = Periodo(date(2026, 2, 1), date(2026, 2, 28))


@pytest.fixture
def base(db):
    kg = Unidad(clave="kg", nombre="Kilogramo", permite_decimales=True)
    db.add(kg)
    db.flush()
    pulpa = crear_producto(
        db, "CMANGOX18", "Cubeta mango", kg.id, categoria="Pulpa", familia="Mango"
    )
    frijol = crear_producto(db, "FPXB25KGM", "Bulto frijol", kg.id, categoria="Frijol")
    registrar_precio(db, pulpa.id, Decimal("1000"), ENERO)
    registrar_precio(db, frijol.id, Decimal("500"), ENERO)
    return {"unidad": kg, "pulpa": pulpa, "frijol": frijol}


def _vender(db, producto, cliente, cantidad, vendedor=None):
    pedido = crear_pedido(
        db,
        cliente.id,
        [LineaNueva(producto.id, Decimal(cantidad))],
        fecha_pedido=datetime(2026, 2, 10),
    )
    pedido.vendedor = vendedor
    cambiar_estado(db, pedido.id, EstadoPedido.CONFIRMADO)
    return pedido


def test_rfc_se_normaliza_a_mayusculas(db):
    cliente = crear_cliente(db, DatosCliente("Jugos Mary", rfc=" aear791212mm3 "))
    assert cliente.rfc == "AEAR791212MM3"


def test_rfc_invalido_se_rechaza(db):
    with pytest.raises(DatoInvalidoError, match="RFC"):
        crear_cliente(db, DatosCliente("Jugos Mary", rfc="12345"))


def test_sugerencias_sin_duplicados(db):
    crear_cliente(db, DatosCliente("A", tipo_negocio="Restaurante", plaza="Monterrey"))
    crear_cliente(db, DatosCliente("B", tipo_negocio="Restaurante", plaza="Saltillo"))
    crear_cliente(db, DatosCliente("C", plaza="Monterrey"))

    assert tipos_de_negocio(db) == ["Restaurante"]
    assert plazas(db) == ["Monterrey", "Saltillo"]


def test_ventas_agrupadas_por_plaza_categoria_y_vendedor(db, base):
    mty = crear_cliente(
        db, DatosCliente("Aguas El Sol", tipo_negocio="Aguas de sabor", plaza="Monterrey")
    )
    stl = crear_cliente(
        db, DatosCliente("Tortillería La Luz", tipo_negocio="Tortillería", plaza="Saltillo")
    )

    _vender(db, base["pulpa"], mty, "2", vendedor="GI")
    _vender(db, base["frijol"], stl, "3", vendedor="GI")
    _vender(db, base["frijol"], mty, "1")

    datos = resumen(db, FEBRERO)
    assert dict(datos["por_plaza"]) == {
        "Monterrey": Decimal("2500.00"),
        "Saltillo": Decimal("1500.00"),
    }
    assert dict(datos["por_categoria"]) == {
        "Pulpa": Decimal("2000.00"),
        "Frijol": Decimal("2000.00"),
    }
    assert dict(datos["por_vendedor"]) == {
        "GI": Decimal("3500.00"),
        "Sin clasificar": Decimal("500.00"),
    }
    assert dict(datos["por_tipo_negocio"])["Aguas de sabor"] == Decimal("2500.00")


def test_producto_sin_categoria_cae_en_sin_clasificar(db, base):
    suelto = Producto(codigo="X-1", descripcion="Sin categoría", unidad=base["unidad"])
    db.add(suelto)
    db.flush()
    registrar_precio(db, suelto.id, Decimal("100"), ENERO)

    cliente = crear_cliente(db, DatosCliente("Cliente Uno", plaza="Monterrey"))
    _vender(db, suelto, cliente, "1")

    por_categoria = dict(resumen(db, FEBRERO)["por_categoria"])
    assert por_categoria["Sin clasificar"] == Decimal("100.00")


def test_editar_cliente_conserva_clasificacion(db):
    cliente = crear_cliente(
        db, DatosCliente("Jugos Mary", tipo_negocio="Nevería", plaza="Saltillo")
    )
    actualizar_cliente(
        db,
        cliente.id,
        DatosCliente(
            "Jugos Mary", tipo_negocio="Nevería", plaza="Saltillo", dias_credito=30
        ),
    )
    assert (cliente.plaza, cliente.dias_credito) == ("Saltillo", 30)


def test_el_precio_inicial_del_alta_rige_desde_hoy(db):
    """Documenta por qué el fixture registra precios con fecha explícita."""
    kg = db.scalar(select(Unidad).where(Unidad.clave == "kg"))
    if kg is None:
        kg = Unidad(clave="kg", nombre="Kilogramo", permite_decimales=True)
        db.add(kg)
        db.flush()

    producto = crear_producto(db, "PZ-1", "Prueba", kg.id, Decimal("50"))
    cliente = crear_cliente(db, DatosCliente("Cliente Pasado"))

    with pytest.raises(DatoInvalidoError, match="no tiene precio vigente"):
        crear_pedido(
            db,
            cliente.id,
            [LineaNueva(producto.id, Decimal("1"))],
            fecha_pedido=datetime(2020, 1, 1),
        )