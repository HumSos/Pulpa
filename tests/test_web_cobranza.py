from decimal import Decimal

import pytest

from app.modelos import Producto, Unidad
from app.servicios.catalogo import registrar_precio
from app.servicios.clientes import DatosCliente, crear_cliente


@pytest.fixture
def datos(db):
    kg = Unidad(clave="kg", nombre="Kilogramo", permite_decimales=True)
    mango = Producto(codigo="PUL-001", descripcion="Pulpa de mango", unidad=kg)
    db.add(mango)
    db.flush()
    registrar_precio(db, mango.id, Decimal("100.00"))
    cliente = crear_cliente(db, DatosCliente("Jugos Doña Mary", dias_credito=15))
    db.commit()
    return {"mango": mango, "cliente": cliente}


def _pedido_confirmado(client, datos, cantidad="10"):
    creado = client.post(
        "/pedidos/nuevo", data={"cliente_id": datos["cliente"].id}, follow_redirects=False
    )
    url = creado.headers["location"]
    client.post(f"{url}/lineas", data={"producto_id": datos["mango"].id, "cantidad": cantidad})
    client.post(f"{url}/estado", data={"estado": "confirmado"})
    return url


def test_cobro_parcial_actualiza_saldo_en_pantalla(client, datos):
    url = _pedido_confirmado(client, datos)

    respuesta = client.post(
        f"{url}/cobros",
        data={"monto": "400", "fecha": "", "metodo": "efectivo", "referencia": "REC-1"},
        headers={"HX-Request": "true"},
    )
    assert "Saldo $600.00" in respuesta.text

    excedido = client.post(
        f"{url}/cobros", data={"monto": "700"}, headers={"HX-Request": "true"}
    )
    assert "excede el saldo" in excedido.text


def test_el_resumen_lista_el_saldo_pendiente(client, datos):
    _pedido_confirmado(client, datos)
    resumen = client.get("/cobranza")

    assert "Jugos Doña Mary" in resumen.text
    assert "$1,000.00" in resumen.text


def test_un_pedido_pagado_sale_del_resumen(client, datos):
    url = _pedido_confirmado(client, datos)
    client.post(f"{url}/cobros", data={"monto": "1000"})

    resumen = client.get("/cobranza")
    assert "No hay saldos pendientes de cobro" in resumen.text