// Solución modelo del problema «Ronda» (plantilla del modelo `batched-custom`).
//
// Este archivo es el que `problemsetting outputs` compila y corre sobre cada
// `cases/{i}.in` para producir `cases/{i}.out`.  Debe leer exactamente el mismo
// formato que escribe `generator.py` (`TestCase.write_file`): un entero `n` en
// una línea.
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
//   * **La construcción alcanza esa cota.**  Los faros van en `3, 8, 13, ...`,
//     o sea `5` posiciones de distancia.  El faro de la posición `p` ilumina
//     `[p-2, p+2]`, así que dos faros consecutivos dejan entre sus coberturas
//     una posición de solapamiento y ninguna sin cubrir: el primero cubre hasta
//     `p+2` y el siguiente arranca en `p+3`.  Recorriendo la ronda hacia
//     adelante, cada faro agrega 5 posiciones nuevas hasta el final, donde el
//     índice circular hace que el último se solape con el primero.  Eso deja
//     exactamente las últimas posiciones cubiertas por el primero, y el total
//     alcanza justo: `ceil(n/5)` faros cubren las `n` posiciones.
//
// El caso chico importa: con `n` entre 1 y 5 el único faro necesario es el que
// pone el índice 0 del bucle -- `k = 1` -- y el ciclo no se repite.  Con `n`
// chico el índice circular también hace que un faro "se salga" y dé la vuelta
// sobre posiciones ya cubiertas, y el `% n` de abajo lo maneja sin un caso
// especial.  Por eso el archivo es correcto para todo `n >= 1` y no sólo para
// los tamaños que el problema usa.
//
// El costo es O(n): se emiten `ceil(n/5)` posiciones y se calcula cada una en
// tiempo constante.

#include <iostream>

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    long long n;
    if (!(std::cin >> n)) {
        return 1;  // input ausente o mal formado: mejor fallar ruidosamente
    }

    // Número de faros por aritmética entera: ceil(n / 5) == (n + 4) / 5.
    long long k = (n + 4) / 5;

    std::cout << k << '\n';
    for (long long j = 0; j < k; ++j) {
        // `2 + 5j` es 2, 7, 12, ...; el `% n` lo trae al rango de la ronda y el
        // `+ 1` lo pasa a la numeración 1..n del enunciado (la posición 3 es la
        // primera con el faro).
        long long posicion = (2 + 5 * j) % n + 1;
        std::cout << (j ? " " : "") << posicion;
    }
    std::cout << '\n';
    return 0;
}
