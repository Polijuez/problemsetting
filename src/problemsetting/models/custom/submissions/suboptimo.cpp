// Envío subóptimo a propósito: un faro en cada posición par.
//
// Es una construcción **válida** y lo bastante buena para caer siempre en la
// banda de puntaje parcial, que es lo que `submissions.yml` declara:
//
//   * válida: los faros en 2, 4, 6, ... cubren todas las posiciones, porque cada
//     faro cubre también su impar anterior y ningún par queda sin cubrir (el
//     vecino de un par es impar y viceversa);
//   * subóptima: usa n/2 faros donde el óptimo es n/3, o sea 1.5x.  Y n/2 <=
//     2·(n/3) para todo n, así que nunca cae por debajo del umbral «pobre» del
//     checker: siempre vale exactamente `0.7 * point_value`.
//
// Ese «siempre» es la razón de que exista este archivo, y es más frágil de lo
// que parece: con n = 3 la construcción par también da 1 faro, o sea es óptima,
// y el puntaje declarado sería 1.0 en vez de 0.7.  Por eso `generator.py` genera
// los tamaños del problema como múltiplos de 3 y no menores que 6: es la
// restricción que hace que la expectativa declarada sea una propiedad del
// problema y no una coincidencia de esta corrida.
//
// Si tocás TAMANOS en el generador, este envío puede pasar a sacar puntaje
// completo y `verify` va a fallar contra su `score:` declarado.  Es
// intencional: la falla dice que la premisa cambió, no que el checker está mal.
//
// El costo es O(n), trivial para los límites del problema.

#include <iostream>

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    long long n;
    if (!(std::cin >> n)) {
        return 1;
    }

    long long faros = n / 2;
    std::cout << faros << '\n';
    for (long long i = 0; i < faros; ++i) {
        std::cout << (i ? " " : "") << 2 * (i + 1);
    }
    std::cout << '\n';
    return 0;
}
