from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import BigInteger
from sqlalchemy.types import TypeDecorator


class DecimalFijo(TypeDecorator):
    """Guarda Decimal como entero escalado. Exacto en SQLite y en Postgres."""

    impl = BigInteger
    cache_ok = True

    def __init__(self, escala: int = 2):
        super().__init__()
        self.escala = escala

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        escalado = Decimal(str(value)).scaleb(self.escala)
        return int(escalado.to_integral_value(ROUND_HALF_UP))

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value).scaleb(-self.escala)