#!/usr/bin/env python3
"""Generador de casos para «subpalíndromo más largo» (plantilla del modelo
`signature-batched`).

Este archivo es una plantilla completa y funcionando.  Al escribir un problema
propio, reemplazá la clase `TestCase` y las funciones `gen_*` de abajo, y dejá
intacto el resto (el protocolo que consume `problemsetting cases`).

El modelo `signature-batched` es E/S por stdin/stdout **con subtareas** y con el
grader de firma: cada subtarea es un *lote* (batch) de DMOJ con su propio
puntaje, y un lote paga sólo si *todos* sus casos son correctos.  A diferencia de
`standard`, acá el puntaje parcial existe de verdad: una solución que sólo cubre
los casos chicos se lleva los puntos de los lotes chicos.

La diferencia con el modelo `batched` es *qué* escribe el concursante: acá no
escribe un programa entero sino **una función**, declarada en `signature.hpp`, y
el evaluador `evaluator.cpp` se encarga de leer la entrada, llamarla e imprimir
el resultado.  La función se puede implementar en **C o en C++**: el mecanismo es
el mismo en los dos (ver `signature.hpp`), y lo único que elige el autor es el
lenguaje de su solución modelo (`solutionlang`).  El contenido y la escalera de
subtareas son deliberadamente los mismos que los de la plantilla `batched` --
ver el comentario de `signature.hpp` y de `evaluator.cpp` -- así que las dos
plantillas son comparables línea a línea salvo por la interfaz.

El enunciado: dada una cadena `s` de letras minúsculas, se pide la longitud del
substring contiguo más largo que sea palíndromo.  La función que ve el
concursante recibe `s` y devuelve un `int`.

Las subtareas se definen por **restricciones sobre N = |s|**, no por clases de
complejidad con nombre ("O(N^2)", "lineal", ...).  Es la misma escalera que
usaría un problema real, y es la que hace que el puntaje parcial sea una
afirmación sobre *cuánto input aguanta* la solución:

  ST1 (20 pts): N <= 50.
  ST2 (25 pts): N <= 1000.
  ST3 (25 pts): N <= 5000.  Depende del lote 2 (ver más abajo).
  ST4 (30 pts): N <= 10^5, sin restricciones adicionales.

Por qué esta escalera es el contenido pedagógico del problema y NO un defecto a
"arreglar": con N <= 50 una fuerza bruta cúbica O(N^3) entra de sobra; con
N <= 10^5 ya no, y una solución cuadrática O(N^2) (la típica expansión alrededor
de cada centro) se cae en ST4, donde sólo una solución lineal (Manacher) entra en
el límite de 1 s.  El problema está *diseñado* para que se vea esa separación, así
que sus casos límite incluyen a propósito cadenas uniformes ("aaaa..."), que son
las que llevan a la cuadrática a su peor caso (con las alternantes "abab..." de
acompañamiento: su respuesta es larguísima -- N o N-1 -- pero su expansión es
barata, así que cubren la forma "casi palíndromo" sin cargar el tiempo).  Si
"mejorás" el generador sacando esos casos, dejás de tener un problema de
subtareas y los puntajes esperados de submissions.yml dejan de significar nada.

Dónde cae la cuadrática depende del lenguaje, y en este problema eso no es
teórico: la plantilla `batched` (mismo enunciado, misma escalera) se corta en
Python ya en ST2, mientras que en los dos lenguajes que este modelo acepta -- C
y C++ -- la cuadrática pasa ST1, ST2 y ST3 enteras y sólo se cae en el caso
uniforme de 10^5 de ST4.  Lo mismo vale para la lineal: los `.out` que produce
`solution.c` y los que produce `solution.cpp` tienen que coincidir, y si no
coinciden el problema está mal armado, no "el lenguaje es distinto".  Es el
motivo por el que los `score` de submissions.yml salen de una corrida real de
`problemsetting verify` y no de copiar los de la otra plantilla.  Los cortes no
se eligieron a ojo: están puestos donde una corrida real mostró la separación, y
si cambiás el `tl` de meta.yml tenés que volver a ubicarlos así.
"""

import random

