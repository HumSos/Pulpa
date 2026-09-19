"""Respaldo de la base de datos. Seguro de ejecutar con el sistema en uso."""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import BASE_DIR, settings

DESTINO = BASE_DIR / "respaldos"
CONSERVAR_DIAS = 30


def ruta_base() -> Path:
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        raise SystemExit("Este script solo respalda bases SQLite")
    return Path(url.database)


def respaldar() -> Path:
    origen = ruta_base()
    if not origen.exists():
        raise SystemExit(f"No se encontró la base en {origen}")

    DESTINO.mkdir(parents=True, exist_ok=True)
    archivo = DESTINO / f"pulpa_{datetime.now():%Y%m%d_%H%M}.db"

    with sqlite3.connect(f"file:{origen}?mode=ro", uri=True) as conexion:
        with sqlite3.connect(archivo) as copia:
            conexion.backup(copia)
    return archivo


def limpiar() -> int:
    limite = datetime.now().timestamp() - CONSERVAR_DIAS * 86400
    viejos = [a for a in DESTINO.glob("pulpa_*.db") if a.stat().st_mtime < limite]
    for archivo in viejos:
        archivo.unlink()
    return len(viejos)


def main() -> None:
    archivo = respaldar()
    borrados = limpiar()
    tamano = archivo.stat().st_size / 1024
    print(f"{datetime.now():%Y-%m-%d %H:%M} respaldo {archivo.name} ({tamano:.0f} KB)")
    if borrados:
        print(f"Se eliminaron {borrados} respaldos con más de {CONSERVAR_DIAS} días")
    if tamano < 1:
        print("ADVERTENCIA: el respaldo parece vacío, revisa la base", file=sys.stderr)


if __name__ == "__main__":
    main()