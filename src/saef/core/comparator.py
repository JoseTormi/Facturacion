from saef.models import FacturaExtraida


def validar_factura(factura: FacturaExtraida) -> str:
    campos_requeridos = [
        factura.proveedor,
        factura.numero,
        factura.valor,
        factura.moneda,
        factura.ruta_pdf,
    ]
    if all(campo not in (None, "") for campo in campos_requeridos):
        return "ok"
    return "pendiente_validacion"

