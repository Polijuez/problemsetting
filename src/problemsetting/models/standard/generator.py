#!/usr/bin/env python3
"""Generador de casos para el problema «A+B» (plantilla del modelo `standard`).

Este archivo es una plantilla completa y funcionando.  A+B se usa como ejemplo
porque su formato de E/S es el mínimo posible: lo único que hay que mirar es la
*estructura* del generador.  Al escribir un problema propio, reemplazá la clase
`TestCase` y las funciones `gen_*` de abajo, y dejá intacto el resto.

El modelo `standard` es E/S por stdin/stdout y todo-o-nada: un único lote que
vale 100 puntos, y si falla un caso la submission deja de evaluarse y saca 0.
Para puntaje parcial hace falta el modelo `batched`, que arma una escalera de
lotes.

El input es una única línea con dos enteros ~a~ y ~b~; la salida es su suma
~a + b~.

Subtareas del enunciado (inclusivas: todo caso de ST1 también está en ST2):

  ST1 (30 pts): ~-1000 <= a, b <= 1000~.
  ST2 (70 pts): ~-10^9 <= a, b <= 10^9~, sin restricciones adicionales.

Ojo: en `standard` esos 30/70 son *didácticos* -- sirven para el enunciado y
para elegir los casos límite, pero el puntaje se paga una sola vez.  La
clasificación por subtarea (`check_st1` / `check_st2`, más abajo) es la misma
mecánica que `batched` usa para dar puntaje parcial de verdad.

Estructura de los casos: los ejemplos del enunciado y, por cada subtarea, sus
casos límite y casos aleatorios.
"""

import random

# ── Lo único que hay que tocar para otro problema ──────────────────────
#
#   1. `TestCase`: qué campos tiene un caso y cómo se escribe su input.
#   2. Las funciones `gen_*`: qué casos se generan, en qué orden y cuántos.
#   3. Las funciones `check_*`: a qué subtarea pertenece cada caso.
#   4. `Generator.get_subtasks`: cuánto vale cada subtarea.
#
# Lo demás (el protocolo que consume `problemsetting cases`) no se cambia.

# Semilla fija: con la misma semilla el generador produce exactamente los mismos
# casos, así que un problema es reproducible entre corridas y entre máquinas.
# Nunca uses `random.seed()` sin argumento ni `time.time()`: los casos cambiarían
# en cada build y los `.out` quedarían desincronizados de los `.in`.
SEMILLA = 3141592

# Límites de cada subtarea, como constantes para que los usen tanto los
# generadores como los clasificadores.  Una sola definición, un solo lugar donde
# cambiarla.
LIM_ST1 = 1000
LIM_ST2 = 10**9


class TestCase:
    """Un caso de prueba.

    Contrato que espera el toolkit:

    * ``check()``       -- valida las invariantes del caso.  Se llama desde
                           ``__init__``: un caso mal formado falla durante el
                           build y nunca llega al juez.  Es mucho más barato que
                           descubrirlo con un WA.
    * ``write_file(f)`` -- escribe el input del caso.  El nombre del archivo lo
                           elige el toolkit (``cases/{i}.in``), no el caso.

    El toolkit no impone nombres de atributos; sólo estos dos métodos.
    """

    def __init__(self, a, b):
        self.a = a
        self.b = b
        self.check()

    def check(self):
        assert -LIM_ST2 <= self.a <= LIM_ST2, f"a fuera de rango: {self.a}"
        assert -LIM_ST2 <= self.b <= LIM_ST2, f"b fuera de rango: {self.b}"

    def write_file(self, file):
        file.write(f"{self.a} {self.b}\n")


# ── Ejemplos visibles en el enunciado ─────────────────────────────────
# Se generan primero a propósito: quedan como cases/0.in, cases/1.in, ... y son
# los que conviene copiar al enunciado (media/statement.md).
def gen_ejemplos(cases):
    cases.append(TestCase(2, 3))     # 2 + 3 = 5
    cases.append(TestCase(-4, 7))    # -4 + 7 = 3


# ── Subtarea 1: ~-1000 <= a, b <= 1000~ ────────────────────────────────
def gen_st1(cases, rand):
    # Casos límite de la subtarea (también caen en ST2 por inclusión).
    cases.append(TestCase(0, 0))                # neutro aditivo
    cases.append(TestCase(LIM_ST1, LIM_ST1))    # máximo positivo
    cases.append(TestCase(-LIM_ST1, -LIM_ST1))  # mínimo negativo
    cases.append(TestCase(LIM_ST1, -LIM_ST1))   # cancelación exacta
    for _ in range(4):
        cases.append(TestCase(rand.randint(-LIM_ST1, LIM_ST1),
                              rand.randint(-LIM_ST1, LIM_ST1)))


