#!/usr/bin/env python3
"""Generador de casos para «100000 como suma de Fibonacci» (plantilla `output-only-custom`).

Este archivo es una plantilla completa y funcionando.  El modelo es el cruce de
dos ejes: el envío **no es un programa** (es un archivo `.txt`, como en
`output-only`) y además hay un **checker** que *puntúa* ese texto en vez de
compararlo por igualdad (como en `custom`).

El ejecutor que corre un `.txt` es `TEXT` (`dmoj/executors/TEXT.py`: `cat`), así
que el contenido del archivo es la salida de la submission, literalmente.  Lo que
cambia respecto de `output-only` es qué se hace con esa salida:

* `output-only` la compara contra el `out:` del caso y paga todo o nada.
* `output-only-custom` la pasa por `checker.py`, que **valida la estructura y
  puntúa la calidad** de lo que se subió: `CheckerResult(True, 0.7 * point_value)`
  es un puntaje parcial real (`dmoj/graders/standard.py:36-40` toma el veredicto de
  `passed` y el puntaje de `points`, sin importar que sea fraccionario).

Cuatro cosas hay que entender de este modelo, y son el punto de la plantilla:

1. **Los casos no tienen input.**  `init.yml` declara cada caso sólo con `out:` y
   sin `in:`; el juez le da al ejecutor un stdin vacío
   (`TestCase._make_input_data_io()` devuelve un `MemoryIO(seal=True)` cuando no
   hay `in:`, `dmoj/problem.py:489-493`).  Por eso `TestCase.write_file` de acá
   abajo *falla a propósito*: si algo intentara escribir un input para este
   modelo, quiero enterarme durante el build y no por un WA misterioso.

2. **El checker recibe un `judge_input` vacío**, así que el objetivo del problema
   no puede venir del caso: es una **constante del problema** (`OBJETIVO`, acá
   abajo, y la misma constante en `checker.py`).  Es la diferencia estructural
   entre este modelo y un problema con checker normal, donde `checker.py` lee del
   input la instancia que tiene que validar.

3. **Un único caso, y por una razón distinta que en `output-only`.**  El mismo
   `.txt` se corre contra *todos* los casos, y con un `judge_input` vacío el
   checker no puede distinguir un caso de otro: un segundo caso sería el mismo
   objetivo repetido.  Que este modelo tenga checker no lo habilita a tener
   varios casos -- al revés, lo obliga a que el objetivo sea uno solo.

4. **La salida esperada no se calcula corriendo nada.**  `problemsetting outputs`
   copia `solution.txt` a `cases/{i}.out` en vez de compilar y ejecutar.  El
   archivo `solution.txt` *es* la respuesta, y el checker la usa como referencia
   del modelo: comprueba que sea una representación **mínima** de verdad, porque
   si no lo fuera los `.out` estarían mal y ninguna submission podría sacar
   puntaje completo.

Lo único que hay que tocar para otro problema: `OBJETIVO`, `RESPUESTA` y la forma
de `TestCase`, igual que en cualquier otra plantilla.
"""

# ── Lo único que hay que tocar para otro problema ──────────────────────
#
#   1. `OBJETIVO`: el número que el enunciado pide representar.
#   2. `TestCase`: la forma del caso -- acá no hay input, sólo la respuesta.
#   3. `Generator.get_subtasks`: cuánto vale el único lote (`single` = 100).

#: El número que hay que representar como suma de números de Fibonacci.  Tiene
#: que coincidir con el de `checker.py` -- el test de la plantilla compara los
#: dos, porque el toolkit no puede hacerlo solo (uno corre acá, durante el
#: build, y el otro corre dentro del juez, durante el grading).
OBJETIVO = 100000

#: Cuántos sumandos acepta el enunciado como máximo.  Es un techo *publicado*:
#: sin él, "pocos sumandos" no sería una meta alcanzable y el puntaje parcial no
#: tendría forma.  `checker.py` define el mismo número para rechazar lo que se
#: pase de acá.
TOPE = 20

#: Módulo del que se piden los números: acá se usan los Fibonacci con
#: F(1) = 1, F(2) = 2 (la convención del enunciado, que es la de DMOJ y la de
#: `ZEckendorf`).  No hay F(0) = 0 en la lista a propósito: sumar ceros no
#: cambiaría el objetivo y sólo inflaría la cantidad de sumandos.


