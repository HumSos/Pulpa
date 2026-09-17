from decimal import Decimal
from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def dinero(valor: Decimal | None) -> str:
    """$1,250.50 y hasta 4 decimales solo si el valor los tiene."""
    if valor is None:
        return "-"
    exponente = valor.normalize().as_tuple().exponent
    decimales = min(4, max(2, -exponente)) if isinstance(exponente, int) else 2
    return f"${valor:,.{decimales}f}"


templates.env.filters["dinero"] = dinero