# ── Lo único que hay que tocar para otro problema ──────────────────────
#
#   1. `TestCase`: qué campos tiene un caso y cómo se escribe su input.
#   2. Las funciones `gen_*`: qué casos se generan, en qué orden y cuántos.
#   3. Las funciones `check_*`: a qué subtarea pertenece cada caso.
#   4. `Generator.get_subtasks`: cuánto vale cada subtarea y de cuáles depende.
#
# Lo demás (el protocolo que consume `problemsetting cases`) no se cambia.

# Semilla fija: con la misma semilla el generador produce exactamente los mismos
# casos, así que un problema es reproducible entre corridas y entre máquinas.
# Nunca uses `random.seed()` sin argumento ni `time.time()`: los casos cambiarían
# en cada build y los `.out` quedarían desincronizados de los `.in`.
SEMILLA = 20240920

# Límites de cada subtarea, como constantes para que los usen tanto los
# generadores como los clasificadores.  Una sola definición, un solo lugar donde
# cambiarla.
LIM_ST1 = 50
LIM_ST2 = 1000
LIM_ST3 = 5000
LIM_ST4 = 100_000

# Alfabeto de los casos.  Con dos letras alcanza: hace natural el caso
# adversarial (un solo carácter repetido, donde *todos* los substrings son
# palíndromos) y mantiene el enunciado legible.  Un alfabeto más grande sólo
# volvería las cadenas aleatorias "más fáciles" sin agregar nada.
ALFABETO = "ab"


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

    def __init__(self, s):
        self.s = s
        self.check()

    def check(self):
        # `n >= 1`: el enunciado pide el substring palindrómico más largo de una
        # cadena no vacía.  Permitir la cadena vacía obligaría a definir su
        # respuesta (0) en el enunciado y agregaría un caso de borde que no
        # enseña nada sobre la complejidad, que es lo que este problema evalúa.
        assert 1 <= len(self.s) <= LIM_ST4, f"largo fuera de rango: {len(self.s)}"
        assert all(c in ALFABETO for c in self.s), f"caracteres fuera del alfabeto: {self.s!r}"

    def write_file(self, file):
        # El formato de entrada es una línea con la cadena y nada más.  Quien lo
        # lee es el evaluador `evaluator.cpp`, que luego llama a la función.
        file.write(self.s + "\n")


# ── Ayudas de generación ──────────────────────────────────────────────
# Tres formas de cadena, cada una con un papel distinto:
#   * uniforme    -- "aaaa...": todos los substrings son palíndromos, así que
#                    ninguna solución puede "escapar" temprano.  Es *el* peor
#                    caso de la expansión alrededor de cada centro (cuadrática) y
#                    de la fuerza bruta cúbica, y por eso carga todo el peso
#                    adversarial de la escalera.
#   * alternante  -- "abab...": respuesta N (impar) o N-1 (par), o sea un
#                    palíndromo larguísimo, pero de expansión baratísima: cada
#                    centro para en uno o dos pasos.  Está para cubrir la forma
#                    "casi palíndromo" y porque su salida es un caso de borde
#                    (un palíndromo par nunca puede ser de largo N).
#   * aleatoria   -- respuesta corta y muy por debajo del peor caso; sirve para
#                    cubrir el "caso promedio" sin inflar el tiempo del juez.
def uniforme(caracter, n):
    return caracter * n