def fibonacci_hasta(limite):
    """Los números de Fibonacci ``1, 2, 3, 5, 8, ...`` que no superan ``limite``.

    Arranca en ``1, 2`` y no en ``0, 1``: el enunciado define ``F(1) = 1`` y
    ``F(2) = 2``.  Con ``0`` en la lista, cualquier representación se podría
    rellenar con ceros y la cantidad de sumandos dejaría de ser una medida.
    """
    numeros = []
    anterior, actual = 1, 2
    while anterior <= limite:
        numeros.append(anterior)
        anterior, actual = actual, anterior + actual
    return numeros


def zeckendorf(objetivo, numeros):
    """Representación *mínima* de ``objetivo`` por el algoritmo goloso.

    El teorema de Zeckendorf dice que todo entero positivo se escribe como suma
    de Fibonacci **distintos** sin dos consecutivos, y que el goloso -- tomar
    siempre el mayor que entra -- da exactamente esa representación.  Acá se
    permite repetir sumandos, así que hay que tener el cuidado de que el mínimo
    con repeticiones siga siendo el de Zeckendorf: es lo que el test de la
    plantilla verifica con una programación dinámica **independiente** de esta
    función, y lo que `checker.py` vuelve a verificar en cada corrida.

    Devuelve los sumandos de mayor a menor.  ``numeros`` viene de
    :func:`fibonacci_hasta`.
    """
    restante = objetivo
    sumandos = []
    for numero in reversed(numeros):
        if numero <= restante:
            sumandos.append(numero)
            restante -= numero
    assert restante == 0, f"{objetivo} no se pudo representar: sobró {restante}"
    return sumandos


#: Los sumandos de la respuesta del problema, de mayor a menor.
SUMANDOS = zeckendorf(OBJETIVO, fibonacci_hasta(OBJETIVO))

#: La respuesta del problema, formateada como la va a subir el concursante y como
#: la imprime `solution.txt`: la cantidad de sumandos en la primera línea y los
#: sumandos en la segunda, separados por espacios.
#:
#: `solution.txt` y esta constante tienen que decir lo mismo: `outputs` copia el
#: `.txt` sin mirarlo, así que si los dos se separan, los `.out` dejan de
#: coincidir con el enunciado y nadie se entera hasta que un concursante
#: correcto saca WA.  `tests/test_model_output_only_custom.py` compara ambos,
#: justamente porque el toolkit no puede hacerlo solo.
RESPUESTA = f"{len(SUMANDOS)}\n" + " ".join(str(n) for n in SUMANDOS) + "\n"


def es_fibonacci(valor, numeros):
    """True si ``valor`` es uno de los números de Fibonacci admisibles."""
    return valor in numeros


