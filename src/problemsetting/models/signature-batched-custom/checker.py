"""Checker del problema «Ronda» (plantilla del modelo `signature-batched-custom`).

Este archivo es el que `init.yml` declara como `checker: checker.py`, y en este
modelo esa declaración convive con **dos** mecanismos más: una escalera de
subtareas y una interfaz de firma.  Las tres piezas están documentadas por
separado en sus plantillas:

  * el checker como reemplazo de la comparación, con sus tres decisiones de
    diseño (validar el objeto, no romperse con la basura, exigirle al artefacto
    propio), en `models/custom/checker.py`;
  * los lotes y las dependencias en `models/batched/generator.py`, y la
    interacción «el checker se llama con el `point_value` del lote» en
    `models/batched-custom/checker.py`;
  * la composición de firma, el `#include` y el `#define main main_<uuid>`, en
    `models/signature-batched/signature.hpp`.

Lo que se documenta **acá** es lo que cambia cuando la submission no imprime
nada:

1. **El checker no ve la salida de la submission: ve la del evaluador.**  La
   función del concursante *recibe* el arreglo donde escribir las posiciones y
   devuelve cuántas escribió; el evaluador `evaluator.cpp` -- el programa que el
   concursante no escribe -- imprime esa cantidad y esas posiciones.  Para este
   archivo el efecto es nulo: `process_output` sigue siendo «un entero `K` en la
   primera línea y `K` posiciones después», exactamente el formato que lee el
   checker de `batched-custom`.  Esa continuidad es el punto: el formato de
   salida es del **evaluador**, así que cambiar de E/S a firma no obliga a
   reescribir la validación.

2. **Lo que la firma sí agrega es un límite que el checker no puede verificar.**
   El evaluador reserva el arreglo con capacidad ~n~ (el `n` del caso) y lo pasa
   a la función; una función que escriba más de `n` posiciones corrompe memoria
   en vez de producir una salida inválida.  Eso no es un WA: es un fallo del
   proceso, y el enunciado y `signature.hpp` lo dicen explícitamente porque no es
   deducible de la firma.  El checker, en cambio, **sí** puede rechazar el
   resultado de esa escritura cuando el proceso sobrevive: la cantidad que el
   evaluador imprime tiene que coincidir con las posiciones que imprimió, todas
   dentro de `1..n` y todas distintas.

3. **La calidad se mide sobre el objeto, no sobre lo que la función declara.**  La
   función devuelve `K` y eso es lo que el evaluador imprime primero, así que un
   envío *podría* devolver un `K` que no corresponde a lo que escribió.  El
   checker no le cree a `K`: recalcula qué queda iluminado con las posiciones que
   llegaron.  `_faros_del_modelo` y la comprobación `len(posiciones) != declarados`
   son las dos mitades de esa desconfianza.

El problema, en una línea: hay que iluminar una ronda de ~n~ posiciones poniendo
la menor cantidad de faros, y cada faro ilumina las dos posiciones a cada lado
(cinco en total, en círculo).  El óptimo es ~\\lceil n/5 \\rceil~.

El cuerpo restante -- la validación de la construcción, las bandas de puntaje y
el contraste con `custom` en la rama de basura -- es el mismo del checker de
`batched-custom`, y no por copia mecánica: es el mismo problema con la misma
escalera, y la única variable que este modelo mueve es la interfaz.
"""

from dmoj.result import CheckerResult
from dmoj.utils.unicode import utf8text

#: Cuántas posiciones a cada lado ilumina un faro.  El alcance total es
#: ``2 * RADIO + 1`` posiciones, y de ahí sale el óptimo de abajo.
RADIO = 2
ALCANCE = 2 * RADIO + 1

#: Calidad de una respuesta válida que usa hasta el doble del óptimo.  Es la
#: fracción que el sitio otorgaría **dentro del lote del caso**: el evaluador
#: imprime el `K` que devolvió la función, y `point_value` es el `points:` del
#: lote de ese caso (ver el punto 1 del encabezado de `batched-custom/checker.py`).
PUNTAJE_PARCIAL = 0.7

#: Calidad de una respuesta válida pero muy ineficiente (más del doble del
#: óptimo).  Existe para que el puntaje sea una función de la calidad y no un
#: interruptor; con un solo nivel, «parcial» y «pésimo» no se distinguen.
PUNTAJE_POBRE = 0.4

#: A partir de cuántos múltiplos del óptimo una respuesta válida ya es «pobre».
FACTOR_POBRE = 2


