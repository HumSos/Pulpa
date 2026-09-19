from decimal import Decimal

import pytest

from app.modelos import Producto, ProveedorProducto, Unidad
from app.servicios.catalogo import costo_vigente
from app.servicios.errores import DatoInvalidoError
from app.servicios.proveedores import (
    DatosProveedor,
    agregar_suministro,
    crear_proveedor,
    quitar_suministro,
)


@pytest.fixture
def datos(db):
    kg = Unidad(clave="kg", nombre="Kilogramo", permite_decimales=True)
    bulto = Unidad(clave="bulto", nombre="Bulto")
    producto = Producto(codigo="PUL-001", descripcion="Pulpa de mango", unidad=kg)
    db.add_all([producto, bulto])
    db.flush()
    proveedor = crear_proveedor(db, DatosProveedor("Frutas del Norte", dias_credito=30))
    db.commit()
    return {"producto": producto, "bulto": bulto, "proveedor": proveedor}


def test_agregar_suministro_registra_costo(db, datos):
    suministro = agregar_suministro(
        db,
        datos["proveedor"].id,
        datos["producto"].id,
        datos["bulto"].id,
        Decimal("25"),
        costo=Decimal("900"),
    )
    assert costo_vigente(db, suministro.id) == Decimal("900")


def test_no_se_duplica_el_mismo_producto(db, datos):
    argumentos = (datos["proveedor"].id, datos["producto"].id, datos["bulto"].id, Decimal("25"))
    agregar_suministro(db, *argumentos)
    with pytest.raises(DatoInvalidoError, match="ya está en el catálogo"):
        agregar_suministro(db, *argumentos)


def test_reactivar_conserva_el_historial_de_costos(db, datos):
    suministro = agregar_suministro(
        db,
        datos["proveedor"].id,
        datos["producto"].id,
        datos["bulto"].id,
        Decimal("25"),
        costo=Decimal("900"),
    )
    identificador = suministro.id
    quitar_suministro(db, datos["proveedor"].id, identificador)

    nuevo = agregar_suministro(
        db, datos["proveedor"].id, datos["producto"].id, datos["bulto"].id, Decimal("20")
    )
    assert nuevo.id == identificador
    assert costo_vigente(db, identificador) == Decimal("900")


def test_quitar_suministro_retira_el_preferido(db, datos):
    suministro = agregar_suministro(
        db, datos["proveedor"].id, datos["producto"].id, datos["bulto"].id, Decimal("25")
    )
    suministro.es_preferido = True
    db.flush()

    quitar_suministro(db, datos["proveedor"].id, suministro.id)
    assert not suministro.es_preferido


def test_factor_cero_se_rechaza(db, datos):
    with pytest.raises(DatoInvalidoError, match="factor"):
        agregar_suministro(
            db, datos["proveedor"].id, datos["producto"].id, datos["bulto"].id, Decimal("0")
        )


def test_no_se_puede_tocar_el_suministro_de_otro_proveedor(client, db, datos):
    otro = crear_proveedor(db, DatosProveedor("Pulpas La Huerta"))
    suministro = agregar_suministro(
        db, datos["proveedor"].id, datos["producto"].id, datos["bulto"].id, Decimal("25")
    )
    db.commit()

    respuesta = client.post(
        f"/proveedores/{otro.id}/suministros/{suministro.id}/costo",
        data={"costo": "1"},
        headers={"HX-Request": "true"},
    )
    assert "no pertenece a este proveedor" in respuesta.text
    assert db.get(ProveedorProducto, suministro.id).proveedor_id == datos["proveedor"].id

def test_no_se_puede_preferir_el_suministro_de_otro_proveedor(client, db, datos):
    otro = crear_proveedor(db, DatosProveedor("Pulpas del Sur"))
    suministro = agregar_suministro(
        db, datos["proveedor"].id, datos["producto"].id, datos["bulto"].id, Decimal("25")
    )
    db.commit()

    respuesta = client.post(
        f"/proveedores/{otro.id}/suministros/{suministro.id}/preferido",
        headers={"HX-Request": "true"},
    )
    assert "no pertenece a este proveedor" in respuesta.text
    assert not db.get(ProveedorProducto, suministro.id).es_preferido