# ── Subtarea 2: sin restricciones adicionales ──────────────────────────
def gen_st2(cases, rand):
    # Casos límite del problema completo, exclusivos de ST2: son los que
    # ejercitan los extremos del rango declarado, donde los errores de tipo y de
    # comparación aparecen.  La suma llega a ±2·10^9 -- entra por poco en un
    # `int` de 32 bits con signo, así que estos casos no lo castigan; están para
    # que los extremos queden cubiertos y para que el enunciado tenga sustancia.
    cases.append(TestCase(10**9, 10**9))        # suma máxima: 2·10^9
    cases.append(TestCase(-(10**9), -(10**9)))  # suma mínima: -2·10^9
    cases.append(TestCase(10**9, -(10**9)))     # suma nula en el extremo
    cases.append(TestCase(LIM_ST1 + 1, 0))      # justo fuera de ST1
    cases.append(TestCase(LIM_ST2, LIM_ST2 - 1))
    # Un operando grande acompaña a uno aleatorio, así la suma se acerca a los
    # extremos mucho más seguido que por puro azar.
    for _ in range(6):
        grande = rand.choice([LIM_ST2, -LIM_ST2, LIM_ST2 - rand.randint(0, 10)])
        cases.append(TestCase(grande, rand.randint(-LIM_ST2, LIM_ST2)))


# ── Clasificación por subtarea ────────────────────────────────────────
# ¡Atención! Estas funciones determinan a qué subtarea pertenece cada caso: al
# escribir init.yml, `problemsetting cases` incluye el caso en cada subtarea
# cuyo check devuelva True.  Por eso el check de la última subtarea es el que
# acepta todo -- así los casos se acumulan hacia arriba, que es la convención de
# este toolkit.  Editar una condición acá cambia la composición de los lotes (y
# con ello el puntaje de cada submission) sin tocar los casos en sí.
def check_st1(case):
    """ST1: ambos operandos dentro de ±1000."""
    return abs(case.a) <= LIM_ST1 and abs(case.b) <= LIM_ST1


def check_st2(case):
    """ST2: sin restricciones adicionales -- todo caso califica."""
    return True


class Generator:
    """Punto de entrada del generador.  El toolkit instancia esta clase.

    Protocolo:

    * ``get_cases()``    -- la lista *ordenada* de casos.  El índice en la lista
                            es el número de archivo: el caso ``i`` se escribe en
                            ``cases/{i}.in`` y su respuesta esperada en
                            ``cases/{i}.out``.  Reordenar cambia los nombres de
                            archivo, no la composición de los lotes.
    * ``get_subtasks()`` -- una lista de ``(puntos, check_fn)``.  El tercer
                            elemento es opcional y son las *dependencias*: una
                            lista de números de lote (1-based) que deben haberse
                            pasado completos para que este lote se evalúe; si no,
                            sus casos quedan en SC y no se corren.  Eso lo hace
                            el juez, no el toolkit.
    * ``gen_small(rand)``-- opcional: casos diminutos para `problemsetting
                            stress`, que compara la solución modelo contra una
                            fuerza bruta sobre muchos casos al azar.  Si el
                            problema no lo define, `stress` avisa que no puede
                            usarlo en vez de no hacer nada en silencio.

    El constructor recibe la semilla (`--seed` en las herramientas que lo
    permiten) y debe ser determinista para una semilla dada.
    """

    def __init__(self, seed=SEMILLA):
        # Un `random.Random` propio en vez del módulo global: no toca el estado
        # de nadie más que corra en el mismo proceso y hace explícita la semilla.
        self.random = random.Random(seed)

    def get_cases(self):
        cases = []
        gen_ejemplos(cases)
        gen_st1(cases, self.random)
        gen_st2(cases, self.random)
        return cases

    def get_subtasks(self):
        # (puntos, check).  El caso entra en la subtarea si check(case) es True.
        #
        # `standard` paga todo en un único lote, así que hay una sola entrada y
        # el check es el acepta-todo: es el mismo `check_st2` que usaría la
        # última subtarea de un problema con escalera de puntajes.  Si este
        # problema pasara al modelo `batched`, acá iría la escalera completa:
        #
        #   return [
        #       (30, check_st1),
        #       (70, check_st2),          # acepta todo: acumula hacia arriba
        #   ]
        #
        # y con una dependencia (el lote 2 sólo se corre si el lote 1 pasó
        # completo) el tercer elemento:
        #
        #   return [
        #       (30, check_st1),
        #       (70, check_st2, [1]),
        #   ]
        #
        # Ojo: `check_st1` no se usa para armar el lote de `standard`, pero sí
        # para describir ST1 en el enunciado y sigue siendo la primera pieza si
        # el problema se pasa a `batched`.
        return [
            (100, check_st2),
        ]

    def gen_small(self, rand):
        # Casos diminutos para el stress test: operandos en un rango chico,
        # donde una fuerza bruta tonta sirve de referencia honesta.  Devuelve una
        # lista porque en un problema real cada llamada genera un caso distinto.
        return [TestCase(rand.randint(-1000, 1000), rand.randint(-1000, 1000))]
