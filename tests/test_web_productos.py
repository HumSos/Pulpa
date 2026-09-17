from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modelos import Producto, Unidad
from app.servicios.catalogo import precio_vigente


@pytest.fixture
def kg(db):
    unidad = Unidad(clave="kg", nombre="Kilogramo", permite_decimales=True)
    db.add(unidad)
    db.commit()
    return unidad


def test_crear_producto_redirige_y_guarda_precio(client, db, kg):
    datos = {
        "codigo": "pul-010",
        "descripcion": "Pulpa de fresa",
        "unidad_id": kg.id,
        "precio": "1,250.50",
    }
    respuesta = client.post("/productos/nuevo", data=datos, follow_redirects=False)

    producto = db.scalar(select(Producto).where(Producto.codigo == "PUL-010"))
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == f"/productos/{producto.id}"
    assert precio_vigente(db, producto.id) == Decimal("1250.50")


def test_codigo_duplicado_muestra_error(client, kg):
    datos = {"codigo": "PUL-011", "descripcion": "Pulpa de guayaba", "unidad_id": kg.id}
    client.post("/productos/nuevo", data=datos)
    respuesta = client.post("/productos/nuevo", data=datos)

    assert respuesta.status_code == 422
    assert "Ya existe un producto" in respuesta.text


def test_precio_negativo_se_reporta_en_el_fragmento(client, db, kg):
    producto = Producto(codigo="PUL-012", descripcion="Pulpa de maracuyá", unidad=kg)
    db.add(producto)
    db.commit()

    respuesta = client.post(
        f"/productos/{producto.id}/precios", data={"precio": "-5"}, headers={"HX-Request": "true"}
    )

    assert respuesta.status_code == 200
    assert "no puede ser negativo" in respuesta.text