class DatoInvalidoError(ValueError):
    """Datos capturados que no cumplen las reglas de negocio."""


class PrecioNoDefinidoError(Exception):
    """No hay precio o costo vigente en la fecha pedida."""