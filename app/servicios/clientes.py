from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modelos import Cliente, DireccionEntrega
from app.servicios.errores import DatoInvalidoError

MAX_DIAS_CREDITO = 180


@dataclass(frozen=True)
class DatosCliente:
    nombre_negocio: str
    nombre_contacto: str | None = None
    telefono: str | None = None
    email: str | None = None
    direccion: str | None = None
    dias_credito: int = 0


def _limpio(texto: str | None) -> str | None:
    texto = " ".join((texto or "").split())
    return texto or None


def _normalizar(db: Session, datos: DatosCliente, excluir_id: int | None = None) -> dict:
    nombre = _limpio(datos.nombre_negocio)
    if nombre is None:
        raise DatoInvalidoError("El nombre del negocio es obligatorio")
    if not 0 <= datos.dias_credito <= MAX_DIAS_CREDITO:
        raise DatoInvalidoError(f"Los días de crédito deben estar entre 0 y {MAX_DIAS_CREDITO}")
    email = _limpio(datos.email)
    if email and ("@" not in email or " " in email):
        raise DatoInvalidoError("El correo no parece válido")

    clave = nombre.casefold()
    existentes = db.execute(select(Cliente.id, Cliente.nombre_negocio))
    if any(n.casefold() == clave and i != excluir_id for i, n in existentes):
        raise DatoInvalidoError(f"Ya existe un cliente llamado {nombre}")

    return {
        "nombre_negocio": nombre,
        "nombre_contacto": _limpio(datos.nombre_contacto),
        "telefono": _limpio(datos.telefono),
        "email": email.lower() if email else None,
        "direccion": _limpio(datos.direccion),
        "dias_credito": datos.dias_credito,
    }


def obtener_cliente(db: Session, cliente_id: int) -> Cliente:
    cliente = db.get(Cliente, cliente_id)
    if cliente is None:
        raise DatoInvalidoError(f"No existe el cliente {cliente_id}")
    return cliente


def listar_clientes(
    db: Session, buscar: str = "", incluir_inactivos: bool = False, limite: int = 200
) -> list[Cliente]:
    consulta = select(Cliente)
    buscar = buscar.strip()
    if buscar:
        patron = f"%{buscar}%"
        consulta = consulta.where(
            or_(
                Cliente.nombre_negocio.ilike(patron),
                Cliente.nombre_contacto.ilike(patron),
                Cliente.telefono.ilike(patron),
            )
        )
    if not incluir_inactivos:
        consulta = consulta.where(Cliente.activo.is_(True))
    return list(db.scalars(consulta.order_by(Cliente.nombre_negocio).limit(limite)))


def crear_cliente(db: Session, datos: DatosCliente) -> Cliente:
    cliente = Cliente(**_normalizar(db, datos))
    db.add(cliente)
    db.flush()
    return cliente


def actualizar_cliente(db: Session, cliente_id: int, datos: DatosCliente) -> Cliente:
    cliente = obtener_cliente(db, cliente_id)
    for campo, valor in _normalizar(db, datos, excluir_id=cliente.id).items():
        setattr(cliente, campo, valor)
    db.flush()
    return cliente


def direcciones_activas(db: Session, cliente_id: int) -> list[DireccionEntrega]:
    return list(
        db.scalars(
            select(DireccionEntrega)
            .where(DireccionEntrega.cliente_id == cliente_id, DireccionEntrega.activo.is_(True))
            .order_by(DireccionEntrega.alias)
        )
    )


def agregar_direccion(
    db: Session, cliente_id: int, alias: str, direccion: str, referencia: str | None = None
) -> DireccionEntrega:
    cliente = obtener_cliente(db, cliente_id)
    alias_limpio, direccion_limpia = _limpio(alias), _limpio(direccion)
    if alias_limpio is None or direccion_limpia is None:
        raise DatoInvalidoError("El alias y la dirección son obligatorios")
    if any(
        d.alias.casefold() == alias_limpio.casefold() for d in direcciones_activas(db, cliente.id)
    ):
        raise DatoInvalidoError(f"Este cliente ya tiene una dirección llamada {alias_limpio}")

    nueva = DireccionEntrega(
        cliente_id=cliente.id,
        alias=alias_limpio,
        direccion=direccion_limpia,
        referencia=_limpio(referencia),
    )
    db.add(nueva)
    db.flush()
    return nueva


def desactivar_direccion(db: Session, cliente_id: int, direccion_id: int) -> None:
    direccion = db.get(DireccionEntrega, direccion_id)
    if direccion is None or direccion.cliente_id != cliente_id:
        raise DatoInvalidoError("La dirección no pertenece a este cliente")
    direccion.activo = False
    db.flush()