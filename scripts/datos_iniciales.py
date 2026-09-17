from sqlalchemy import select

from app.db import SessionLocal
from app.modelos import Unidad

UNIDADES = [
    ("kg", "Kilogramo", True),
    ("l", "Litro", True),
    ("pza", "Pieza", False),
    ("bulto", "Bulto", False),
    ("caja", "Caja", False),
]


def main() -> None:
    with SessionLocal() as db:
        existentes = set(db.scalars(select(Unidad.clave)))
        nuevas = [
            Unidad(clave=clave, nombre=nombre, permite_decimales=decimales)
            for clave, nombre, decimales in UNIDADES
            if clave not in existentes
        ]
        db.add_all(nuevas)
        db.commit()
    print(f"Unidades agregadas: {len(nuevas)}")


if __name__ == "__main__":
    main()