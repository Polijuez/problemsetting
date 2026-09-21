#!/usr/bin/env python3
"""Generador de casos para «Fibonacci(10^12) mód 10^5» (plantilla `output-only`).

Este archivo es una plantilla completa y funcionando.  A diferencia del modelo
`standard`, acá el envío **no es un programa**: el concursante sube un archivo
`.txt` con su respuesta.  DMOJ lo corre con el ejecutor `TEXT` (literalmente
`cat`, `dmoj/executors/TEXT.py`) y `StandardGrader` compara esa salida contra la
respuesta esperada, sin puntaje parcial.

Cuatro cosas cambian respecto de una plantilla normal, y son el punto de este
modelo:

1. **Los casos no tienen input.**  `init.yml` declara cada caso sólo con `out:`
   y sin `in:`; el juez le da al ejecutor un stdin vacío
   (`TestCase._make_input_data_io()` devuelve un `MemoryIO(seal=True)` cuando no
   hay `in:`, `dmoj/problem.py:489-493`).  Por eso `TestCase.write_file` de acá
   abajo *falla a propósito*: si algo intentara escribir un input para este
   modelo, quiero enterarme durante el build y no por un WA misterioso.

2. **La respuesta esperada no se calcula corriendo nada.**  `problemsetting
   outputs` copia `solution.txt` a `cases/{i}.out` en vez de compilar y ejecutar
   (Q11/plan: «output generation for these models is a file copy»).  El archivo
   `solution.txt` *es* la respuesta; el toolkit no tiene cómo verificarla por su
   cuenta.

3. **El generador y la solución buscada son artefactos distintos.**  Esto es lo
   que enseña la plantilla: el `Generator` de abajo *calcula* la respuesta con
   exponenciación de matrices en O(log n), pero ese cálculo es una herramienta
   **del autor**, no la solución del problema.  El concursante no puede subir un
   programa: el enunciado pide el número, y el número se obtiene fuera del juez
   (a mano, o con un programa que el concursante corre por su cuenta y del que
   sólo sube la salida).  Por eso este archivo no se parece a una solución, y no
   tiene que parecerse: nadie lo va a ejecutar dentro del juez.

4. **Un único caso.**  El mismo `.txt` se compara contra el `out:` de *todos* los
   casos, así que un segundo caso sólo podría repetir la misma respuesta.  Un
   problema output-only tiene una sola respuesta y por eso un solo caso; la
   división en subtareas no existe en este modelo (`batch: single`, todo o nada).

Lo único que hay que tocar para otro problema: `RESPUESTA` y las funciones
`gen_*`, igual que en cualquier otra plantilla.
"""

# ── Lo único que hay que tocar para otro problema ──────────────────────
#
#   1. `RESPUESTA`: qué número (o texto) pide el enunciado.
#   2. `TestCase`: la forma del caso -- acá no hay input, sólo la respuesta.
#   3. `Generator.get_subtasks`: cuánto vale el único lote (`single` = 100).
#
# El protocolo que consume `problemsetting cases` no se cambia: `check()` y
# `write_file(f)` tienen que existir, y `write_file` puede negarse si el modelo
# no tiene inputs.

#: Módulo del que se piden los últimos 5 dígitos: 10^5.
MODULO = 10**5

#: El índice del enunciado: F(10^12).
INDICE = 10**12


def fibonacci_mod(n, mod):
    """F(n) mód `mod`, por exponenciación de matrices en O(log n).

    [[F(n+1), F(n)], [F(n), F(n-1)]] = [[1, 1], [1, 0]] ** n.  Cada producto es
    de matrices 2x2, así que cuesta O(1), y hay O(log n) de ellos.

    Con n = 10^12 esto son ~40 pasos: instantáneo.  La recurrencia iterada, en
    cambio, son 10^12 sumas -- del orden de mil segundos a mil millones de sumas
    por segundo.  Por eso el enunciado pide el número y no un programa: el número
    se calcula afuera, con este método u otro equivalente, y lo que se sube es el
    resultado.

    `mod` entra en la recurrencia gracias a que la suma y el producto son
    compatibles con el resto: (a + b) % m y (a * b) % m se calculan desde a % m
    y b % m sin conocer a ni b.  Por eso los productos de abajo llevan `% mod`.
    """
    result = [[1, 0], [0, 1]]  # identidad
    base = [[1, 1], [1, 0]]
    while n:
        if n & 1:
            result = _multiply(result, base, mod)
        base = _multiply(base, base, mod)
        n >>= 1
    # El exponente 0 de la matriz da [[F(1), F(0)], [F(0), F(-1)]] = identidad,
    # es decir F(n) está en la esquina superior derecha.
    return result[0][1] % mod


