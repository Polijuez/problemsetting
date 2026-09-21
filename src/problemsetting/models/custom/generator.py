#!/usr/bin/env python3
"""Generador de casos para el problema «Faros» (plantilla del modelo `custom`).

Este archivo es una plantilla completa y funcionando.  «Faros» es un problema de
**optimización**: hay que construir un objeto (un conjunto de posiciones) que
cumpla una condición, y la calidad de lo construido decide el puntaje.  Es el
ejemplo mínimo que muestra las dos piezas que distinguen a `custom` de
`standard`: un `checker.py` que valida la construcción, y `CheckerResult` con
puntaje fraccionario.

El modelo `custom` es E/S por stdin/stdout y **un solo lote**: el toolkit rechaza
una escalera de subtareas acá (ver `cases._check_model_supports`), porque emitir
varios lotes convertiría un problema todo-o-nada en puntaje parcial por lotes sin
decirlo.  El puntaje parcial de `custom` viene del *checker*, no de la estructura
de lotes: si querés las dos cosas, el modelo es `batched-custom`.

Para puntaje parcial por subtareas hace falta el modelo `batched`; para puntaje
parcial por calidad, este.

El input es una única línea con un entero ~n~: una ronda de ~n~ posiciones en
círculo, numeradas ~1..n~.  La salida es:

    K              el número de faros que la submission dice haber colocado
    b_1 ... b_K    las posiciones de esos faros, en cualquier orden

Un faro en la posición ~i~ ilumina ~i~, ~i-1~ e ~i+1~ (en círculo: el vecino de
~n~ es ~1~).  Todo el círculo tiene que quedar iluminado, y se gana el puntaje
completo con la **menor cantidad posible** de faros: ~\\lceil n/3 \\rceil~.

Por qué el círculo es divisible por 3 en todos los casos: con ~3 \\mid n~ el
óptimo es exactamente ~n/3~ y los faros en ~2, 5, 8, \\dots, n-1~ lo alcanzan sin
ningún caso especial.  Eso mantiene la solución modelo y la fuerza bruta
chiquitas, que es justamente lo que esta plantilla quiere mostrar: el tema es el
checker, no el problema.  La solución modelo igual maneja cualquier ~n~
(parchea el último faro si hace falta), porque el enunciado no promete nada.

Estructura de los casos: los ejemplos del enunciado y un puñado de rondas de
tamaños distintos.  La ronda es simétrica, así que un caso queda determinado por
~n~: la variedad está en el tamaño.
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
SEMILLA = 20250920

# Tamaños usados.  Todos múltiplos de 3 (ver el encabezado) y ninguno menor que
# 6, por dos razones concretas:
#
#   * con n = 3 el único conjunto óptimo es {2}, y la submission «un faro de más»
#     de submissions/ (uno en cada posición par) también da 1 -- o sea sería
#     óptima y sacaría puntaje completo, no el parcial que el manifest declara;
#   * con n chico el problema se resuelve mirando, y los casos no dicen nada.
#
# Los tamaños elegidos hacen que esa submission quede *siempre* en la banda
# parcial: su costo es n/2, el óptimo es n/3, y n/3 < n/2 <= 2·(n/3) para todo
# n >= 1.  El comentario del manifest explica por qué eso importa.
TAMANOS = (6, 9, 12, 15, 18)

#: La restricción absoluta del enunciado, la que sí vale para *cualquier* caso,
#: incluidos los diminutos de `gen_small`.  Es la única que va en `check()`.
N_MAX = 18

# La premisa de `TAMANOS`, verificada donde vive la constante y no caso por caso.
# Es una aserción sobre el *generador*, no sobre un caso: `gen_small` produce a
# propósito tamaños que no la cumplen (n=1..9, donde un error de borde asoma), y
# una restricción que se aplicara a todo TestCase los haría imposibles.
assert TAMANOS and all(n % 3 == 0 and 6 <= n <= N_MAX for n in TAMANOS), (
    "los tamaños del problema tienen que ser múltiplos de 3 entre 6 y N_MAX: es la "
    "premisa de la banda de puntaje parcial que declara submissions.yml"
)


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

    def __init__(self, n):
        self.n = n
        self.check()

    def check(self):
        # Sólo la restricción del *enunciado*, que vale para todo caso -- incluidos
        # los de `gen_small`.  Lo específico de los tamaños que este problema usa
        # (múltiplos de 3, >= 6) es una propiedad de `TAMANOS` y se verifica
        # arriba, junto a la constante; meterla acá haría que `gen_small` no
        # pudiera generar los tamaños chicos, que son justamente donde un error
        # de índice aparece.
        assert 1 <= self.n <= N_MAX, f"n fuera de rango: {self.n}"

    def write_file(self, file):
        file.write(f"{self.n}\n")


# ── Ejemplos visibles en el enunciado ─────────────────────────────────
# Se generan primero a propósito: quedan como cases/0.in, cases/1.in, ... y son
# los que conviene copiar al enunciado (media/statement.md).
def gen_ejemplos(cases):
    cases.append(TestCase(6))    # óptimo: 2 faros (2 y 5)
    cases.append(TestCase(9))    # óptimo: 3 faros (2, 5 y 8)


# ── Rondas por tamaño ─────────────────────────────────────────────────
def gen_rondas(cases, rand):
    # Un caso por tamaño, más un par de repeticiones: la ronda es simétrica, así
    # que repetir un tamaño no agrega instancias nuevas, pero sí cubre el camino
    # del checker con el mismo n en posiciones de caso distintas.
    for n in TAMANOS:
        cases.append(TestCase(n))
    for _ in range(3):
        cases.append(TestCase(rand.choice(TAMANOS)))


# ── Clasificación por subtarea ────────────────────────────────────────
# ¡Atención! Estas funciones determinan a qué subtarea pertenece cada caso: al
# escribir init.yml, `problemsetting cases` incluye el caso en cada subtarea
# cuyo check devuelva True.  Como `custom` es `batch: single`, hay una sola
# subtarea y su check es el acepta-todo: los casos se acumulan hacia arriba, que
# es la convención de este toolkit.
def check_puntaje_completo(case):
    """El único lote de `custom` acepta todos los casos."""
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
                            el juez, no el toolkit.  En `custom` hay un solo
                            lote, así que no hay dependencias que declarar.
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
        gen_rondas(cases, self.random)
        return cases

    def get_subtasks(self):
        # (puntos, check).  El caso entra en la subtarea si check(case) es True.
        #
        # `custom` paga todo en un único lote de 100 puntos, igual que
        # `standard`: la diferencia no está acá sino en el checker, que devuelve
        # `CheckerResult` con puntaje fraccionario.  Si este problema pasara al
        # modelo `batched-custom`, acá iría la escalera completa con su tercer
        # elemento de dependencias (ver el modelo `batched`).
        return [
            (100, check_puntaje_completo),
        ]

    def gen_small(self, rand):
        # Casos diminutos para el stress test: acá sí cualquier n, incluidos los
        # que no son múltiplos de 3 y los muy chicos -- el stress compara la
        # solución modelo contra la fuerza bruta, no el puntaje, así que las
        # restricciones de TAMANOS (que existen para que la banda parcial sea
        # estable) no aplican.  Justamente son los tamaños donde un error de
        # borde asoma: n = 1 (el vecino de 1 es 1 mismo), n = 2 y n = 3.
        return [TestCase(rand.randint(1, 9))]
