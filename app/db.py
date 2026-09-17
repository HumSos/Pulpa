from datetime import datetime
from pathlib import Path

from sqlalchemy import MetaData, create_engine, event, func
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import settings

url = make_url(settings.database_url)
es_sqlite = url.get_backend_name() == "sqlite"

if es_sqlite and url.database:
    Path(url.database).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(url, connect_args={"check_same_thread": False} if es_sqlite else {})

if es_sqlite:
    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

CONVENCION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCION)


class ConTiempos:
    creado_en: Mapped[datetime] = mapped_column(server_default=func.now())
    actualizado_en: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


def get_db():
    with SessionLocal() as db:
        yield db