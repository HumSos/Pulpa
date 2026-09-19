from decimal import Decimal

import pytest

from app.modelos import Producto, Unidad
from app.servicios.catalogo import registrar_precio
from app.servicios.clientes import DatosCliente, crear_cliente


@pytest.fixture
def datos(db):
    kg = Unidad(clave="kg", nombre="Kilogramo", permite_decimales=True)
    producto = Producto(codigo="PUL-001", descripcion="Pulpa de mango", unidad=kg)
    db.add(producto)
    db.flush()
    registrar_precio(db, producto.id, Decimal("45.50"))
    cliente = crear_cliente(db, DatosCliente("Jugos Doña Mary", dias_credito=15))
    db.commit()
    return {"producto": producto, "cliente": cliente}


def test_flujo_completo_de_captura(client, datos):
    creado = client.post(
        "/pedidos/nuevo", data={"cliente_id": datos["cliente"].id}, follow_redirects=False
    )
    assert creado.status_code == 303
    url = creado.headers["location"]

    sin_lineas = client.post(
        f"{url}/estado", data={"estado": "confirmado"}, headers={"HX-Request": "true"}
    )
    assert "sin productos" in sin_lineas.text

    agregada = client.post(
        f"{url}/lineas",
        data={"producto_id": datos["producto"].id, "cantidad": "2.5"},
        headers={"HX-Request": "true"},
    )
    assert "$113.75" in agregada.text

    repetida = client.post(
        f"{url}/lineas",
        data={"producto_id": datos["producto"].id, "cantidad": "1"},
        headers={"HX-Request": "true"},
    )
    assert "ya está en el pedido" in repetida.text

    confirmado = client.post(
        f"{url}/estado", data={"estado": "confirmado"}, headers={"HX-Request": "true"}
    )
    assert "Confirmado" in confirmado.text
    assert "Agregar" not in confirmado.text


def test_no_se_puede_editar_un_pedido_confirmado(client, datos):
    creado = client.post(
        "/pedidos/nuevo", data={"cliente_id": datos["cliente"].id}, follow_redirects=False
    )
    url = creado.headers["location"]
    client.post(f"{url}/lineas", data={"producto_id": datos["producto"].id, "cantidad": "1"})
    client.post(f"{url}/estado", data={"estado": "confirmado"})

    respuesta = client.post(
        f"{url}/lineas",
        data={"producto_id": datos["producto"].id, "cantidad": "5"},
        headers={"HX-Request": "true"},
    )
    assert "borrador" in respuesta.text