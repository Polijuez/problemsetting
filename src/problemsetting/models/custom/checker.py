"""Checker del problema «Faros» (plantilla del modelo `custom`).

Este archivo es el que `init.yml` declara como `checker: checker.py`, y es **la**
diferencia entre el modelo `custom` y `standard`: `StandardGrader` sigue
manejando todo (lanza el proceso, mide tiempo y memoria) y sólo la comparación
final pasa por acá.  Devolviendo `CheckerResult` con puntaje fraccionario se
otorga puntaje parcial sin tocar el motor del juez.

    from dmoj.result import CheckerResult      # (dmoj/graders/standard.py:36-40)
    CheckerResult(passed, points)              # points puede ser fraccionario

Firma que llama el juez (`dmoj/graders/standard.py:57-70`):

    check(process_output, judge_output, judge_input, point_value,
          submission_source, **kwargs)

`point_value` es el puntaje **del lote**, no del problema, así que un factor
sobre él compone bien con problemas por subtareas (`batched-custom`).
`submission_source` es el fuente de la submission, en **bytes**; es lo que hace
posible la receta de codegolf del final de este archivo.

El problema, en una línea: hay que iluminar un círculo de ~n~ posiciones
poniendo la menor cantidad de faros.  Un faro en ~i~ ilumina ~i-1~, ~i~ e ~i+1~
(en círculo), y el óptimo es ~\\lceil n/3 \\rceil~.

Las tres decisiones de diseño que importan, y que son el motivo de que esta
plantilla exista:

1. **Se valida el objeto, no el puntaje que la submission declara.**  La salida
   trae la cantidad de faros, pero el checker **no** la usa para puntuar: cuenta
   las posiciones que realmente vinieron en la salida, recalcula qué queda
   iluminado y recién de ahí saca la calidad.  Una submission que dice «2 faros»
   y manda treinta no saca puntaje completo por haber escrito un 2.
2. **La entrada malformada no puede tirar una excepción.**  Una excepción acá no
   es un WA: el juez la reporta como error interno, o sea un problema roto.  Por
   eso todo lo que viene de la submission se parsea adentro de un `try` y el
   camino de basura tiene un puntaje fijo y determinista.
3. **Lo que viene de *nuestro* lado (el input del caso, la salida del modelo) sí
   es ruidoso.**  Si el input no se puede leer, o si la salida del modelo no es
   óptima, el problema está mal armado y conviene que se vea como IE en vez de
   esconderse detrás de un puntaje parcial.  Es la asimetría central de un
   checker: la submission es hostil y hay que aguantarla; el problema es nuestro
   y hay que exigirle.
"""

from dmoj.result import CheckerResult
from dmoj.utils.unicode import utf8text

#: Calidad de una respuesta válida pero no óptima.  Es la fracción que el sitio
#: otorga a la submission parcial del manifest, y `submissions.yml` la declara
#: como el `score:` de esa submission -- 70 para este 0.7.  La fracción es
#: verificable de punta a punta: el launcher del pool emite los puntos por caso,
#: `judges` los expone y `verify` puntúa la fracción en vez de darle el lote
#: entero por ser AC.
PUNTAJE_PARCIAL = 0.7

#: Calidad de una respuesta válida que además es muy ineficiente (usa más del
#: doble del óptimo).  Existe para que el puntaje sea una función de la calidad
#: y no un interruptor; con un solo nivel, «parcial» y «pésimo» no se distinguen.
PUNTAJE_POBRE = 0.4

#: A partir de cuántos múltiplos del óptimo una respuesta válida ya es «pobre».
FACTOR_POBRE = 2


