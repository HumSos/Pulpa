from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.servicios.errores import DatoInvalidoError


def leer_decimal(texto: str) -> Decimal | None:
    texto = texto.strip().replace(",", "")
    if not texto:
        return None
    try:
        return Decimal(texto)
    except InvalidOperation as exc:
        raise DatoInvalidoError(f"'{texto}' no es un número válido") from exc


def leer_fecha(texto: str) -> datetime | None:
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto)
    except ValueError as exc:
        raise DatoInvalidoError("La fecha no es válida") from exc


def leer_entero(texto: str, nombre: str) -> int | None:
    texto = texto.strip()
    if not texto:
        return None
    try:
        return int(texto)
    except ValueError as exc:
        raise DatoInvalidoError(f"{nombre} debe ser un número entero") from exc