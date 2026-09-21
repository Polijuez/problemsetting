// signature.hpp -- la interfaz que implementa el concursante.
//
// En el modelo `signature-batched-custom` el concursante NO escribe un programa:
// escribe **una función**.  El juez le entrega este header -- textualmente el
// archivo que está leyendo -- y compila su envío junto con `evaluator.cpp`, que
// es el programa de verdad.  El envío no necesita `#include` propio: el juez se
// lo prefija (ver abajo).
//
// ── Cómo lo compone el juez ─────────────────────────────────────────────────
//
// `dmoj/graders/signature.py` arma el texto del envío así:
//
//     #include "signature.hpp"
//     #define main main_<uuid>
//     <envío del concursante, tal cual>
//
// y lo pasa como `aux_sources` al ejecutor del lenguaje, que además agrega el
// `evaluator.cpp` de `init.yml` (`signature_grader: {entry: evaluator.cpp, ...}`).
// Los tres archivos se compilan **juntos, como una sola unidad de traducción**.
// Tres consecuencias:
//
//   1. El `#include` lo pone el juez.  El envío puede incluirlo igual -- por eso
//      la guarda de abajo -- pero no hace falta.
//   2. `#define main main_<uuid>` renombra el `main` del envío para que no
//      colisione con el de `evaluator.cpp`.  Por eso **este** header no puede
//      definir un `main`: el juez renombra el del envío, no el de la interfaz.
//   3. Todo se compila en una sola unidad, así que aquí sólo se **declara**.
//
// ── Por qué la interfaz está escrita en C y no en C++ ───────────────────────
//
// El mismo header sirve a un envío en **C** y a uno en **C++**: DMOJ le pone
// `is_signature_gradable` al ejecutor de C y al de C++ por igual
// (`dmoj/executors/c_like_executor.py:165-172`), y lo único que elige el autor es
// el lenguaje de la solución modelo (`solutionlang`), no el modelo.  La razón
// estructural es la misma que la de `models/signature-batched/signature.hpp`: el
// evaluador se compila como C o como C++ según el ejecutor, así que su contenido
// -- y esta declaración -- tienen que valer en los dos lenguajes.  De ahí los
// tipos del subconjunto común (`int`, `int *`) y las guardas de `extern "C"`, que
// le dicen al compilador de C++ que el símbolo es el de C -- sin *name mangling*
// -- para que la definición de una solución en C sea exactamente la que llama el
// evaluador.
//
// ── La obligación de memoria, que no se ve en la firma ──────────────────────
//
// El evaluador reserva un arreglo de **capacidad `n`** y se lo pasa a la función:
// la función escribe ahí las posiciones de los faros y **devuelve cuántas
// escribió**.  Escribir más de `n` posiciones no produce una salida inválida:
// corrompe memoria, que es un fallo del proceso y no un WA.  Por eso el límite
// está dicho acá y en el enunciado, y no sólo implícito en el tipo del parámetro.
//
// El nombre de la función lo elige el autor del problema, pero **una vez
// publicado es la interfaz**: cambiarlo invalida todos los envíos de los
// concursantes (y los de submissions.yml).  `evaluator.cpp`, `solution.c` y
// `solution.cpp` lo usan; los cuatro tienen que estar de acuerdo.

#ifndef SIGNATURE_BATCHED_CUSTOM_HPP_INCLUDED
#define SIGNATURE_BATCHED_CUSTOM_HPP_INCLUDED

#ifdef __cplusplus
extern "C" {
#endif

// Ilumina una ronda de `n` posiciones (numeradas 1..n, en círculo) colocando
// faros, y devuelve la **cantidad** de faros colocados.
//
// Un faro en la posición `i` ilumina `i-2`, `i-1`, `i`, `i+1` e `i+2` (en
// círculo).  Hay que iluminar todas las posiciones.
//
// La función escribe las posiciones elegidas en `faros` -- que el evaluador
// reserva con capacidad `n` -- y **no** las imprime: de la salida se encarga el
// evaluador.  La cantidad que devuelve tiene que coincidir con la cantidad de
// posiciones que escribió, y cada posición tiene que ser distinta y estar entre 1
// y `n`.  Escribir más de `n` posiciones corrompe el arreglo: no lo hagas.
int iluminar(int n, int *faros);

#ifdef __cplusplus
}
#endif

#endif  // SIGNATURE_BATCHED_CUSTOM_HPP_INCLUDED