def optimo(n):
    """Mínima cantidad de faros que ilumina un círculo de ``n`` posiciones.

    Es la fórmula clásica del conjunto dominante mínimo de un ciclo,
    ~\\lceil n/3 \\rceil~: cada faro cubre tres posiciones y no hay solape útil
    posible para hacerlo mejor.  Se calcula acá en vez de leerla de
    ``judge_output`` a propósito: leer el óptimo del output del modelo sería
    confiar en el modelo, y este checker existe justamente para no confiar.
    """
    return -(-n // 3)


def cubre(posiciones, n):
    """True si los faros de ``posiciones`` iluminan todas las posiciones."""

    iluminadas = set()
    for posicion in posiciones:
        # En círculo: el vecino de n es 1 y el de 1 es n.
        for desplazamiento in (-1, 0, 1):
            iluminadas.add((posicion - 1 + desplazamiento) % n + 1)
    return len(iluminadas) == n


def leer_n(judge_input):
    """El ``n`` del input del caso.

    A diferencia de todo lo que viene de la submission, acá un error es un
    problema roto y no una submission mala: se deja escapar la excepción para
    que el juez lo reporte como error interno en vez de puntuarla.
    """
    tokens = utf8text(judge_input).split()
    if len(tokens) != 1:
        raise ValueError(f"el input del caso debe ser un único entero n, no {tokens!r}")
    n = int(tokens[0])
    if n < 1:
        raise ValueError(f"n debe ser positivo, no {n}")
    return n


def check(process_output, judge_output, judge_input, point_value, submission_source, **kwargs):
    n = leer_n(judge_input)
    mejor = optimo(n)

    # El output del modelo es nuestra referencia: si no es óptimo, el problema
    # está mal construido (los `.out` se generan con él) y ninguna submission
    # puede sacar puntaje completo.  Es una aserción sobre el *problema*, así que
    # falla ruidosamente.
    declarado_mejor = _cantidad_del_modelo(judge_output)
    if declarado_mejor != mejor:
        raise ValueError(
            f"la salida modelo declara {declarado_mejor} faros pero el óptimo de n={n} es "
            f"{mejor}: los .out no son óptimos y el problema no puede dar puntaje completo"
        )

    # `utf8text` decodifica en modo estricto, así que un output con bytes
    # inválidos levanta `UnicodeDecodeError` acá.  Eso lo maneja el juez, no el
    # checker: `dmoj/graders/standard.py:71-74` envuelve la llamada y convierte
    # ese error en `CheckerResult(False, 0, feedback='invalid unicode')`.  O sea
    # que un output con bytes basura da WA, no error interno -- que es lo
    # correcto -- y replicar ese `except` acá sería duplicar la política del
    # juez sobre el mismo caso.
    tokens = utf8text(process_output).split()
    if not tokens:
        return CheckerResult(False, 0.0, feedback="salida vacía")

    # ── Primera línea: la única condición barata ────────────────────────────
    # Se puede decidir sin parsear el resto, así que fallarla es un rechazo
    # limpio y no un parcial: quien no puede escribir una cantidad de faros
    # plausible no construyó nada.
    try:
        declarados = int(tokens[0])
    except ValueError:
        return CheckerResult(
            False, 0.0, feedback=f"la primera línea no es un entero: {tokens[0][:16]!r}"
        )
    if not 1 <= declarados <= n:
        return CheckerResult(
            False, 0.0, feedback=f"cantidad de faros fuera de rango: {declarados} (1..{n})"
        )

    # A partir de acá la primera línea es válida, así que el piso es parcial:
    # *si* la basura que sigue impide validar el objeto, se otorga igual el
    # puntaje parcial de forma determinista.  Es la misma forma que usa el
    # checker de producción de `vuelo` y la razón de que el camino de excepción
    # sea un `return` y no un `raise`.
    parcial = PUNTAJE_PARCIAL * point_value
    try:
        posiciones = [int(token) for token in tokens[1:]]
    except ValueError:
        return CheckerResult(
            True, parcial, feedback="posiciones ilegibles después de una primera línea válida"
        )

    # El objeto que se valida es la lista que vino, no la cantidad declarada: si
    # no coinciden, el envío se contradice a sí mismo.
    if len(posiciones) != declarados:
        return CheckerResult(
            True,
            parcial,
            feedback=f"declara {declarados} faros pero manda {len(posiciones)} posiciones",
        )
    if len(set(posiciones)) != len(posiciones):
        return CheckerResult(True, parcial, feedback="hay posiciones repetidas")
    if any(posicion < 1 or posicion > n for posicion in posiciones):
        return CheckerResult(True, parcial, feedback=f"hay posiciones fuera de 1..{n}")

    # ── El objeto está bien formado: recién ahora se juzga ──────────────────
    if not cubre(posiciones, n):
        return CheckerResult(
            False, 0.0, feedback=f"{declarados} faros no alcanzan para iluminar las {n} posiciones"
        )

    # La calidad sale de la cantidad *validada*, que es lo que el objeto
    # realmente es.  Es el punto entero del modelo: el puntaje no se declara, se
    # mide.
    if declarados == mejor:
        return CheckerResult(True, point_value, feedback=f"óptimo: {mejor} faros")
    if declarados <= FACTOR_POBRE * mejor:
        return CheckerResult(
            True, parcial, feedback=f"válido pero subóptimo: {declarados} faros, óptimo {mejor}"
        )
    return CheckerResult(
        True,
        PUNTAJE_POBRE * point_value,
        feedback=f"válido pero muy ineficiente: {declarados} faros, óptimo {mejor}",
    )


def _cantidad_del_modelo(judge_output):
    """La cantidad de faros que declara la salida del modelo (nuestro artefacto)."""
    tokens = utf8text(judge_output).split()
    if not tokens:
        raise ValueError("la salida modelo está vacía: los .out no se generaron")
    return int(tokens[0])


# =========================================================================
# Receta: cómo sería un checker de codegolf
# =========================================================================
#
# Un problema de codegolf no se puntúa por lo que el programa *hace* -- si el
# problema es correcto, todas las submissions correctas hacen lo mismo -- sino
# por lo *corta* que es la solución.  `check()` recibe `submission_source`, así
# que toda la mecánica ya está disponible sin motor nuevo.  Lo que sigue es una
# receta comentada, no un checker en uso: para que fuera un problema de verdad
# falta lo que dice el final.
#
#     LIMITE = 512   # bytes de referencia declarados en el enunciado
#
#     def codegolf_check(process_output, judge_output, judge_input,
#                        point_value, submission_source, **kwargs):
#         # 1) Primero la corrección: un programa corto que no resuelve el
#         #    problema vale 0, no "puntaje parcial por lindo".  El orden de
#         #    estas dos comprobaciones es el problema entero.
#         if not correcto(process_output, judge_output):
#             return CheckerResult(False, 0.0, feedback="no resuelve el problema")
#
#         # 2) Después el tamaño.  `submission_source` llega como *bytes*
#         #    (dmoj/graders/base.py:22-23 lo pasa por utf8bytes), así que
#         #    `len()` YA es la cuenta en bytes y coincide con lo que el sitio
#         #    reporta como tamaño del archivo.  Lo que NO hay que hacer es
#         #    `len(utf8text(submission_source))`: eso cuenta caracteres, y un
#         #    programa con un identificador acentuado -- o cualquier literal
#         #    no ASCII -- mediría menos de lo que pesa el archivo.
#         byte_count = len(submission_source)
#
#         # 3) El puntaje es una función monótona del tamaño, con piso 0 y techo
#         #    `point_value`.  Se normaliza contra un `LIMITE` que tiene que
#         #    estar en el enunciado: sin una referencia publicada, "corto" no
#         #    es una meta alcanzable y el problema es injusto.
#         if byte_count >= LIMITE:
#             return CheckerResult(True, 0.0, feedback=f"{byte_count} bytes (límite {LIMITE})")
#         return CheckerResult(True, point_value * (LIMITE - byte_count) / LIMITE)
#
# Desempate.  Con puntaje continuo, dos programas de igual longitud empatan
# exactamente, y en un problema real eso no se puede arreglar con el puntaje: el
# desempate es de la *tabla*, no del puntaje.  Lo que sí conviene hacer acá es
# que el orden sea total y reproducible, así que si el problema define un
# desempate propio (por ejemplo tiempo de ejecución, o el hash del fuente) hay
# que meterlo en la misma función y documentarlo en el enunciado.  Un desempate
# implícito, como el orden en que llegaron las submissions, es una lotería.
#
# Qué le falta para ser un problema de verdad, en vez de una receta:
#
#   * **Una referencia publicada.**  `LIMITE` tiene que estar en el enunciado y
#     en los datos del problema, no sólo en este archivo.
#   * **Puntaje por caso que se componga bien.**  `check()` corre *una vez por
#     caso* y el tamaño del fuente es el mismo en todos.  Con `point_value` de
#     100 por caso y diez casos, cada uno devolvería el mismo número y el lote
#     sumaría diez veces la misma fracción.  Un problema de codegolf real necesita
#     que el puntaje se normalice contra el total del problema, y eso hoy pide un
#     `custom_judge` (que reemplaza el grader entero y puede mantener estado
#     entre casos) en lugar de un `checker:` -- que es exactamente la frontera
#     entre los dos mecanismos que documenta `meta.yml`.
#   * **Decidir qué se mide.**  Acá se mide el fuente tal como se envió; un
#     enunciado serio tiene que decir si cuentan los comentarios, los espacios y
#     el `#include`, porque el sitio no los distingue.
