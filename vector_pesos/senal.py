from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResultadoSenal:
    """
    CONTIENE EL RESULTADO DE LA FUNCIÓN CENTRAL DE SEÑAL.
    """

    valor: float
    decision: str  # "COMPRA" | "VENTA" | "NO_OPERAR"
    # TOP CONTRIBUCIONES (VARIABLE -> w_i * x_i) PARA AUDITORÍA / DEBUG.
    contribuciones: list[tuple[str, float]] | None = None


def evaluar_senal(
    vector_mercado: dict[str, float],
    vector_pesos: dict[str, float],
    umbral_compra: float,
    umbral_venta: float,
    *,
    devolver_contribuciones: bool = False,
    top_n: int = 5,
) -> ResultadoSenal:
    """
    IMPLEMENTA LA LÓGICA MATEMÁTICA CENTRAL: s~ = w^T x

    QUÉ HACE:
    - CALCULA PRODUCTO PUNTO ENTRE PESOS (w) Y VARIABLES (x) POR NOMBRE.
    - APLICA UMBRALES PARA DECIDIR COMPRA/VENTA/NEUTRO.

    POR QUÉ:
    - SEPARA MERCADO (x) DE ESTRATEGIA (w).
    - PERMITE CAMBIAR PESOS (INCLUSO POR IA) SIN TOCAR EL CONSTRUCTOR DE VARIABLES.
    """
    valor = 0.0
    contribs: dict[str, float] | None = {} if devolver_contribuciones else None
    for nombre_variable, x_i in vector_mercado.items():
        w_i = float(vector_pesos.get(nombre_variable, 0.0))
        c = w_i * float(x_i)
        valor += c
        if contribs is not None:
            contribs[str(nombre_variable)] = float(c)

    top: list[tuple[str, float]] | None = None
    if contribs is not None:
        n = max(0, int(top_n))
        items = list(contribs.items())
        items.sort(key=lambda kv: abs(float(kv[1])), reverse=True)
        top = [(str(k), float(v)) for k, v in items[:n]]

    if valor >= float(umbral_compra):
        decision = "COMPRA"
    elif valor <= float(umbral_venta):
        decision = "VENTA"
    else:
        decision = "NO_OPERAR"

    return ResultadoSenal(valor=float(valor), decision=decision, contribuciones=top)


