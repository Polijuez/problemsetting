"""Checker del problema «100000 como suma de Fibonacci» (plantilla `output-only-custom`).

Este archivo es el que `init.yml` declara como `checker: checker.py`, y es la
mitad del modelo que lo distingue de `output-only`: el envío sigue siendo un
`.txt` que el ejecutor `TEXT` corre con `cat` (`dmoj/executors/TEXT.py`), pero la
salida **no se compara por igualdad** -- se *puntúa*.  `StandardGrader` lanza el
proceso `cat` y después llama a `check()` de acá
(`dmoj/graders/standard.py:56-83`); el veredicto sale de `CheckerResult.passed` y
el puntaje de `CheckerResult.points`, que puede ser fraccionario
(`dmoj/graders/standard.py:36-40`).  Devolver `0.7 * point_value` es puntaje
parcial de verdad, sin motor nuevo.

Cuatro cosas definen a este checker, y son las que hay que leer antes de tocarlo:

1. **El objetivo es una constante del problema, no del caso.**  Este modelo no
   tiene inputs (`init.yml` declara cada caso sólo con `out:`), así que
   `judge_input` llega vacío y no hay instancia que leer.  Eso es *distinto* de un
   problema `custom`, donde el checker saca del input la instancia que valida.
   Consecuencia directa: el problema tiene un solo caso, porque dos casos serían
   el mismo objetivo repetido.

2. **Se puntúa el objeto, no el formato -- y el formato no paga nada.**  La
   primera línea declara cuántos sumandos vienen, y esa declaración no vale
   puntos: el checker recalcula la suma y comprueba que cada sumando sea de
   Fibonacci.  Una salida que *no* es una representación válida del objetivo saca
   **0**, por bien formateada que esté.  Nótese que acá el piso **no** es parcial:
   a diferencia de un problema con input, donde una primera línea plausible puede
   ser un intento genuino, en este modelo la declaración es gratis -- no hay
   ninguna instancia que haya que entender para escribirla.  Dar puntaje parcial
   por una línea suelta sería regalar el 70% de un problema sin resolverlo, y
   contradiría la tabla publicada en el enunciado.

3. **Las tres bandas del enunciado son las tres ramas de `check()`.**  Mínimo →
   puntaje completo; representación válida pero no mínima → `PUNTAJE_PARCIAL`;
   cualquier otra cosa → 0.  La tabla del enunciado y este código son el mismo
   contrato, y el test de la plantilla comprueba las tres contra los archivos que
   el manifest declara.

4. **El `out:` del modelo se exige; la submission se aguanta.**  Es la asimetría
   central de un checker, y acá es literal: si la salida del modelo no es una
   representación **mínima**, el problema está mal construido (los `.out` se
   copian de `solution.txt`) y el checker **falla ruidosamente** con `ValueError`.
   La submission, en cambio, es hostil y se tolera: cualquier basura que llegue
   se convierte en un `CheckerResult` determinista, nunca en una excepción.

Sobre los finales de línea: el ejecutor `TEXT` normaliza `\r\n` y `\r` a `\n`
antes de escribir el archivo (`StripCarriageReturnsMixin`,
`dmoj/executors/mixins.py:34-37`), y DMOJ hace lo mismo con el `out:` del caso
(`TestCase._normalize`, `dmoj/problem.py:361-381`).  Igual este checker no
depende de eso: parte la salida por espacios en blanco, así que un `\r` que
sobreviviera no cambiaría ningún veredicto.
"""

from dmoj.result import CheckerResult
from dmoj.utils.unicode import utf8text

#: El número que hay que representar.  Tiene que coincidir con `OBJETIVO` de
#: `generator.py`: uno corre durante el build y el otro dentro del juez, así que
#: nada los ata salvo el test de la plantilla, que compara los dos.
OBJETIVO = 100000

#: Cuántos sumandos acepta el enunciado como máximo.  Es un techo *publicado* (el
#: enunciado lo dice), y acá se usa para rechazar lo que se pase: sin un techo, no
#: habría nada que impida rellenar con `1 + 1 + 1 + ...` y el puntaje parcial no
#: tendría forma.  Mismo valor que `generator.TOPE`.
TOPE = 20

#: Calidad de una representación válida pero **no mínima**.  Es la fracción que el
#: sitio otorgaría al envío parcial del manifest, y `submissions.yml` explica por
#: qué su `score:` declarado es ese porcentaje y cómo se mide.
PUNTAJE_PARCIAL = 0.7


def fibonacci_hasta(limite):
    """Los números de Fibonacci ``1, 2, 3, 5, 8, ...`` que no superan ``limite``.

    Arranca en ``1, 2`` y no en ``0, 1``: el enunciado define ``F(1) = 1`` y
    ``F(2) = 2``.  Con ``0`` en la lista, cualquier representación se podría
    rellenar con ceros y la cantidad de sumandos dejaría de medir nada.
    """
    numeros = []
    anterior, actual = 1, 2
    while anterior <= limite:
        numeros.append(anterior)
        anterior, actual = actual, anterior + actual
    return numeros


