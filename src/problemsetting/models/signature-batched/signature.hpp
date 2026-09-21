// signature.hpp -- la interfaz que implementa el concursante.
//
// En el modelo `signature-batched` el concursante NO escribe un programa: escribe
// **una función**.  El juez le entrega este header -- textualmente el archivo que
// está leyendo -- y compila su envío junto con `evaluator.cpp`, que es el
// programa de verdad.  El envío del concursante no necesita `#include` propio:
// el juez se lo prefija (ver abajo).
//
// ── Cómo lo compone el juez (lo que hay que saber para autorar) ─────────────
//
// `dmoj/graders/signature.py` arma el texto del envío así:
//
//     #include "signature.hpp"
//     #define main main_<uuid>
//     <envío del concursante, tal cual>
//
// y lo pasa como `aux_sources` al ejecutor del lenguaje, que además agrega el
// `evaluator.cpp` de `init.yml` (`signature_grader: {entry: evaluator.cpp, ...}`).
// Los tres archivos se le pasan a **una sola invocación** del compilador, que
// compila cada uno como su propia unidad de traducción y después los enlaza:
//
//     g++ -Wall <id>_submission.cpp signature.hpp <id>cpp.cpp -DONLINE_JUDGE ...
//     gcc -Wall <id>_submission.c   signature.hpp <id>c.c   -DONLINE_JUDGE ...
//
// Tres consecuencias que explican por qué este archivo tiene la forma que tiene:
//
//   1. El `#include` lo pone el juez, no el concursante.  El envío puede
//      incluirlo igual (es idempotente sólo si el header tiene guarda -- por eso
//      la de abajo), pero no hace falta.
//   2. `#define main main_<uuid>` renombra el `main` del envío para que no
//      colisione con el de `evaluator.cpp`.  Es lo que permite que un concursante
//      que además escribió un `main` (porque probó su función localmente) no
//      rompa la compilación.  Por eso **este** header no puede definir un `main`
//      propio: el juez renombra el del envío, no el de la interfaz, y el
//      `evaluator.cpp` ya aporta el único `main` que puede existir.
//   3. Como son unidades separadas, el envío y el evaluador se vinculan por el
//      **símbolo** de la función, no por texto: de ahí que la declaración tenga
//      que coincidir exactamente, y que `extern "C"` importe (ver abajo).  Aquí
//      sólo se **declara**; la definición vive en el envío.
//
// ── Por qué la interfaz está escrita en C y no en C++ ───────────────────────
//
// El mismo header sirve a un envío en **C** y a uno en **C++**: DMOJ le pone
// `is_signature_gradable` al ejecutor de C y al de C++ por igual
// (`dmoj/executors/c_like_executor.py:165-172`), así que el mecanismo es el mismo
// y lo único que elige el autor es el lenguaje de la solución modelo
// (`solutionlang`), no el modelo.  Hay una razón estructural y no estilística
// para el subconjunto común:
//
//   * los envios de los dos lenguajes tienen que linkear contra el **mismo**
//     evaluador, y el evaluador es un solo archivo (`evaluator.cpp` en
//     `init.yml`) que el juez renombra a `<id>c.c` o a `<id>cpp.cpp` según el
//     ejecutor -- o sea que **su contenido se compila como C cuando el modelo es
//     C, y como C++ cuando es C++**.  Un evaluador con `std::cin` directamente no
//     compilaría en la variante C;
//   * por lo mismo, la declaración tiene que ser válida en los dos lenguajes: un
//     `std::string` acá haría el modelo inutilizable desde C.
//
// De ahí las dos formas de este archivo: los tipos del subconjunto común
// (`const char *`, `int`) y las guardas de `extern "C"`, que le dicen al
// compilador de C++ que el símbolo es el de C -- sin *name mangling* -- para que
// el `int subpalindromo(const char *)` que define una solución en C sea
// exactamente el que llama el evaluador.  Sin ellas, las dos variantes no
// linkearían entre sí.
//
// El nombre de la función lo elige el autor del problema, pero **una vez
// publicado es la interfaz**: cambiarlo invalida todos los envíos de los
// concursantes (y los de submissions.yml).  `evaluator.cpp`, `solution.c` y
// `solution.cpp` lo usan; los tres tienen que estar de acuerdo.

#ifndef SIGNATURE_BATCHED_HPP_INCLUDED
#define SIGNATURE_BATCHED_HPP_INCLUDED

#ifdef __cplusplus
extern "C" {
#endif

// Devuelve la longitud del substring **contiguo** más largo de `s` que sea un
// palíndromo.  `s` no está vacía: 1 <= strlen(s) <= 100000.
//
// El evaluador lee `s` de la entrada estándar y llama a esta función una vez por
// caso; no hay estado compartido entre casos (cada corrida es un proceso nuevo).
int subpalindromo(const char *s);

#ifdef __cplusplus
}
#endif

#endif  // SIGNATURE_BATCHED_HPP_INCLUDED
