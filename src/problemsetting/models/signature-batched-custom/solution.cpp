// Solución modelo del problema «Ronda» (plantilla del modelo
// `signature-batched-custom`, variante **C++**).
//
// Este archivo es el que `problemsetting outputs` compone y corre sobre cada
// `cases/{i}.in` para producir `cases/{i}.out` cuando `meta.yml` declara
// `solutionlang: .cpp`.  No hay `main`: el concursante implementa **la función**
// que declara `signature.hpp`, y el `main`, la entrada y la salida los aporta
// `evaluator.cpp`.
//
// Devuelve la construcción **óptima**: `ceil(n / 5)` faros.  No es un detalle.
// El checker recalcula `óptimo(n)` y falla ruidosamente si este archivo no lo
// alcanza, porque entonces los `.out` estarían mal y ninguna submission podría
// sacar puntaje completo.  Es la asimetría que documenta `checker.py`: la
// submission es hostil y se aguanta; el artefacto del problema es nuestro y se
// exige.
//
// Por qué `ceil(n/5)` es el óptimo, y por qué esta construcción lo alcanza:
//
//   * **Cota inferior.**  Cada faro ilumina 5 posiciones (las dos a cada lado,
//     más la propia), así que ningún conjunto de `k` faros cubre más de `5k`
//     posiciones.  Para cubrir `n` hace falta `k >= ceil(n/5)`.
//
//   * **La construcción alcanza esa cota.**  Los faros van en `3, 8, 13, ...`, o
//     sea `5` posiciones de distancia.  El faro de la posición `p` ilumina
//     `[p-2, p+2]`, así que dos faros consecutivos dejan entre sus coberturas una
//     posición de solapamiento y ninguna sin cubrir.  Recorriendo la ronda hacia
//     adelante, cada faro agrega 5 posiciones nuevas hasta el final, donde el
//     índice circular hace que el último se solape con el primero.
//
// El caso chico importa: con `n` entre 1 y 5 el único faro necesario es el que
// pone la iteración 0 -- `k = 1` -- y el ciclo no se repite.  Con `n` chico el
// índice circular también hace que un faro "se salga" y dé la vuelta sobre
// posiciones ya cubiertas, y el `% n` de abajo lo maneja sin un caso especial.
// Por eso el archivo es correcto para todo `n >= 1` y no sólo para los tamaños
// que el problema usa.
//
// La obligación de memoria es del header: se escribe a lo sumo `n` posiciones en
// `faros`, y acá se escriben exactamente `ceil(n/5) <= n`.  La variante en C de
// esta misma solución está en `solution.c`, con el mismo algoritmo.
//
// El costo es O(n): se emiten `ceil(n/5)` posiciones y se calcula cada una en
// tiempo constante.

#include "signature.hpp"

int iluminar(int n, int *faros) {
    // Número de faros por aritmética entera: ceil(n / 5) == (n + 4) / 5.
    const int k = (n + 4) / 5;

    for (int j = 0; j < k; ++j) {
        // `2 + 5j` es 2, 7, 12, ...; el `% n` lo trae al rango de la ronda y el
        // `+ 1` lo pasa a la numeración 1..n del enunciado (la posición 3 es la
        // primera con el faro).
        faros[j] = (2 + 5 * j) % n + 1;
    }

    // La cantidad que se escribió.  El evaluador imprime este valor en la primera
    // línea y después las `k` posiciones, que es el formato que lee el checker.
    return k;
}
