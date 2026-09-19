"""Restaura un respaldo. Detén el servidor antes de ejecutarlo."""

import shutil
import sys
from datetime import datetime
from pathlib import Path

from scripts.respaldo import DESTINO, ruta_base


def main() -> None:
    if len(sys.argv) != 2:
        disponibles = sorted(DESTINO.glob("pulpa_*.db"), reverse=True)[:10]
        print("Uso: uv run python -m scripts.restaurar <archivo>\n")
        print("Respaldos disponibles:")
        for archivo in disponibles:
            print(f"  {archivo.name}")
        raise SystemExit(1)

    origen = Path(sys.argv[1])
    if not origen.exists():
        origen = DESTINO / sys.argv[1]
    if not origen.exists():
        raise SystemExit(f"No existe el respaldo {sys.argv[1]}")

    destino = ruta_base()
    if destino.exists():
        previa = destino.with_name(f"antes_de_restaurar_{datetime.now():%Y%m%d_%H%M}.db")
        shutil.copy2(destino, previa)
        print(f"La base actual se guardó como {previa.name}")

    for sufijo in ("-wal", "-shm"):
        residuo = destino.with_name(destino.name + sufijo)
        residuo.unlink(missing_ok=True)

    shutil.copy2(origen, destino)
    print(f"Restaurado desde {origen.name}")


if __name__ == "__main__":
    main()