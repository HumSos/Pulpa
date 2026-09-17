from decimal import Decimal

import pytest

from app.modelos import Producto, Unidad
from app.servicios.catalogo import registrar_precio
from app.servicios.clientes import (
    DatosCliente,
    actualizar_cliente,
    agregar_direccion,
    crear_cliente,
    desactivar_direccion,
)
from app.servicios.errores import DatoInvalidoError
from app.servicios.pedidos import LineaNueva, crear_pedido


def test_nombre_duplicado_ignora_mayusculas_y_espacios(db):
    crear_cliente(db, DatosCliente("Jugos Doña Mary"))
    with pytest.raises(DatoInvalidoError, match="Ya existe"):
        crear_cliente(db, DatosCliente("  JUGOS   DOÑA mary "))


def test_actualizar_conservando_su_propio_nombre(db):
    cliente = crear_cliente(db, DatosCliente("Frutería El Sol"))
    actualizar_cliente(
        db, cliente.id, DatosCliente("Frutería El Sol", telefono="5551234567", dias_credito=30)
    )
    assert (cliente.telefono, cliente.dias_credito) == ("5551234567", 30)


def test_dias_de_credito_fuera_de_rango(db):
    with pytest.raises(DatoInvalidoError, match="días de crédito"):
        crear_cliente(db, DatosCliente("Cafetería Luna", dias_credito=-1))


def test_pedido_no_acepta_direccion_desactivada(db):
    kg = Unidad(clave="kg", nombre="Kilogramo", permite_decimales=True)
    producto = Producto(codigo="PUL-001", descripcion="Pulpa de mango", unidad=kg)
    db.add(producto)
    db.flush()
    registrar_precio(db, producto.id, Decimal("45"))

    cliente = crear_cliente(db, DatosCliente("Jugos Doña Mary"))
    direccion = agregar_direccion(db, cliente.id, "Bodega", "Av. Norte 200")
    desactivar_direccion(db, cliente.id, direccion.id)

    with pytest.raises(DatoInvalidoError, match="dirección"):
        crear_pedido(
            db,
            cliente.id,
            [LineaNueva(producto.id, Decimal("1"))],
            direccion_entrega_id=direccion.id,
        )


def test_alta_por_formulario_y_error_de_edicion_en_fragmento(client):
    alta = client.post(
        "/clientes/nuevo",
        data={"nombre_negocio": "Paletería Polar", "dias_credito": "15"},
        follow_redirects=False,
    )
    assert alta.status_code == 303

    edicion = client.post(
        alta.headers["location"],
        data={"nombre_negocio": "Paletería Polar", "dias_credito": "abc"},
        headers={"HX-Request": "true"},
    )
    assert edicion.status_code == 200
    assert "número entero" in edicion.text