def entero(token):
    """``token`` as an ``int``, or None unless it is **ASCII digits**.

    `int()` alone accepts far more than the statement promises: a leading ``+``,
    ``_`` as a thousands separator, and non-ASCII decimal digits such as ``٧`` or
    ``７`` all parse.  The statement says what it says -- "sólo cuentan los
    dígitos" -- so the parse is restricted here until the two agree, instead of
    leaving a contestant to discover the gap by experiment.
    """
    return int(token) if token.isascii() and token.isdigit() else None


def minimo(objetivo):
    """Mínima cantidad de sumandos de Fibonacci (repetidos o no) que suman ``objetivo``.

    Por programación dinámica, y a propósito: el algoritmo goloso de Zeckendorf
    -- tomar siempre el mayor que entra -- también da el mínimo, pero **afirmar
    eso** es justamente lo que un checker no debe hacer de sí mismo.  Acá se
    recalcula el óptimo desde cero, y el goloso del generador queda como una
    solución más a la que el checker no le cree nada.

    Costo: O(len(fibonacci) * objetivo) = unos 2,4 millones de pasos para este
    problema, o sea décimas de segundo, una sola vez por caso.
    """
    numeros = fibonacci_hasta(objetivo)
    # `best[s]` = mínimos sumandos que suman `s`.  El "infinito" es un valor que
    # ninguna suma puede alcanzar (nunca hacen falta más sumandos que `s`, porque
    # `1` es de Fibonacci), así que no hace falta importar nada para decirlo.
    infinito = objetivo + 1
    best = [0] + [infinito] * objetivo
    for numero in numeros:
        for suma in range(numero, objetivo + 1):
            candidato = best[suma - numero] + 1
            if candidato < best[suma]:
                best[suma] = candidato
    return best[objetivo]


def _verificar_modelo(judge_output, mejor):
    """La salida del modelo tiene que ser una representación **mínima** del objetivo.

    Esta función es la que le exige al **problema**: `check()` la llama antes de
    mirar la submission, y cualquier cosa que falle acá es un problema mal
    construido -- no una submission mala.  Por eso levanta `ValueError` en vez de
    devolver un `CheckerResult`: un error en el checker lo reporta el juez como
    error interno, que es exactamente la señal que quiero si los `.out` no son
    óptimos.

    `mejor` es el mínimo que `check()` ya calculó; se pasa en vez de recalcularlo
    porque el costo es O(len(fibonacci) * objetivo) y no hay razón para pagarlo
    dos veces por caso.

    La salida del modelo se parsea con la misma regla que la submission (la
    cantidad declarada tiene que coincidir con lo que viene), así que un `.out`
    mal formado se rechaza acá y no más tarde.
    """
    tokens = utf8text(judge_output).split()
    if not tokens:
        raise ValueError("la salida modelo está vacía: los .out no se generaron")
    cantidad = entero(tokens[0])
    if cantidad is None:
        raise ValueError(f"la salida modelo no empieza con un entero: {tokens[0][:16]!r}")
    sumandos = [entero(token) for token in tokens[1:]]
    if any(sumando is None for sumando in sumandos):
        raise ValueError(f"la salida modelo tiene un sumando ilegible: {tokens[1:4]!r}")
    if cantidad != len(sumandos):
        raise ValueError(
            f"la salida modelo declara {cantidad} sumandos y trae {len(sumandos)}"
        )
    numeros = fibonacci_hasta(OBJETIVO)
    if any(sumando not in numeros for sumando in sumandos):
        raise ValueError(f"la salida modelo tiene un sumando que no es de Fibonacci: {sumandos}")
    if sum(sumandos) != OBJETIVO:
        raise ValueError(
            f"la salida modelo suma {sum(sumandos)}, no {OBJETIVO}: los .out no representan "
            f"el objetivo"
        )
    if len(sumandos) != mejor:
        raise ValueError(
            f"la salida modelo usa {len(sumandos)} sumandos pero el mínimo para {OBJETIVO} es "
            f"{mejor}: los .out no son óptimos y el problema no puede dar puntaje completo"
        )


