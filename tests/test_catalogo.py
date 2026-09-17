from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.modelos import Producto, Proveedor, ProveedorProducto, Unidad
from app.servicios.catalogo import (
    PrecioNoDefinidoError,
    marcar_preferido,
    precio_vigente,
    registrar_precio,
)


@pytest.fixture
def producto(db):
    kg = Unidad(clave="kg", nombre="Kilogramo", permite_decimales=True)
    p = Producto(codigo="PUL-001", descripcion="Pulpa de mango", unidad=kg)
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def dos_proveedores(db, producto):
    bulto = Unidad(clave="bulto", nombre="Bulto")
    relaciones = [
        ProveedorProducto(
            proveedor=Proveedor(nombre=nombre),
            producto=producto,
            unidad_compra=bulto,
            factor_conversion=Decimal("25"),
        )
        for nombre in ("Frutas del Norte", "Pulpas La Huerta")
    ]
    db.add_all(relaciones)
    db.flush()
    return relaciones


def test_precio_vigente_toma_el_ultimo_anterior_a_la_fecha(db, producto):
    registrar_precio(db, producto.id, Decimal("40.00"), datetime(2026, 1, 1))
    registrar_precio(db, producto.id, Decimal("45.50"), datetime(2026, 3, 1))

    assert precio_vigente(db, producto.id, en=datetime(2026, 2, 15)) == Decimal("40.00")
    assert precio_vigente(db, producto.id, en=datetime(2026, 3, 1)) == Decimal("45.50")


def test_precio_programado_no_aplica_antes_de_tiempo(db, producto):
    registrar_precio(db, producto.id, Decimal("40"), datetime(2026, 1, 1))
    registrar_precio(db, producto.id, Decimal("99"), datetime(2030, 1, 1))

    assert precio_vigente(db, producto.id, en=datetime(2026, 6, 1)) == Decimal("40")


def test_sin_precio_lanza_error(db, producto):
    with pytest.raises(PrecioNoDefinidoError):
        precio_vigente(db, producto.id)


def test_marcar_preferido_deja_solo_uno(db, dos_proveedores):
    a, b = dos_proveedores
    marcar_preferido(db, a.id)
    marcar_preferido(db, b.id)
    db.refresh(a)

    assert (a.es_preferido, b.es_preferido) == (False, True)


def test_la_base_impide_dos_preferidos(db, dos_proveedores):
    a, b = dos_proveedores
    a.es_preferido = True
    b.es_preferido = True

    with pytest.raises(IntegrityError):
        db.flush()