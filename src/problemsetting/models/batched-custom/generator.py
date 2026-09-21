#!/usr/bin/env python3
"""Generador de casos para «Ronda» (plantilla del modelo `batched-custom`).

Este archivo combina una **escalera de subtareas** con un **checker de
calidad**, y por eso su orden de casos es una decisión de diseño y no una
convención.  El mecanismo de cada pieza por separado está documentado en su
plantilla -- los lotes y los puntajes por subtarea en
`models/batched/generator.py`, el checker de calidad en
`models/custom/checker.py` -- así que acá sólo se documenta lo que cambia al
combinarlas:

**El orden de los casos dentro de un lote decide cuánto puntaje parcial
sobrevive.**  El juez corta el lote apenas un caso no lo pasa
(`dmoj/judge.py:526-533`) y los casos siguientes quedan en `SC`, sin
ejecutarse.  Como el puntaje de un lote fraccionario es la fracción que sus
casos efectivamente ganaron, un caso que falla temprano *borra* el parcial de
todos los que no llegaron a correr.  Por eso los casos se generan **de mayor a
menor `n` dentro de cada subtarea**: la escalera pone primero lo que más pide,
que es lo que una solución insuficiente no puede resolver.  Invertir este orden
no rompe nada -- el problema sigue siendo válido -- pero cambia los puntajes de
`submissions.yml`, y por eso el archivo lo dice en vez de dejarlo implícito.

La escala de `n` que hace visible la interacción es `n <= 50`: una solución
correcta y subóptima que sólo cubre las rondas chicas gana la fracción de la
Subtarea 1 (`0.7 * 10 = 7`) y pierde el resto, porque en las demás subtareas el
primer caso es uno que no puede construir.  Ese `7` no es un número elegido:
es el producto de "cuánto vale el lote" por "qué fracción ganó cada caso que
alcanzó a correr".

El enunciado: dada una ronda de ~n~ posiciones en círculo, iluminarla con la
menor cantidad de faros.  Un faro ilumina las dos posiciones a cada lado, cinco
en total.  La solución óptima usa ~\\lceil n/5 \\rceil~ faros.

Las subtareas se definen por **restricciones sobre n**, y los casos se acumulan
hacia arriba: un caso de la Subtarea 1 también pertenece a la 2, la 3 y la 4,
así que una solución que sólo cubre las rondas chicas no puede "zafar" de las
grandes.

  ST1 (10 pts):  n <= 50.
  ST2 (20 pts):  n <= 2000.
  ST3 (30 pts):  n <= 50000.  Depende del lote 2 (ver `get_subtasks`).
  ST4 (40 pts):  n <= 200000, sin restricciones adicionales.

Estructura de los casos: por cada subtarea, sus tamaños límite y algunos
intermedios, en orden descendente.  No hay casos "aleatorios" a propósito: en
este problema la calidad de la construcción es lo que se puntúa, y una ronda de
tamaño al azar no agrega nada que un tamaño elegido no diga ya.
"""

import random

# ── Lo único que hay que tocar para otro problema ──────────────────────
#
#   1. `TestCase`: qué campos tiene un caso y cómo se escribe su input.
#   2. `TAMANOS_ST*`: qué casos se generan, en qué orden.
#   3. Las funciones `check_*`: a qué subtarea pertenece cada caso.
#   4. `Generator.get_subtasks`: cuánto vale cada subtarea y de cuáles depende.
#
# Lo demás (el protocolo que consume `problemsetting cases`) no se cambia.

# Semilla fija: con la misma semilla el generador produce exactamente los mismos
# casos, así que un problema es reproducible entre corridas y entre máquinas.
# Nunca uses `random.seed()` sin argumento ni `time.time()`: los casos cambiarían
# en cada build y los `.out` quedarían desincronizados de los `.in`.
SEMILLA = 20250921

# Límites de cada subtarea, como constantes para que los usen tanto los
# generadores como los clasificadores.  Una sola definición, un solo lugar donde
# cambiarla.
LIM_ST1 = 50
LIM_ST2 = 2000
LIM_ST3 = 50_000
LIM_ST4 = 200_000

# La restricción absoluta del enunciado.  Es la única que va en `check()`: vale
# para *cualquier* caso, incluidos los diminutos de `gen_small`.
N_MAX = LIM_ST4

# Tamaños de los casos, por subtarea y en orden descendente.  El orden es el
# punto (ver el encabezado): dentro de un lote, el caso más grande va primero,
# así que una solución que no puede con él falla antes de que sus casos chicos
# le acrediten la fracción.
#
# Los tamaños están puestos donde el corte entre subtareas significa algo: el
# límite de ST1 es 50 y el primer caso de ST2 es 51, así que una solución que
# sólo funciona hasta 50 pierde ST2 desde su primer caso.  Dentro de cada
# subtarea los tamaños bajan, para que el caso más exigente sea el primero.
TAMANOS_ST1 = (50, 47, 26, 20, 17, 11, 10, 7, 6)
TAMANOS_ST2 = (2000, 1001, 501, 51)
TAMANOS_ST3 = (50_000, 25_001, 2001)
TAMANOS_ST4 = (200_000, 150_000, 50_001)