def check(process_output, judge_output, judge_input, point_value, submission_source, **kwargs):
    """Puntúa una representación subida como `.txt`.

    `judge_input` llega **vacío** y no se usa: este modelo no tiene inputs, y el
    objetivo es la constante `OBJETIVO` de arriba (ver el encabezado).  El
    parámetro queda en la firma porque es la firma que DMOJ llama
    (`dmoj/graders/standard.py:60-74`), no porque haya algo que leer.

    `submission_source` tampoco se usa: acá no se puntúa el tamaño del archivo.
    (El modelo `custom` documenta la receta de codegolf, que es el caso en que sí
    se usa.)

    Las tres bandas del enunciado, en orden:

    * una representación **mínima** del objetivo vale `point_value` completo;
    * una representación **válida pero no mínima** vale `PUNTAJE_PARCIAL`;
    * todo lo demás vale 0 -- y "todo lo demás" incluye la salida mal formada, un
      sumando que no es de Fibonacci, una cantidad fuera de ``1..TOPE`` y una
      suma que no llega al objetivo.

    El tercer grupo es la decisión interesante de este archivo.  El modelo
    `custom` tiene un "piso parcial" para la basura que sigue a una primera línea
    válida; acá **no lo hay**, y la diferencia no es de gusto sino de estructura:
    un problema `custom` tiene input, así que escribir una primera línea plausible
    significa haber entendido la instancia, y algo merece valer.  En este modelo
    `judge_input` está vacío y el objetivo es una constante: escribir «9» en la
    primera línea es gratis, no cuesta nada entenderlo, y premiarlo con 0.7 por
    caso regalaría el 70% de un problema sin resolverlo.  Por eso el piso parcial
    se saca, y la tabla del enunciado -- que dice 0 para lo mal formado -- es la
    que manda.

    Lo que sí se conserva es la **determinación**: cada rama de abajo devuelve un
    `CheckerResult` fijo y no depende de nada más que su entrada, así que el mismo
    archivo saca siempre el mismo puntaje.  Ninguna entrada produce una excepción.
    """
    # El mínimo se calcula una sola vez y se usa dos veces: para exigirle al
    # modelo y para puntuar la submission.  Es O(len(fibonacci) * objetivo) --
    # unas décimas de segundo acá -- y `check()` corre una vez por caso, así que
    # recalcularlo sería pagar dos veces por el mismo número.
    mejor = minimo(OBJETIVO)
    _verificar_modelo(judge_output, mejor)

    # `utf8text` decodifica en modo estricto, así que un output con bytes
    # inválidos levanta `UnicodeDecodeError` acá.  Eso lo maneja el juez, no el
    # checker: `dmoj/graders/standard.py:75-78` envuelve la llamada y convierte
    # ese error en `CheckerResult(False, 0, feedback='invalid unicode')`.  O sea
    # que un output con bytes basura da WA, no error interno -- que es lo
    # correcto -- y replicar ese `except` acá sería duplicar la política del juez
    # sobre el mismo caso.
    tokens = utf8text(process_output).split()
    if not tokens:
        return CheckerResult(False, 0.0, feedback="salida vacía")

    declarados = entero(tokens[0])
    if declarados is None:
        return CheckerResult(
            False, 0.0, feedback=f"la primera línea no es un entero: {tokens[0][:16]!r}"
        )
    if not 1 <= declarados <= TOPE:
        return CheckerResult(
            False,
            0.0,
            feedback=f"cantidad de sumandos fuera de rango: {declarados} (1..{TOPE})",
        )

    sumandos = [entero(token) for token in tokens[1:]]
    if any(sumando is None for sumando in sumandos):
        return CheckerResult(
            False, 0.0, feedback=f"la salida no es una lista de enteros: {tokens[1:4]!r}"
        )

    # El objeto que se valida es la lista que vino, no la cantidad declarada: si
    # no coinciden, el envío se contradice a sí mismo.
    if len(sumandos) != declarados:
        return CheckerResult(
            False,
            0.0,
            feedback=f"declara {declarados} sumandos pero manda {len(sumandos)}",
        )

    numeros = fibonacci_hasta(OBJETIVO)
    if any(sumando not in numeros for sumando in sumandos):
        return CheckerResult(
            False, 0.0, feedback=f"hay un sumando que no es de Fibonacci en {sumandos}"
        )

    # Adviértase el orden: primero «¿es una representación del objetivo?» y
    # después «¿es buena?».  Al revés, una suma que no llega al objetivo podría
    # colarse por tener pocos sumandos.
    if sum(sumandos) != OBJETIVO:
        return CheckerResult(
            False,
            0.0,
            feedback=f"los sumandos suman {sum(sumandos)}, no {OBJETIVO}",
        )

    # ── El objeto es una representación válida: recién ahora se juzga ────────
    # La calidad sale de la cantidad *validada*, que es lo que el objeto
    # realmente es.  Es el punto entero del modelo: el puntaje no se declara, se
    # mide.
    if declarados == mejor:
        return CheckerResult(True, point_value, feedback=f"óptimo: {mejor} sumandos")
    return CheckerResult(
        True,
        PUNTAJE_PARCIAL * point_value,
        feedback=f"representación válida pero no mínima: {declarados} sumandos, mínimo {mejor}",
    )