def alternante(n):
    return (ALFABETO * (n // 2 + 1))[:n]


def aleatoria(rand, n):
    return "".join(rand.choice(ALFABETO) for _ in range(n))


def con_palindromo(rand, n, largo):
    """Cadena de largo `n` con un palíndromo de largo `largo` plantado adentro.

    Los casos aleatorios tienen respuestas chicas; para que un lote "largo" no
    sea puro relleno, algunos casos llevan un palíndromo largo escondido en una
    posición aleatoria.  El palíndromo puede quedar extendido por sus vecinos, así
    que la respuesta verdadera puede ser mayor que `largo`: eso no importa, el
    `.out` lo produce la solución modelo.
    """
    assert 1 <= largo <= n
    base = [rand.choice(ALFABETO) for _ in range(n)]
    inicio = rand.randrange(0, n - largo + 1)
    mitad = [rand.choice(ALFABETO) for _ in range((largo + 1) // 2)]
    # mitad + reverso(mitad[:largo // 2]) tiene largo exactamente `largo` y es
    # palíndromo tanto para largo par como impar.
    cuerpo = mitad + mitad[: largo // 2][::-1]
    base[inicio : inicio + largo] = cuerpo
    return "".join(base)


# ── Ejemplos visibles en el enunciado ─────────────────────────────────
# Se generan primero a propósito: quedan como cases/0.in, cases/1.in, ... y son
# los que conviene copiar al enunciado (media/statement.md).  Como son cortos,
# caen en todas las subtareas (ver la nota sobre acumulación, más abajo).
def gen_ejemplos(cases):
    cases.append(TestCase("ababa"))  # "ababa" ya es palíndromo: respuesta 5
    cases.append(TestCase("aabb"))   # "aa" o "bb": respuesta 2 (longitud par)


# ── Subtarea 1: ~N <= 50~ ─────────────────────────────────────────────
def gen_st1(cases, rand):
    cases.append(TestCase("a"))                 # mínimo: n = 1
    cases.append(TestCase("ab"))                # n = 2 sin palíndromo de largo 2
    cases.append(TestCase("aa"))                # palíndromo de largo par
    cases.append(TestCase(uniforme("a", LIM_ST1)))   # respuesta n: peor caso
    cases.append(TestCase(alternante(LIM_ST1)))      # "abab...": respuesta 49
    for _ in range(3):
        cases.append(TestCase(aleatoria(rand, rand.randint(1, LIM_ST1))))


# ── Subtarea 2: ~N <= 1000~ ───────────────────────────────────────────
def gen_st2(cases, rand):
    # El caso que separa a la cúbica de la cuadrática: con una cadena uniforme,
    # *todos* los substrings son palíndromos y la fuerza bruta recorrió su peor
    # caso.  Es intencional (ver la cabecera del archivo).
    cases.append(TestCase(uniforme("a", LIM_ST2)))
    cases.append(TestCase(alternante(LIM_ST2)))
    cases.append(TestCase(con_palindromo(rand, LIM_ST2, LIM_ST2 // 2)))
    cases.append(TestCase(aleatoria(rand, LIM_ST2)))
    # Casos justo por encima del límite de ST1: un problema mal leído que sólo
    # funciona hasta 50 tiene que fallar acá y no en el caso enorme de ST4.
    cases.append(TestCase(uniforme("b", LIM_ST1 + 1)))
    cases.append(TestCase(aleatoria(rand, LIM_ST1 + 1)))


# ── Subtarea 3: ~N <= 5000~ ───────────────────────────────────────────
def gen_st3(cases, rand):
    # 5000 caracteres uniformes son ~1.25*10^7 comparaciones en la expansión
    # alrededor de cada centro.  Tanto en C como en C++ eso son milisegundos --
    # medido en el contenedor del juez, la cuadrática pasa esta subtarea con
    # holgura -- así que el caso NO separa complejidades acá (en la plantilla
    # `batched`, en Python, sí).  Está igual porque la escalera es la misma que
    # la de `batched`, que es lo que hace comparables a las dos plantillas, y
    # porque una solución deliberadamente peor que la cuadrática sí se cae.  El
    # corte real de la cuadrática es ST4 (10^5 caracteres), en los dos lenguajes.
    cases.append(TestCase(uniforme("a", LIM_ST3)))
    cases.append(TestCase(alternante(LIM_ST3)))
    cases.append(TestCase(con_palindromo(rand, LIM_ST3, 4000)))
    cases.append(TestCase(aleatoria(rand, LIM_ST3)))
    cases.append(TestCase(uniforme("b", LIM_ST2 + 1)))
    cases.append(TestCase(aleatoria(rand, LIM_ST2 + 1)))


# ── Subtarea 4: ~N <= 10^5~, sin restricciones adicionales ────────────
def gen_st4(cases, rand):
    # Los casos límite del problema completo.  El uniforme de 10^5 es el que
    # ningún algoritmo peor que O(N) atraviesa en tiempo.
    cases.append(TestCase(uniforme("a", LIM_ST4)))
    cases.append(TestCase(alternante(LIM_ST4)))
    cases.append(TestCase(con_palindromo(rand, LIM_ST4, 90_000)))
    cases.append(TestCase(aleatoria(rand, LIM_ST4)))
    cases.append(TestCase(uniforme("b", LIM_ST3 + 1)))
    cases.append(TestCase(aleatoria(rand, LIM_ST3 + 1)))


# ── Clasificación por subtarea ────────────────────────────────────────
# ¡Atención! Estas funciones determinan a qué subtarea pertenece cada caso: al
# escribir init.yml, `problemsetting cases` incluye el caso en cada subtarea
# cuyo check devuelva True.  Por eso el check de la última subtarea es el que
# acepta todo -- así los casos se acumulan hacia arriba, que es la convención de
# este toolkit: un caso de ST1 también está en ST2, ST3 y ST4, de modo que una
# solución que sólo cubre los casos chicos no puede "zafar" de los grandes.
#
# Editar una condición acá cambia la composición de los lotes (y con ello el
# puntaje de cada submission) sin tocar los casos en sí.
def check_st1(case):
    """ST1: la cadena tiene a lo sumo 50 caracteres."""
    return len(case.s) <= LIM_ST1


def check_st2(case):
    """ST2: la cadena tiene a lo sumo 1000 caracteres."""
    return len(case.s) <= LIM_ST2


def check_st3(case):
    """ST3: la cadena tiene a lo sumo 5000 caracteres."""
    return len(case.s) <= LIM_ST3


def check_st4(case):
    """ST4: sin restricciones adicionales -- todo caso califica."""
    return True


class Generator:
    """Punto de entrada del generador.  El toolkit instancia esta clase.

    Protocolo:

    * ``get_cases()``    -- la lista *ordenada* de casos.  El índice en la lista
                            es el número de archivo: el caso ``i`` se escribe en
                            ``cases/{i}.in`` y su respuesta esperada en
                            ``cases/{i}.out``.  Reordenar cambia los nombres de
                            archivo, no la composición de los lotes.
    * ``get_subtasks()`` -- una lista de ``(puntos, check_fn)``.  El segundo
                            elemento clasifica casos; el tercero es opcional y
                            son las *dependencias*, explicadas en
                            :meth:`get_subtasks`.
    * ``gen_small(rand)``-- casos diminutos para `problemsetting stress`, que
                            compara la solución modelo contra una fuerza bruta
                            sobre muchos casos al azar.

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
        gen_st3(cases, self.random)
        gen_st4(cases, self.random)
        return cases

    def get_subtasks(self):
        # (puntos, check) o (puntos, check, dependencias).  El caso entra en la
        # subtarea si check(case) es True.
        #
        # Las dependencias son la lista de números de lote (1-based) que tienen
        # que haberse pasado *completos* para que este lote se evalúe.  Lo aplica
        # el juez, no el toolkit (dmoj/judge.py: `dependencies = batch_dependencies[...]`
        # y, si el lote previo no está en `passed_batches`, todos los casos del
        # lote quedan marcados `SC` sin ejecutarse).  Efecto visible: una
        # solución que falla ST2 no "pierde" ST3 por poco, lo pierde entero y sin
        # correr -- y el reporte lo muestra como SC, que es distinto de WA.
        #
        # ST3 depende de [2] porque sus casos son los mismos de ST2 más los
        # grandes: si los medianos no pasan, tampoco van a pasar los de 5000, y
        # correrlos sólo gasta tiempo del juez.  La última subtarea NO lleva
        # dependencia a propósito: es la que acepta todo y la que tiene que
        # informar el estado real de la solución sobre los casos del problema
        # completo.
        #
        # En este problema la dependencia no llega a activarse con ninguno de los
        # envíos declarados -- la cuadrática de submissions/ pasa ST2 entera, que
        # es la diferencia con la plantilla `batched` (donde el mismo envío en
        # Python se cae en ST2 y ST3 queda en SC).  La declaración queda igual
        # porque es parte de la escalera compartida, y porque sigue en vigor para
        # cualquier envío que sí falle el lote 2.
        return [
            (20, check_st1),
            (25, check_st2),
            (25, check_st3, [2]),
            (30, check_st4),
        ]

    def gen_small(self, rand):
        # Casos diminutos para el stress test: donde una fuerza bruta tonta
        # (incluso cúbica) sirve de referencia honesta por lo barata.  Devuelve
        # una lista porque en un problema real cada llamada genera un caso
        # distinto; acá se varía la forma para que el stress no vea siempre
        # cadenas uniformes.
        forma = rand.randrange(3)
        largo = rand.randint(1, 14)
        if forma == 0:
            return [TestCase(uniforme(rand.choice(ALFABETO), largo))]
        if forma == 1:
            return [TestCase(alternante(largo))]
        return [TestCase(aleatoria(rand, largo))]