class TestCase:
    """Un caso de prueba: en este modelo, «la respuesta de este problema».

    Contrato que espera el toolkit (el mismo que en `standard`):

    * ``check()``       -- valida las invariantes del caso.  Se llama desde
                           ``__init__``, durante el build.
    * ``write_file(f)`` -- escribe el input del caso.

    La diferencia con `standard` es que acá **no hay input que escribir**:
    ``init.yml`` no declara `in:` para ninguno de estos casos, así que el toolkit
    nunca llama a ``write_file`` (lo saltea cuando el modelo es output-only).  El
    método existe porque el protocolo lo pide, y falla ruidosamente en vez de
    escribir un archivo vacío: un input vacío es una cosa, y «este problema no
    tiene inputs» es otra, y confundirlas es exactamente el bug que este modelo
    no debe permitirse.

    ``check()`` no se limita a comparar contra ``RESPUESTA``: valida la
    *estructura* de la respuesta, que es lo que el checker va a exigirle a las
    submissions.  Una plantilla cuya respuesta no pase su propio checker sería
    una plantilla que publica un problema irresoluble.
    """

    def __init__(self, answer):
        self.answer = answer
        self.check()

    def check(self):
        numeros = fibonacci_hasta(OBJETIVO)
        lineas = self.answer.split()
        assert len(lineas) >= 2, (
            f"la respuesta tiene que tener una cantidad y al menos un sumando, "
            f"no {self.answer!r}"
        )
        cantidad = int(lineas[0])
        sumandos = [int(token) for token in lineas[1:]]
        assert cantidad == len(sumandos), (
            f"la respuesta declara {cantidad} sumandos y trae {len(sumandos)}"
        )
        assert 1 <= cantidad <= TOPE, (
            f"la respuesta usa {cantidad} sumandos; el enunciado acepta entre 1 y {TOPE}"
        )
        assert all(es_fibonacci(sumando, numeros) for sumando in sumandos), (
            f"hay un sumando que no es de Fibonacci en {sumandos!r}"
        )
        assert sum(sumandos) == OBJETIVO, (
            f"los sumandos suman {sum(sumandos)}, no {OBJETIVO}"
        )
        # La minimalidad también se exige acá, y no sólo en el checker, porque el
        # checker corre **dentro del juez**: si `solution.txt` fuera válido pero
        # no mínimo, `build` terminaría sin decir nada, el juez puntuaría cada
        # submission con el `ValueError` de `_verificar_modelo` y el autor vería
        # submissions sin calificar en vez de un error en el build.  El caso
        # exacto que atrapa es el que el test de la plantilla escribe a mano:
        # partir el mayor sumando y dejar la suma intacta.
        optimo = len(zeckendorf(OBJETIVO, numeros))
        assert cantidad == optimo, (
            f"la respuesta usa {cantidad} sumandos pero el mínimo para {OBJETIVO} es "
            f"{optimo}: los `.out` se copian de solution.txt, así que una respuesta no "
            f"mínima deja al checker sin referencia y ninguna submission puede calificar"
        )

    def write_file(self, file):
        raise AssertionError(
            "los casos de un problema output-only no tienen input: init.yml los "
            "declara sólo con `out:` y el juez les da un stdin vacío"
        )


class Generator:
    """Punto de entrada del generador.  El toolkit instancia esta clase.

    Protocolo (idéntico al de los modelos con programa, salvo `gen_small`):

    * ``get_cases()``    -- la lista *ordenada* de casos.  Acá es de un solo
                            elemento: el mismo `.txt` se corre contra el `out:` de
                            cada caso, y el checker no tiene input del que sacar
                            otro objetivo, así que un segundo caso sería el mismo
                            problema repetido.
    * ``get_subtasks()`` -- una lista de ``(puntos, check_fn)``.  `output-only-custom`
                            es `batch: single`: un único lote que vale 100.  El
                            puntaje parcial de este problema viene del **checker**,
                            no de una escalera de lotes; si querés las dos cosas,
                            el modelo es `batched-custom`.
    * ``gen_small(rand)``-- **no se implementa, y no hace falta.**  La fuerza
                            bruta de `problemsetting stress` es una *submission*,
                            y en este modelo toda submission es un `.txt` con una
                            respuesta ya construida: no hay dos programas que
                            puedan discrepar.  `stress` corta antes de buscar el
                            hook -- mira el modelo y reporta que un problema
                            output-only no tiene solución que comparar -- así que
                            no tener `gen_small` no cambia nada acá.

    El constructor recibe la semilla (`--seed` en las herramientas que lo
    permiten) y debe ser determinista para una semilla dada.  Esta plantilla es
    determinista sin usarla -- la respuesta es siempre la misma representación,
    no hay azar que sembrar -- pero acepta el argumento porque el protocolo se lo
    pasa a todo generador por igual.
    """

    def __init__(self, seed=None):
        # El argumento se acepta y no se guarda a propósito: no hay ninguna
        # decisión al azar que pueda depender de él, así que una semilla distinta
        # no puede dar un problema distinto.  Ignorarlo en silencio es correcto
        # acá; guardarlo en un atributo que nadie lee sugeriría lo contrario.
        pass

    def get_cases(self):
        return [TestCase(RESPUESTA)]

    def get_subtasks(self):
        # Un único lote de 100 puntos que acepta todo: el problema no tiene
        # escalera de subtareas, y su puntaje parcial lo reparte el checker.
        return [
            (100, lambda case: True),
        ]
