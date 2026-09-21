"""Checker del problema «Ronda» (plantilla del modelo `batched-custom`).

Este archivo es el que `init.yml` declara como `checker: checker.py`, y en este
modelo esa declaración convive con una escalera de subtareas.  El mecanismo de
cada pieza por separado está documentado en su plantilla:

  * el checker como reemplazo de la comparación, y las tres decisiones de diseño
    de un checker (validar el objeto, no romperse con basura, exigirle al
    artefacto propio), en `models/custom/checker.py`;
  * los lotes, los puntajes por subtarea y las dependencias, en
    `models/batched/generator.py`.

Lo que se documenta **acá** es la interacción, que es la única razón de que este
modelo exista aparte:

1. **El checker se llama una vez por caso, con el puntaje del lote al que ese
   caso pertenece.**  El juez pasa `point_value=case.points`
   (`dmoj/graders/standard.py:57-70`) y, para un caso dentro de un lote,
   `case.points` es el `points:` del lote: los casos internos se construyen con
   el `ConfigNode` del caso como config (`dmoj/problem.py:226-239`) y
   `ConfigNode.__getitem__` cae al padre cuando el hijo no tiene la clave
   (`dmoj/config.py`), así que `points` se resuelve en el lote.  O sea: en este
   problema `0.7 * point_value` no es «0.7 del problema», es **0.7 de la
   subtarea de ese caso**.  Por eso una misma fracción devuelve números
   distintos según el lote -- 0.7 de 10 en la Subtarea 1, 0.7 de 40 en la 4 -- y
   el puntaje parcial de una submission es la suma de esas fracciones por lote.
   Un checker escrito suponiendo que `point_value` es el total del problema
   puntúa mal acá, y sólo acá: en `custom` las dos cosas coinciden porque hay un
   solo lote.

2. **Un caso que falla corta el resto de *su* lote.**  El juez levanta una marca
   de cortocircuito al ver un WA y saltea los casos que quedan de ese lote
   (`dmoj/judge.py:526-533`); los salteados se reportan `SC` sin ejecutarse, y la
   marca se limpia en el `BATCH_END` de ese lote, así que el lote siguiente
   arranca de cero.  Consecuencia que sólo aparece al combinar los dos
   mecanismos: **dónde** falla un caso decide cuánto puntaje parcial sobrevive.
   Una submission que falla en el primer caso de un lote se lleva 0 de ese lote
   aunque hubiera pasado los siguientes; la misma submission con el caso difícil
   al final se lleva la fracción de todos los que alcanzó a correr.  Por eso los
   casos de esta plantilla están ordenados de mayor a menor (ver `generator.py`).

3. **El puntaje de un lote fraccionario lo compone el lector del toolkit, no el
   juez.**  DMOJ informa `Result.points`/`Result.total_points` caso por caso y
   nada más; `verify` divide `sum(points) / sum(totals)` sobre los casos del lote
   (`verify.BatchScore.earned`).  Los casos salteados entran a esa suma con 0
   puntos pero con su `total` intacto, así que también diluyen.  Un lote cuyos
   casos corrieron todos y sacaron 0.7 rinde exactamente 0.7 del lote; uno con
   casos salteados rinde menos, y ése es el número real que el sitio vería.

El problema, en una línea: hay que iluminar una ronda de ~n~ posiciones
poniendo la menor cantidad de faros, y cada faro ilumina las dos posiciones a
cada lado (cinco en total, en círculo).  El óptimo es ~\\lceil n/5 \\rceil~

El checker valida la construcción que la submission manda y recién de ahí saca
la calidad; no usa la cantidad que la submission *declara*.  Es la misma regla
que el modelo `custom` documenta en detalle: el objeto se valida, el número no
se cree.

Contraste deliberado con `custom`, en un punto: acá una salida ilegible es un
rechazo seco (~0~), no un piso parcial.  En `custom` el puntaje premia *haber
entendido* el problema aunque la basura siguiente impida validar el objeto; en
este problema el puntaje es una función de la **calidad de la construcción**, y
una construcción que no se puede leer no tiene calidad que premiar.  Elegir una
u otra es una decisión de autor: lo que no es opcional es que la rama de basura
sea determinista y no levante una excepción, porque una excepción acá no es un
WA -- el juez la reporta como error interno, o sea un problema roto.
"""

