// Solución modelo del problema «subpalíndromo más largo» (plantilla del modelo
// `signature-batched`, variante **C**).
//
// Este archivo es el que `problemsetting outputs` compone y corre sobre cada
// `cases/{i}.in` para producir `cases/{i}.out` cuando `meta.yml` declara
// `solutionlang: .c`.  A diferencia de la plantilla `batched`, acá no hay
// `main`: el concursante implementa **la función** que declara `signature.hpp`,
// y el `main` lo aporta `evaluator.cpp`.  Es el mismo contrato que ve un
// concursante, ejercitado por la solución del propio autor -- si la solución
// modelo no compila contra el header, el problema no compila.
//
// `problemsetting outputs` reproduce la composición del juez, no una parecida:
// escribe el envío como `<problema>_submission.c` precedido de
// `#include "signature.hpp"` y `#define main main_<uuid>`, copia el header sin
// tocarlo y renombra el evaluador a `<problema>c.c` (la extensión *sin punto*
// que le agrega `CLikeExecutor`, y que es la que hace que `gcc` compile el
// evaluador como C), y compila los tres juntos.  Por eso este archivo no
// necesita `#include` propio... salvo que se compile solo, así que lo lleva
// igual: el header tiene guarda y una segunda inclusión no hace nada.
//
// Que este archivo esté en C y `solution.cpp` en C++ **no son dos problemas**:
// es el mismo problema, el mismo header y la misma escalera, con el lenguaje de
// la solución modelo elegido por `solutionlang`.  DMOJ le pone
// `is_signature_gradable` al ejecutor `C11` igual que a `CPP17`
// (`dmoj/executors/c_like_executor.py:165-172`), así que el mecanismo no
// distingue.  Eso sí: la interfaz del header está escrita en el subconjunto
// común de los dos lenguajes -- `const char *` y `int`, con guardas de
// `extern "C"` -- porque los dos envíos tienen que linkear contra el **mismo**
// evaluador, y el evaluador se compila como C o como C++ según el ejecutor.  El
// porqué completo está en la cabecera de `signature.hpp`.
//
// Algoritmo: **Manacher**, O(|s|).  Es lo que hace falta para ST4 (N <= 10^5):
// la expansión alrededor de cada centro es O(N^2), y sólo una solución lineal
// entra en el límite de 1 s.  La escalera de subtareas de `generator.py` existe
// para que esa separación sea observable en el puntaje.
//
// Manacher sobre la cadena transformada: se intercalan separadores ('#' entre
// cada par de caracteres) para tratar longitudes pares e impares con el mismo
// código.  En la cadena transformada, un palíndromo de radio k corresponde a un
// palíndromo real de largo k en la original.
//
// La diferencia con `solution.cpp` es sólo de lenguaje: `malloc`/`free` en vez
// de `std::vector`, `size_t` de `<string.h>` en vez de `std::string::size`.  Si
// el problema cambia de algoritmo, hay que cambiar los dos archivos: son la
// misma solución en dos lenguajes, y los `.out` tienen que salir iguales.

#include "signature.hpp"

#include <stdlib.h>
#include <string.h>

int subpalindromo(const char *s) {
    const int n_original = (int)strlen(s);

    // Cadena transformada: #a#b#a# ...
    const int n = 2 * n_original + 1;
    char *t = malloc((size_t)n + 1);
    int *radio = malloc(sizeof(int) * (size_t)n);
    if (t == NULL || radio == NULL) {
        // Sin memoria no hay respuesta correcta que dar.  Es un fallo del
        // ambiente, no del envío; devolver un valor sin sentido sería peor.
        free(t);
        free(radio);
        return 0;
    }

    for (int i = 0; i < n_original; ++i) {
        t[2 * i] = '#';
        t[2 * i + 1] = s[i];
    }
    t[n - 1] = '#';
    t[n] = '\0';

    int centro = 0, borde = 0;  // palíndromo más a la derecha ya conocido
    int mejor = 0;

    for (int i = 0; i < n; ++i) {
        int r = 0;
        if (i < borde) {
            // Dentro del palíndromo ya conocido se puede copiar el radio de la
            // posición espejo; lo que sobra se verifica carácter por carácter.
            const int espejo = radio[2 * centro - i];
            r = espejo < borde - i ? espejo : borde - i;
        }
        while (i - r - 1 >= 0 && i + r + 1 < n && t[i - r - 1] == t[i + r + 1]) {
            ++r;
        }
        radio[i] = r;
        if (i + r > borde) {
            centro = i;
            borde = i + r;
        }
        if (r > mejor) {
            mejor = r;
        }
    }

    free(t);
    free(radio);
    // En la cadena transformada el radio es directamente el largo del
    // palíndromo en la cadena original (el separador aporta la mitad).
    return mejor;
}
