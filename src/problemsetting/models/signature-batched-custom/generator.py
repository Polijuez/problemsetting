#!/usr/bin/env python3
"""Generador de casos para «Ronda» (plantilla del modelo `signature-batched-custom`).

Este problema combina las tres piezas del toolkit que hasta acá venían de a dos:
una **escalera de subtareas**, un **checker de calidad** y una **interfaz de
firma**.  Cada pieza por separado está documentada en su plantilla:

  * los lotes, los puntajes por subtarea y las dependencias, en
    `models/batched/generator.py`;
  * el checker de calidad -- validar el objeto construido en vez de creerle al
    número declarado -- en `models/custom/checker.py`;
  * la composición de firma, el `#include` y el `#define main main_<uuid>` que
    agrega el juez, en `models/signature-batched/signature.hpp`.

Acá sólo se documenta lo que cambia al juntarlas, y hay una cosa que **sí**
cambia y es la razón de que este modelo exista aparte de `batched-custom`:

**Qué es «la salida» de la submission.**  En un problema de E/S, la submission
imprime su construcción y el checker la lee de `process_output`.  Acá la
submission **no imprime nada**: implementa una función que *recibe* el arreglo
donde tiene que escribir las posiciones y devuelve cuántas escribió.  El
evaluador -- el programa que el concursante no escribe -- es el que convierte
ese par (cantidad, arreglo) en las dos líneas de texto que el checker ya sabe
leer.  O sea que el formato de salida del problema es *del evaluador*, no del
concursante: si cambia el evaluador, cambia el formato para todos los casos (y
los `.out`).

Ese arreglo es también el único lugar donde la interfaz impone una obligación de
*memoria* y no sólo de tipos: el evaluador lo reserva con capacidad ~n~ y la
función tiene que escribir a lo sumo esa cantidad de enteros.  Está dicho en el
enunciado y en `signature.hpp` porque no es deducible de la firma.

La escalera y el checker son los mismos que los de `batched-custom`, y es
deliberado: el puntaje parcial de este problema (una fracción de cada lote que
los casos alcanzaron a correr) tiene que componerse igual que allá, así que la
única variable que cambia entre las dos plantillas es la interfaz.  El puntaje
de una submission **no** es «0.7 del problema»: es `0.7` por el puntaje del lote
de cada caso, y por eso `submissions.yml` lleva números medidos.

El enunciado: dada una ronda de ~n~ posiciones en círculo, iluminarla con la
menor cantidad de faros.  Un faro ilumina las dos posiciones a cada lado, cinco
en total.  La solución óptima usa ~\\lceil n/5 \\rceil~ faros.

  ST1 (10 pts):  n <= 50.
  ST2 (20 pts):  n <= 2000.
  ST3 (30 pts):  n <= 50000.  Depende del lote 2 (ver `get_subtasks`).
  ST4 (40 pts):  n <= 200000, sin restricciones adicionales.

Estructura de los casos: por cada subtarea, sus tamaños límite y algunos
intermedios, en orden descendente.  El orden es una decisión de diseño -- ver
`get_cases` -- y no una convención.
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
SEMILLA = 20250922

# Límites de cada subtarea, como constantes para que los usen tanto los
# generadores como los clasificadores.  Una sola definición, un solo lugar donde
# cambiarla.
LIM_ST1 = 50
LIM_ST2 = 2000
LIM_ST3 = 50_000
LIM_ST4 = 200_000

# La restricción absoluta del enunciado.  Es la única que va en `check()`: vale
# para *cualquier* caso, incluidos los diminutos de `gen_small`.  Es también la
# capacidad del arreglo que el evaluador le pasa a la función: el concursante
# puede escribir a lo sumo `n` posiciones.
N_MAX = LIM_ST4

# Tamaños de los casos, por subtarea y en orden descendente.  El orden importa
# (ver `get_cases`): dentro de un lote, el caso más grande va primero, así que una
# solución que no puede con él falla antes de que sus casos chicos le acrediten la
# fracción.
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
        # El formato de entrada es una línea con `n` y nada más.  Quien lo lee es
        # el evaluador `evaluator.cpp`, que reserva el arreglo de esa capacidad y
        # llama a la función con él; el checker vuelve a leerlo desde
        # `judge_input` para recalcular el óptimo.
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
# este toolkit: un caso de ST1 también está en ST2, ST3 y ST4, de modo que una
# solución que sólo cubre los chicos no puede "zafar" de los grandes.
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
        # así hasta los chicos.  Así toda subtarea ve sus casos de mayor a menor,
        # que es lo que hace que una solución insuficiente falle temprano en cada
        # lote en vez de juntar la fracción de los casos que sí podía.
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
        # ST3 depende de [2] porque sus casos son los de ST2 más los grandes: si
        # los medianos no pasan, tampoco van a pasar los de 50000, y correrlos
        # sólo gasta tiempo del juez.  La última subtarea NO lleva dependencia a
        # propósito: es la que acepta todo y la que tiene que informar el estado
        # real de la solución sobre los casos del problema completo.  Los puntos
        # suman 100.
        return [
            (10, check_st1),
            (20, check_st2),
            (30, check_st3, [2]),
            (40, check_st4),
        ]

    def gen_small(self, rand):
        # Casos diminutos para el stress test, donde el costo de una fuerza bruta
        # sería irrelevante.  El rango arranca en 6 por dos razones concretas:
        # `n <= 5` son las rondas donde el óptimo es un solo faro y los casos de
        # borde del enunciado asoman -- útiles en un problema de conteo, pero acá
        # no dicen nada sobre la calidad de una construcción -- y `n >= 6` deja a
        # los casos diminutos dentro del rango donde las submissions declaradas
        # construyen algo válido.
        #
        # Este problema no declara `role: brute` (ver submissions.yml), así que
        # `problemsetting stress` no corre; el hook existe igual porque es parte
        # del protocolo del generador y porque es lo que un problema con brute
        # usaría sin cambios.
        return [TestCase(rand.randint(6, 60))]
