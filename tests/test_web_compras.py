from decimal import Decimal

import pytest

from app.modelos import EstadoCompra, OrdenCompra, Producto, Unidad
from app.servicios.proveedores import DatosProveedor, agregar_suministro, crear_proveedor


@pytest.fixture
def datos(db):
    kg = Unidad(clave="kg", nombre="Kilogramo", permite_decimales=True)
    bulto = Unidad(clave="bulto", nombre="Bulto")
    mango = Producto(codigo="PUL-001", descripcion="Pulpa de mango", unidad=kg)
    db.add_all([mango, bulto])
    db.flush()
    proveedor = crear_proveedor(db, DatosProveedor("Frutas del Norte", dias_credito=30))
    agregar_suministro(db, proveedor.id, mango.id, bulto.id, Decimal("25"), costo=Decimal("900"))
    db.commit()
    return {"proveedor": proveedor, "mango": mango}


def test_flujo_completo_de_compra(client, db, datos):
    creada = client.post(
        "/compras/nueva", data={"proveedor_id": datos["proveedor"].id}, follow_redirects=False
    )
    assert creada.status_code == 303
    url = creada.headers["location"]

    vacia = client.post(
        f"{url}/estado", data={"estado": "enviada"}, headers={"HX-Request": "true"}
    )
    assert "sin productos" in vacia.text

    agregada = client.post(
        f"{url}/lineas",
        data={"producto_id": datos["mango"].id, "cantidad": "3"},
        headers={"HX-Request": "true"},
    )
    assert "$2,700.00" in agregada.text

    client.post(f"{url}/estado", data={"estado": "enviada"})

    sin_remision = client.post(
        f"{url}/recibir", data={"numero_remision": ""}, headers={"HX-Request": "true"}
    )
    assert "remisión" in sin_remision.text

    recibida = client.post(
        f"{url}/recibir",
        data={"numero_remision": "R-4471", "fecha_recepcion": ""},
        headers={"HX-Request": "true"},
    )
    assert "Recibida" in recibida.text

    orden = db.get(OrdenCompra, int(url.rsplit("/", 1)[1]))
    assert orden.estado == EstadoCompra.RECIBIDA
    assert orden.numero_remision == "R-4471"


def test_una_orden_recibida_ya_no_muestra_captura(client, datos):
    creada = client.post(
        "/compras/nueva", data={"proveedor_id": datos["proveedor"].id}, follow_redirects=False
    )
    url = creada.headers["location"]
    client.post(f"{url}/lineas", data={"producto_id": datos["mango"].id, "cantidad": "1"})
    client.post(f"{url}/estado", data={"estado": "enviada"})
    client.post(f"{url}/recibir", data={"numero_remision": "R-1"})

    detalle = client.get(url)
    assert "Agregar" not in detalle.text
    assert "Recibir mercancía" not in detalle.text