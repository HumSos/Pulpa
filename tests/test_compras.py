from datetime import date, datetime
from decimal import Decimal

import pytest

from app.modelos import EstadoCompra, Producto, Unidad
from app.servicios.compras import (
    LineaCompra,
    TransicionInvalidaError,
    agregar_linea,
    cambiar_estado,
    crear_orden,
    recibir,
)
from app.servicios.errores import DatoInvalidoError
from app.servicios.proveedores import DatosProveedor, agregar_suministro, crear_proveedor


@pytest.fixture
def datos(db):
    kg = Unidad(clave="kg", nombre="Kilogramo", permite_decimales=True)
    bulto = Unidad(clave="bulto", nombre="Bulto")
    mango = Producto(codigo="PUL-001", descripcion="Pulpa de mango", unidad=kg)
    otro = Producto(codigo="PUL-999", descripcion="Pulpa de tamarindo", unidad=kg)
    db.add_all([mango, otro, bulto])
    db.flush()
    proveedor = crear_proveedor(db, DatosProveedor("Frutas del Norte", dias_credito=30))
    suministro = agregar_suministro(
        db, proveedor.id, mango.id, bulto.id, Decimal("25"), costo=Decimal("900")
    )
    return {"proveedor": proveedor, "mango": mango, "otro": otro, "suministro": suministro}


def test_la_linea_toma_costo_y_unidad_del_proveedor(db, datos):
    orden = crear_orden(db, datos["proveedor"].id)
    agregar_linea(db, orden.id, LineaCompra(datos["mango"].id, Decimal("3")))
    linea = orden.lineas[0]

    assert (linea.costo_unitario, linea.unidad_clave) == (Decimal("900"), "bulto")
    assert linea.importe == Decimal("2700.00")
    assert orden.total == Decimal("2700.00")


def test_no_acepta_productos_fuera_del_catalogo_del_proveedor(db, datos):
    orden = crear_orden(db, datos["proveedor"].id)
    with pytest.raises(DatoInvalidoError, match="no está en el catálogo"):
        agregar_linea(db, orden.id, LineaCompra(datos["otro"].id, Decimal("1")))


def test_bulto_no_admite_fracciones(db, datos):
    orden = crear_orden(db, datos["proveedor"].id)
    with pytest.raises(DatoInvalidoError, match="sin fracciones"):
        agregar_linea(db, orden.id, LineaCompra(datos["mango"].id, Decimal("1.5")))


def test_recibir_exige_remision_y_fija_vencimiento(db, datos):
    orden = crear_orden(db, datos["proveedor"].id, fecha=datetime(2026, 2, 10, 9, 0))
    agregar_linea(db, orden.id, LineaCompra(datos["mango"].id, Decimal("2")))
    cambiar_estado(db, orden.id, EstadoCompra.ENVIADA)

    with pytest.raises(DatoInvalidoError, match="remisión"):
        recibir(db, orden.id, date(2026, 2, 12))

    recibir(db, orden.id, date(2026, 2, 12), numero_remision="R-4471")
    assert orden.estado == EstadoCompra.RECIBIDA
    assert orden.fecha_vencimiento == date(2026, 3, 14)


def test_no_se_envia_una_orden_vacia(db, datos):
    orden = crear_orden(db, datos["proveedor"].id)
    with pytest.raises(DatoInvalidoError, match="sin productos"):
        cambiar_estado(db, orden.id, EstadoCompra.ENVIADA)


def test_una_orden_recibida_ya_no_se_edita(db, datos):
    orden = crear_orden(db, datos["proveedor"].id)
    agregar_linea(db, orden.id, LineaCompra(datos["mango"].id, Decimal("1")))
    cambiar_estado(db, orden.id, EstadoCompra.ENVIADA)
    recibir(db, orden.id, numero_remision="R-1")

    with pytest.raises(TransicionInvalidaError):
        agregar_linea(db, orden.id, LineaCompra(datos["mango"].id, Decimal("1")))