// Solución modelo del problema «subpalíndromo más largo» (plantilla del modelo
// `signature-batched`).
//
// Este archivo es el que `problemsetting outputs` compone y corre sobre cada
// `cases/{i}.in` para producir `cases/{i}.out`.  A diferencia de la plantilla
// `batched`, acá no hay `main`: el concursante implementa **la función** que
// declara `signature.hpp`, y el `main` lo aporta `evaluator.cpp`.  Es el mismo
// contrato que ve un concursante, ejercitado por la solución del propio autor --
// si la solución modelo no compila contra el header, el problema no compila.
//
// `problemsetting outputs` reproduce la composición del juez, no una parecida:
// escribe el envío como `<problema>_submission.cpp` precedido de
// `#include "signature.hpp"` y `#define main main_<uuid>`, copia el header sin
// tocarlo y renombra el evaluador a `<problema>cpp.cpp` (la extensión *sin
// punto* que le agrega `CLikeExecutor`), y compila los tres juntos.  Por eso este
// archivo no necesita `#include` propio... salvo que se compile solo, así que lo
// lleva igual: el header tiene guarda y una segunda inclusión no hace nada.
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

#include "signature.hpp"

#include <algorithm>
#include <string>
#include <vector>

int subpalindromo(const std::string& s) {
    // Cadena transformada: #a#b#a# ...
    std::string t;
    t.reserve(2 * s.size() + 1);
    for (char c : s) {
        t.push_back('#');
        t.push_back(c);
    }
    t.push_back('#');

    const int n = static_cast<int>(t.size());
    std::vector<int> radio(n, 0);  // radio[i]: cuántos caracteres a cada lado
    int centro = 0, borde = 0;     // palíndromo más a la derecha ya conocido
    int mejor = 0;

    for (int i = 0; i < n; ++i) {
        int r = 0;
        if (i < borde) {
            // Dentro del palíndromo ya conocido se puede copiar el radio de la
            // posición espejo; lo que sobra se verifica carácter por carácter.
            r = std::min(radio[2 * centro - i], borde - i);
        }
        while (i - r - 1 >= 0 && i + r + 1 < n && t[i - r - 1] == t[i + r + 1]) {
            ++r;
        }
        radio[i] = r;
        if (i + r > borde) {
            centro = i;
            borde = i + r;
        }
        mejor = std::max(mejor, r);
    }

    // En la cadena transformada el radio es directamente el largo del
    // palíndromo en la cadena original (el separador aporta la mitad).
    return mejor;
}
