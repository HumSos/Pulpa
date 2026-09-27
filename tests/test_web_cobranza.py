from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modelos import Pago, Producto, Unidad
from app.servicios.catalogo import registrar_precio
from app.servicios.clientes import DatosCliente, crear_cliente

ENERO = datetime(2026, 1, 1)


@pytest.fixture
def datos(db):
    kg = Unidad(clave="kg", nombre="Kilogramo", permite_decimales=True)
    mango = Producto(codigo="PUL-001", descripcion="Pulpa de mango", unidad=kg)
    db.add(mango)
    db.flush()
    registrar_precio(db, mango.id, Decimal("100.00"), ENERO)
    cliente = crear_cliente(db, DatosCliente("Jugos Doña Mary", dias_credito=15))
    db.commit()
    return {"mango": mango, "cliente": cliente}


def _pedido(client, datos, cantidad):
    creado = client.post(
        "/pedidos/nuevo", data={"cliente_id": datos["cliente"].id}, follow_redirects=False
    )
    url = creado.headers["location"]
    client.post(f"{url}/lineas", data={"producto_id": datos["mango"].id, "cantidad": cantidad})
    client.post(f"{url}/estado", data={"estado": "confirmado"})
    return url


def test_cobro_parcial_desde_el_pedido(client, datos):
    url = _pedido(client, datos, "10")

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


def test_un_cobro_reparte_entre_dos_notas(client, db, datos):
    primera = _pedido(client, datos, "3")
    segunda = _pedido(client, datos, "5")

    respuesta = client.post(
        "/cobranza/nuevo",
        data={
            "tipo": "cobro",
            "contraparte_id": datos["cliente"].id,
            "monto": "800",
            "fecha": "",
            "metodo": "transferencia",
        },
        headers={"HX-Request": "true"},
    )
    assert respuesta.status_code == 200
    assert "No hay saldos pendientes de cobro" in respuesta.text

    assert "$0.00" in client.get(primera).text
    assert "$0.00" in client.get(segunda).text


def test_reparto_manual_desde_el_formulario(client, db, datos):
    primera = _pedido(client, datos, "3")
    segunda = _pedido(client, datos, "5")
    id_segunda = int(segunda.rsplit("/", 1)[1])

    client.post(
        "/cobranza/nuevo",
        data={
            "tipo": "cobro",
            "contraparte_id": datos["cliente"].id,
            "monto": "500",
            "fecha": "",
            "metodo": "efectivo",
            f"abono_{id_segunda}": "500",
        },
        headers={"HX-Request": "true"},
    )

    assert "Saldo $300.00" in client.get(primera).text
    assert "Saldo $0.00" in client.get(segunda).text


def test_la_suma_de_abonos_no_puede_exceder_el_pago(client, datos):
    url = _pedido(client, datos, "5")
    identificador = int(url.rsplit("/", 1)[1])

    respuesta = client.post(
        "/cobranza/nuevo",
        data={
            "tipo": "cobro",
            "contraparte_id": datos["cliente"].id,
            "monto": "100",
            "fecha": "",
            "metodo": "efectivo",
            f"abono_{identificador}": "400",
        },
        headers={"HX-Request": "true"},
    )
    assert respuesta.status_code == 422
    assert "excede el monto" in respuesta.text


def test_saldo_a_favor_aparece_y_se_aplica(client, db, datos):
    client.post(
        "/cobranza/nuevo",
        data={
            "tipo": "cobro",
            "contraparte_id": datos["cliente"].id,
            "monto": "500",
            "fecha": "",
            "metodo": "efectivo",
        },
    )
    saldos = client.get("/cobranza/saldos-a-favor")
    assert "$500.00" in saldos.text

    url = _pedido(client, datos, "3")
    pago = db.scalars(select(Pago)).first()
    client.post(
        f"/cobranza/{pago.id}/aplicar",
        data={"documento_id": url.rsplit("/", 1)[1], "monto": "300"},
        headers={"HX-Request": "true"},
    )

    assert "Saldo $0.00" in client.get(url).text


def test_el_resumen_lista_movimientos(client, datos):
    _pedido(client, datos, "3")
    client.post(
        "/cobranza/nuevo",
        data={
            "tipo": "cobro",
            "contraparte_id": datos["cliente"].id,
            "monto": "300",
            "fecha": "",
            "metodo": "efectivo",
            "referencia": "TRANSF-99",
        },
    )

    resumen = client.get("/cobranza")
    assert "Jugos Doña Mary" in resumen.text
    assert "C-000001" in resumen.text