from dmoj.result import CheckerResult
from dmoj.utils.unicode import utf8text

#: Cuántas posiciones a cada lado ilumina un faro.  El alcance total es
#: ``2 * RADIO + 1`` posiciones, y de ahí sale el óptimo de abajo.
RADIO = 2
ALCANCE = 2 * RADIO + 1

#: Calidad de una respuesta válida que usa hasta el doble del óptimo.  Es la
#: fracción que el sitio otorgaría **dentro del lote del caso**: ver el punto 1
#: del encabezado.
PUNTAJE_PARCIAL = 0.7

#: Calidad de una respuesta válida pero muy ineficiente (más del doble del
#: óptimo).  Existe para que el puntaje sea una función de la calidad y no un
#: interruptor; con un solo nivel, «parcial» y «pésimo» no se distinguen.
PUNTAJE_POBRE = 0.4

#: A partir de cuántos múltiplos del óptimo una respuesta válida ya es «pobre».
FACTOR_POBRE = 2


def optimo(n):
    """Mínima cantidad de faros que ilumina una ronda de ``n`` posiciones.

    Cada faro ilumina ``ALCANCE`` posiciones, así que ninguna construcción
    puede bajar de ``ceil(n / ALCANCE)``; y ese número se alcanza siempre:
    poniendo faros en ``3, 8, 13, ...`` cada uno cubre cinco posiciones nuevas
    salvo el solapamiento de una al principio y al final de la ronda.  El
    argumento completo, y la construcción que lo realiza, están en
    ``solution.cpp``; acá alcanza con que el óptimo es una **fórmula cerrada**,
    que es lo que permite puntuar sin correr una búsqueda.
    """
    return -(-n // ALCANCE)


def cubre(posiciones, n):
    """True si los faros de ``posiciones`` iluminan todas las posiciones.

    Se recalcula qué queda iluminado en vez de creerle a la cantidad declarada:
    es el punto entero de validar el objeto.  ``bytearray`` y no un ``set``
    porque un faro ilumina ``ALCANCE`` posiciones y en el caso más grande del
    problema eso son millones de marcas: un contador de pendientes evita
    materializar un conjunto por caso.
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

    Esto viene de *nuestro* lado, no de la submission, así que un input
    ilegible es un error del problema y tiene que verse: por eso levanta en vez
    de devolver un puntaje.  La asimetría -- la submission se aguanta, el
    problema se exige -- es la que documenta `models/custom/checker.py`.
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
    # puede sacar puntaje completo.  Es una aserción sobre el *problema*, así
    # que falla ruidosamente en vez de esconderse detrás de un puntaje parcial.
    declarado_mejor = _faros_del_modelo(judge_output)
    if declarado_mejor != mejor:
        raise ValueError(
            f"la salida modelo declara {declarado_mejor} faros pero el óptimo de n={n} es "
            f"{mejor}: los .out no son óptimos y el problema no puede dar puntaje completo"
        )

    # `utf8text` decodifica en modo estricto, así que un output con bytes
    # inválidos levanta `UnicodeDecodeError` acá; el juez lo convierte en
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
    # contraste con `custom` en el encabezado.
    try:
        posiciones = [int(token) for token in tokens[1:]]
    except ValueError:
        return CheckerResult(False, 0.0, feedback="hay posiciones ilegibles después de la primera línea")

    # El objeto que se valida es la lista que vino, no la cantidad declarada: si
    # no coinciden, el envío se contradice a sí mismo.
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
    # realmente es -- y se multiplica por el puntaje del LOTE del caso, no por
    # el del problema.  Ese producto es lo que hace que la fracción componga con
    # la escalera de subtareas: ver el punto 1 del encabezado.
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
