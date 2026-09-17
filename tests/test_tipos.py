from decimal import Decimal

from app.tipos import DecimalFijo


def test_redondeo_mitad_hacia_arriba():
    tipo = DecimalFijo(2)
    assert tipo.process_bind_param(Decimal("10.005"), None) == 1001


def test_ida_y_vuelta_conserva_escala():
    tipo = DecimalFijo(4)
    guardado = tipo.process_bind_param("12.3456", None)
    assert tipo.process_result_value(guardado, None) == Decimal("12.3456")


def test_float_no_arrastra_error_binario():
    tipo = DecimalFijo(2)
    assert tipo.process_bind_param(0.1 + 0.2, None) == 30