class TestCase:
    """Un caso de prueba.

    Contrato que espera el toolkit:

    * ``check()``       -- valida las invariantes del caso.  Se llama desde
                           ``__init__``: un caso mal formado falla durante el
                           build y nunca llega al juez.
    * ``write_file(f)`` -- escribe el input del caso.  El nombre del archivo lo
                           elige el toolkit (``cases/{i}.in``), no el caso.

    El toolkit no impone nombres de atributos; sólo estos dos métodos.
    """

    def __init__(self, n):
        self.n = n
        self.check()

    def check(self):
        # La ronda tiene al menos una posición (con n = 0 no habría nada que
        # iluminar y el enunciado tendría que definir esa respuesta), y a lo
        # sumo N_MAX, la restricción absoluta del problema.
        assert 1 <= self.n <= N_MAX, f"n fuera de rango: {self.n}"

    def write_file(self, file):
        # El formato de entrada es una línea con `n` y nada más.  La solución
        # modelo (`solution.cpp`) y el checker (`checker.py`, `leer_n`) leen
        # exactamente esto.
        file.write(f"{self.n}\n")


def gen_tamanos(cases, tamanos):
    """Agrega un caso por tamaño, en el orden dado.

    Una sola función para las cuatro subtareas: los tamaños son lo único que
    cambia, y tenerlos en una tupla por subtarea deja el orden a la vista.
    """
    for n in tamanos:
        cases.append(TestCase(n))


# ── Clasificación por subtarea ────────────────────────────────────────
# ¡Atención! Estas funciones determinan a qué subtarea pertenece cada caso: al
# escribir init.yml, `problemsetting cases` incluye el caso en cada subtarea
# cuyo check devuelva True.  Por eso el check de la última subtarea es el que
# acepta todo -- así los casos se acumulan hacia arriba, que es la convención de
# este toolkit.
def check_st1(case):
    """ST1: la ronda tiene a lo sumo 50 posiciones."""
    return case.n <= LIM_ST1


def check_st2(case):
    """ST2: la ronda tiene a lo sumo 2000 posiciones."""
    return case.n <= LIM_ST2


def check_st3(case):
    """ST3: la ronda tiene a lo sumo 50000 posiciones."""
    return case.n <= LIM_ST3


def check_st4(case):
    """ST4: sin restricciones adicionales -- todo caso califica."""
    return True


class Generator:
    """Punto de entrada del generador.  El toolkit instancia esta clase.

    Protocolo:

    * ``get_cases()``    -- la lista *ordenada* de casos.  El índice en la lista
                            es el número de archivo: el caso ``i`` se escribe en
                            ``cases/{i}.in`` y su respuesta esperada en
                            ``cases/{i}.out``.
    * ``get_subtasks()`` -- una lista de ``(puntos, check_fn)`` o
                            ``(puntos, check_fn, dependencias)``.
    * ``gen_small(rand)``-- casos diminutos para `problemsetting stress`.

    El constructor recibe la semilla (`--seed` en las herramientas que lo
    permiten) y debe ser determinista para una semilla dada.
    """

    def __init__(self, seed=SEMILLA):
        # Un `random.Random` propio en vez del módulo global: no toca el estado
        # de nadie más que corra en el mismo proceso y hace explícita la semilla.
        self.random = random.Random(seed)

    def get_cases(self):
        # El orden *global* es descendente porque cada subtarea conserva el orden
        # de esta lista: los tamaños de ST4 van primero, después los de ST3, y
        # así hasta los chicos.  Así toda subtarea ve sus casos de mayor a menor
        # (ver el encabezado).
        cases = []
        gen_tamanos(cases, TAMANOS_ST4)
        gen_tamanos(cases, TAMANOS_ST3)
        gen_tamanos(cases, TAMANOS_ST2)
        gen_tamanos(cases, TAMANOS_ST1)
        return cases

    def get_subtasks(self):
        # (puntos, check) o (puntos, check, dependencias).  El caso entra en la
        # subtarea si check(case) es True.
        #
        # Las dependencias se aplican en el juez, no en el toolkit
        # (`dmoj/judge.py:506-508`): si el lote declarado no está en
        # `passed_batches`, todos los casos de este lote quedan en `SC` sin
        # ejecutarse.
        #
        # ST3 depende de [2] por la misma razón que en `batched`: sus casos son
        # los de ST2 más los grandes, así que si los medianos no pasan, los
        # grandes tampoco, y correrlos sólo gasta tiempo del juez.
        #
        # La interacción con el checker, que es lo que este modelo agrega: un
        # lote omitido por dependencia no ejecuta **ningún** caso, así que no
        # acredita fracción alguna.  ST3 no vale "un poco menos" cuando ST2
        # falla: vale 0, y sus casos ni siquiera llaman a `check()`.  Es la
        # diferencia entre un 0 por fracaso y un 0 por omisión, y el reporte de
        # `verify` la muestra (`SC`, distinto de `WA`).
        #
        # La última subtarea NO lleva dependencia a propósito: es la que acepta
        # todo y la que tiene que informar el estado real de la solución sobre
        # los casos del problema completo.  Los puntos suman 100.
        return [
            (10, check_st1),
            (20, check_st2),
            (30, check_st3, [2]),
            (40, check_st4),
        ]

    def gen_small(self, rand):
        # Casos diminutos para el stress test, donde el costo de una fuerza
        # bruta sería irrelevante.  El rango arranca en 6 por dos razones
        # concretas: `n <= 5` son las rondas donde el óptimo es un solo faro y
        # los casos de borde del enunciado asoman -- útiles en un problema de
        # conteo, pero acá no dicen nada sobre la calidad de una construcción --
        # y `n >= 6` deja a los casos diminutos dentro del rango donde las
        # submissions declaradas construyen algo válido.
        #
        # Este problema no declara `role: brute` (ver submissions.yml), así que
        # `problemsetting stress` no corre; el hook existe igual porque es parte
        # del protocolo del generador y porque es lo que un problema con brute
        # usaría sin cambios.
        return [TestCase(rand.randint(6, 60))]