def optimo(n):
    """Mínima cantidad de faros que ilumina una ronda de ``n`` posiciones.

    Cada faro ilumina ``ALCANCE`` posiciones, así que ninguna construcción puede
    bajar de ``ceil(n / ALCANCE)``; y ese número se alcanza siempre: poniendo
    faros en ``3, 8, 13, ...`` cada uno cubre cinco posiciones nuevas salvo el
    solapamiento de una al principio y al final de la ronda.  El argumento
    completo, y la construcción que lo realiza, están en ``solution.cpp`` y
    ``solution.c``; acá alcanza con que el óptimo es una **fórmula cerrada**, que
    es lo que permite puntuar sin correr una búsqueda.
    """
    return -(-n // ALCANCE)


def cubre(posiciones, n):
    """True si los faros de ``posiciones`` iluminan todas las posiciones.

    Se recalcula qué queda iluminado en vez de creerle a la cantidad declarada:
    es el punto entero de validar el objeto -- y acá vale igual aunque el
    concursante no haya impreso nada, porque el número que el evaluador imprime
    es el valor de retorno de su función.  ``bytearray`` y no un ``set`` porque
    un faro ilumina ``ALCANCE`` posiciones y en el caso más grande del problema
    eso son millones de marcas.
    """
    iluminadas = bytearray(n + 1)
    restantes = n
    for posicion in posiciones:
        for delta in range(-RADIO, RADIO + 1):
            # Índice circular 1..n: la posición n es vecina de la 1.
            iluminada = (posicion - 1 + delta) % n + 1
            if not iluminadas[iluminada]:
                iluminadas[iluminada] = 1
                restantes -= 1
    return restantes == 0


def leer_n(judge_input):
    """El ``n`` del input del caso.

    Esto viene de *nuestro* lado, no de la submission, así que un input ilegible
    es un error del problema y tiene que verse: por eso levanta en vez de
    devolver un puntaje.  La asimetría -- la submission se aguanta, el problema
    se exige -- es la que documenta `models/custom/checker.py`.
    """
    tokens = utf8text(judge_input).split()
    if not tokens:
        raise ValueError("el input del caso está vacío")
    n = int(tokens[0])
    if n < 1:
        raise ValueError(f"el input del caso declara n={n}, y la ronda tiene al menos una posición")
    return n


def _faros_del_modelo(judge_output):
    """La cantidad de faros que declara la salida del modelo (nuestro artefacto)."""
    tokens = utf8text(judge_output).split()
    if not tokens:
        raise ValueError("la salida modelo está vacía: los .out no se generaron")
    return int(tokens[0])


def check(process_output, judge_output, judge_input, point_value, submission_source, **kwargs):
    n = leer_n(judge_input)
    mejor = optimo(n)

    # El output del modelo es nuestra referencia: si no es óptimo, el problema
    # está mal construido (los `.out` se generan con él) y ninguna submission
    # puede sacar puntaje completo.  Es una aserción sobre el *problema*, así que
    # falla ruidosamente en vez de esconderse detrás de un puntaje parcial.
    declarado_mejor = _faros_del_modelo(judge_output)
    if declarado_mejor != mejor:
        raise ValueError(
            f"la salida modelo declara {declarado_mejor} faros pero el óptimo de n={n} es "
            f"{mejor}: los .out no son óptimos y el problema no puede dar puntaje completo"
        )

    # `utf8text` decodifica en modo estricto, así que un output con bytes inválidos
    # levanta `UnicodeDecodeError` acá; el juez lo convierte en
    # `CheckerResult(False, 0, feedback='invalid unicode')`
    # (`dmoj/graders/standard.py:71-74`), que es el WA correcto.
    tokens = utf8text(process_output).split()
    if not tokens:
        return CheckerResult(False, 0.0, feedback="salida vacía")

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

    # De acá en adelante todo desvío es un rechazo, no un parcial: ver el
    # contraste con `custom` en el encabezado de `batched-custom/checker.py`.
    try:
        posiciones = [int(token) for token in tokens[1:]]
    except ValueError:
        return CheckerResult(False, 0.0, feedback="hay posiciones ilegibles después de la primera línea")

    # El objeto que se valida es la lista que vino, no la cantidad declarada: si
    # no coinciden, el envío se contradice a sí mismo.  Acá la contradicción tiene
    # una forma propia del modelo de firma -- la función devolvió un `K` que no es
    # la cantidad de posiciones que escribió -- y por eso esta comprobación es la
    # que traduce esa posibilidad al vocabulario del checker.
    if len(posiciones) != declarados:
        return CheckerResult(
            False,
            0.0,
            feedback=f"declara {declarados} faros pero manda {len(posiciones)} posiciones",
        )
    if len(set(posiciones)) != len(posiciones):
        return CheckerResult(False, 0.0, feedback="hay posiciones repetidas")
    if any(posicion < 1 or posicion > n for posicion in posiciones):
        return CheckerResult(False, 0.0, feedback=f"hay posiciones fuera de 1..{n}")

    # ── El objeto está bien formado: recién ahora se juzga ──────────────────
    if not cubre(posiciones, n):
        return CheckerResult(
            False,
            0.0,
            feedback=f"{declarados} faros no alcanzan para iluminar las {n} posiciones",
        )

    # La calidad sale de la cantidad *validada*, que es lo que el objeto
    # realmente es -- y se multiplica por el puntaje del LOTE del caso, no por el
    # del problema.  Ese producto es lo que hace que la fracción componga con la
    # escalera de subtareas.
    if declarados == mejor:
        return CheckerResult(True, point_value, feedback=f"óptimo: {mejor} faros")
    if declarados <= FACTOR_POBRE * mejor:
        return CheckerResult(
            True,
            PUNTAJE_PARCIAL * point_value,
            feedback=f"válido pero subóptimo: {declarados} faros, óptimo {mejor}",
        )
    return CheckerResult(
        True,
        PUNTAJE_POBRE * point_value,
        feedback=f"válido pero muy ineficiente: {declarados} faros, óptimo {mejor}",
    )
