import re

from app.servicios.errores import DatoInvalidoError

# 3 letras (moral) o 4 (física), fecha AAMMDD y homoclave de 3
PATRON_RFC = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z\d]{3}$")


def normalizar_rfc(valor: str | None) -> str | None:
    rfc = "".join((valor or "").split()).upper().replace("-", "")
    if not rfc:
        return None
    if not PATRON_RFC.match(rfc):
        raise DatoInvalidoError(f"El RFC {rfc} no tiene un formato válido")
    return rfc