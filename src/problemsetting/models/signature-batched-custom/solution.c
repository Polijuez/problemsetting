// Solución modelo del problema «Ronda» (plantilla del modelo
// `signature-batched-custom`, variante **C**).
//
// Este archivo es el que `problemsetting outputs` compone y corre sobre cada
// `cases/{i}.in` para producir `cases/{i}.out` cuando `meta.yml` declara
// `solutionlang: .c`.  No hay `main`: el concursante implementa **la función**
// que declara `signature.hpp`, y el `main`, la entrada y la salida los aporta
// `evaluator.cpp`.
//
// Es la misma solución que `solution.cpp`, en C: `ceil(n/5)` faros en las
// posiciones 3, 8, 13, ...  El argumento de optimalidad -- cota inferior por
// cobertura y construcción que la alcanza -- está en el comentario de
// `solution.cpp`, que es donde vive completo; acá se repite el resultado y no la
// demostración.
//
// Que este archivo exista no es una redundancia: DMOJ le pone
// `is_signature_gradable` al ejecutor `C11` igual que a `CPP17`, así que el
// mecanismo de firma no distingue entre los dos lenguajes y lo único que el autor
// elige es `solutionlang`.  La evidencia de que la composición funciona en C es
// esta solución corriendo con el ejecutor `C11` -- donde el evaluador se compila
// **como C** -- y su salida tiene que coincidir con la de la variante C++.  Las
// dos están declaradas en `submissions.yml`, con `verdict: AC` y `score: 100`.
//
// El costo es O(n), y se escribe a lo sumo `n` posiciones en `faros`.

#include "signature.hpp"

int iluminar(int n, int *faros) {
    // Número de faros por aritmética entera: ceil(n / 5) == (n + 4) / 5.
    const int k = (n + 4) / 5;

    for (int j = 0; j < k; ++j) {
        // `2 + 5j` es 2, 7, 12, ...; el `% n` lo trae al rango de la ronda y el
        // `+ 1` lo pasa a la numeración 1..n del enunciado.
        faros[j] = (2 + 5 * j) % n + 1;
    }

    // La cantidad que se escribió: el evaluador la imprime primero, y después las
    // `k` posiciones.  Ése es el formato que lee el checker.
    return k;
}
