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
// y lo pasa como `aux_sources` al ejecutor de C++, que además agrega el
// `evaluator.cpp` de `init.yml` (`signature_grader: {entry: evaluator.cpp, ...}`).
// Los tres archivos se compilan **juntos, como una sola unidad de traducción**:
//
//     g++ -Wall <id>_submission.cpp signature.hpp <id>cpp.cpp -DONLINE_JUDGE ...
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
//   3. Todo se compila en una sola unidad, así que aquí sólo se **declara**.  Las
//      definiciones, si las hubiera, tendrían que ser `inline`; no las hay.
//
// El nombre de la función lo elige el autor del problema, pero **una vez
// publicado es la interfaz**: cambiarlo invalida todos los envíos de los
// concursantes (y los de submissions.yml).  `evaluator.cpp` y `solution.cpp` lo
// usan; los tres tienen que estar de acuerdo.

#ifndef SIGNATURE_BATCHED_HPP_INCLUDED
#define SIGNATURE_BATCHED_HPP_INCLUDED

#include <string>

// Devuelve la longitud del substring **contiguo** más largo de `s` que sea un
// palíndromo.  `s` no está vacía: 1 <= s.size() <= 100000.
//
// El evaluador lee `s` de la entrada estándar y llama a esta función una vez por
// caso; no hay estado compartido entre casos (cada corrida es un proceso nuevo).
int subpalindromo(const std::string& s);

#endif  // SIGNATURE_BATCHED_HPP_INCLUDED
