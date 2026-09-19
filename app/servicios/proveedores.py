from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.modelos import Producto, Proveedor, ProveedorProducto, Unidad
from app.servicios.catalogo import costo_vigente, registrar_costo
from app.servicios.errores import DatoInvalidoError, PrecioNoDefinidoError

MAX_DIAS_CREDITO = 180


@dataclass(frozen=True)
class DatosProveedor:
    nombre: str
    contacto: str | None = None
    telefono: str | None = None
    email: str | None = None
    dias_credito: int = 0


def _limpio(texto: str | None) -> str | None:
    texto = " ".join((texto or "").split())
    return texto or None


def _normalizar(db: Session, datos: DatosProveedor, excluir_id: int | None = None) -> dict:
    nombre = _limpio(datos.nombre)
    if nombre is None:
        raise DatoInvalidoError("El nombre del proveedor es obligatorio")
    if not 0 <= datos.dias_credito <= MAX_DIAS_CREDITO:
        raise DatoInvalidoError(f"Los días de crédito deben estar entre 0 y {MAX_DIAS_CREDITO}")
    email = _limpio(datos.email)
    if email and ("@" not in email or " " in email):
        raise DatoInvalidoError("El correo no parece válido")

    clave = nombre.casefold()
    existentes = db.execute(select(Proveedor.id, Proveedor.nombre))
    if any(n.casefold() == clave and i != excluir_id for i, n in existentes):
        raise DatoInvalidoError(f"Ya existe un proveedor llamado {nombre}")

    return {
        "nombre": nombre,
        "contacto": _limpio(datos.contacto),
        "telefono": _limpio(datos.telefono),
        "email": email.lower() if email else None,
        "dias_credito": datos.dias_credito,
    }


def obtener_proveedor(db: Session, proveedor_id: int) -> Proveedor:
    proveedor = db.get(Proveedor, proveedor_id)
    if proveedor is None:
        raise DatoInvalidoError(f"No existe el proveedor {proveedor_id}")
    return proveedor


def listar_proveedores(
    db: Session, buscar: str = "", incluir_inactivos: bool = False
) -> list[Proveedor]:
    consulta = select(Proveedor)
    buscar = buscar.strip()
    if buscar:
        patron = f"%{buscar}%"
        consulta = consulta.where(
            or_(
                Proveedor.nombre.ilike(patron),
                Proveedor.contacto.ilike(patron),
                Proveedor.telefono.ilike(patron),
            )
        )
    if not incluir_inactivos:
        consulta = consulta.where(Proveedor.activo.is_(True))
    return list(db.scalars(consulta.order_by(Proveedor.nombre)))


def crear_proveedor(db: Session, datos: DatosProveedor) -> Proveedor:
    proveedor = Proveedor(**_normalizar(db, datos))
    db.add(proveedor)
    db.flush()
    return proveedor


def actualizar_proveedor(db: Session, proveedor_id: int, datos: DatosProveedor) -> Proveedor:
    proveedor = obtener_proveedor(db, proveedor_id)
    for campo, valor in _normalizar(db, datos, excluir_id=proveedor.id).items():
        setattr(proveedor, campo, valor)
    db.flush()
    return proveedor


# ---------- Productos que surte el proveedor ----------

def listar_suministros(db: Session, proveedor_id: int) -> list[ProveedorProducto]:
    return list(
        db.scalars(
            select(ProveedorProducto)
            .options(
                joinedload(ProveedorProducto.producto).joinedload(Producto.unidad),
                joinedload(ProveedorProducto.unidad_compra),
            )
            .join(ProveedorProducto.producto)
            .where(
                ProveedorProducto.proveedor_id == proveedor_id,
                ProveedorProducto.activo.is_(True),
            )
            .order_by(Producto.codigo)
        )
    )


def costos_vigentes(db: Session, suministros: list[ProveedorProducto]) -> dict[int, Decimal]:
    resultado = {}
    for suministro in suministros:
        try:
            resultado[suministro.id] = costo_vigente(db, suministro.id)
        except PrecioNoDefinidoError:
            continue
    return resultado


def agregar_suministro(
    db: Session,
    proveedor_id: int,
    producto_id: int,
    unidad_compra_id: int,
    factor_conversion: Decimal,
    costo: Decimal | None = None,
    solo_unidades_completas: bool = True,
) -> ProveedorProducto:
    proveedor = obtener_proveedor(db, proveedor_id)
    producto = db.get(Producto, producto_id)
    if producto is None or not producto.activo:
        raise DatoInvalidoError("El producto no existe o está inactivo")
    if db.get(Unidad, unidad_compra_id) is None:
        raise DatoInvalidoError("La unidad de compra no existe")

    factor = Decimal(str(factor_conversion))
    if not factor.is_finite() or factor <= 0:
        raise DatoInvalidoError("El factor de conversión debe ser mayor a cero")

    existente = db.scalar(
        select(ProveedorProducto).where(
            ProveedorProducto.proveedor_id == proveedor.id,
            ProveedorProducto.producto_id == producto.id,
        )
    )
    if existente is not None and existente.activo:
        raise DatoInvalidoError(f"{producto.codigo} ya está en el catálogo de este proveedor")

    if existente is not None:
        existente.activo = True
        existente.unidad_compra_id = unidad_compra_id
        existente.factor_conversion = factor
        existente.solo_unidades_completas = solo_unidades_completas
        suministro = existente
    else:
        suministro = ProveedorProducto(
            proveedor_id=proveedor.id,
            producto_id=producto.id,
            unidad_compra_id=unidad_compra_id,
            factor_conversion=factor,
            solo_unidades_completas=solo_unidades_completas,
        )
        db.add(suministro)
    db.flush()

    if costo is not None:
        registrar_costo(db, suministro.id, costo)
    return suministro


def quitar_suministro(db: Session, proveedor_id: int, suministro_id: int) -> None:
    suministro = db.get(ProveedorProducto, suministro_id)
    if suministro is None or suministro.proveedor_id != proveedor_id:
        raise DatoInvalidoError("Ese producto no pertenece a este proveedor")
    suministro.activo = False
    suministro.es_preferido = False
    db.flush()