def _multiply(left, right, mod):
    """Producto de dos matrices 2x2 mód `mod`, escrito sin construcciones raras."""
    return [
        [
            (left[0][0] * right[0][0] + left[0][1] * right[1][0]) % mod,
            (left[0][0] * right[0][1] + left[0][1] * right[1][1]) % mod,
        ],
        [
            (left[1][0] * right[0][0] + left[1][1] * right[1][0]) % mod,
            (left[1][0] * right[0][1] + left[1][1] * right[1][1]) % mod,
        ],
    ]


#: La respuesta del problema, ya formateada como la imprime `solution.txt`.
#:
#: `solution.txt` y esta constante tienen que decir lo mismo: `outputs` copia el
#: `.txt` sin mirarlo, así que si los dos se separan, los `.out` y el enunciado
#: dejan de coincidir y nadie se entera hasta que un concursante correcto saca
#: WA.  `tests/test_model_output_only.py` compara ambos, justamente porque el
#: toolkit no puede hacerlo solo.
#:
#: `:05d` porque el enunciado pide *cinco dígitos*: un resto de 4 dígitos se
#: imprime con un cero adelante.  Con la respuesta de este problema no se nota
#: (46875 ya tiene cinco), pero la regla se define ahora y no cuando aparezca el
#: primer caso con ceros.
RESPUESTA = f"{fibonacci_mod(INDICE, MODULO):05d}"


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
    """

    def __init__(self, answer):
        self.answer = answer
        self.check()

    def check(self):
        assert self.answer == RESPUESTA, (
            f"la respuesta del caso ({self.answer!r}) no es la que calcula el "
            f"generador ({RESPUESTA!r})"
        )
        assert self.answer.isdigit() and len(self.answer) == 5, (
            f"la respuesta tiene que ser exactamente 5 dígitos, no {self.answer!r}"
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
                            elemento: el mismo `.txt` se compara contra el `out:`
                            de cada caso, así que un segundo caso sería la misma
                            respuesta repetida.
    * ``get_subtasks()`` -- una lista de ``(puntos, check_fn)``.  `output-only`
                            es `batch: single`: un único lote que vale 100 y se
                            paga entero o no se paga.  Devolver más de un lote
                            haría que `problemsetting cases` rechace el build, en
                            vez de publicar en silencio un puntaje parcial que el
                            modelo no declara.
    * ``gen_small(rand)``-- **no se implementa, y no hace falta.**  La fuerza
                            bruta de `problemsetting stress` es una *submission*,
                            y en este modelo toda submission es un `.txt` con la
                            respuesta ya calculada: no hay dos programas que
                            puedan discrepar.  `stress` corta antes de buscar el
                            hook -- mira el modelo y reporta que un problema
                            output-only no tiene solución que comparar -- así que
                            no tener `gen_small` no cambia nada acá.

    El constructor recibe la semilla (`--seed` en las herramientas que lo
    permiten) y debe ser determinista para una semilla dada.  Esta plantilla es
    determinista sin usarla -- la respuesta es siempre el mismo número, no hay
    azar que sembrar -- pero acepta el argumento porque el protocolo se lo pasa
    a todo generador por igual.
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
        # Un único lote de 100 puntos que acepta todo: `output-only` es todo o
        # nada, así que no hay escalera de subtareas que armar.  El patrón
        # «el último check acepta todo» no se necesita acá porque no hay un
        # último con respecto a nada.
        return [
            (100, lambda case: True),
        ]
