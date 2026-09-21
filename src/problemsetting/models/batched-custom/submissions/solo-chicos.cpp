// Envío declarado: correcto y **subóptimo**, pero sólo en las rondas chicas.
//
// Es el archivo que hace visible la interacción entre las dos piezas del modelo,
// porque su resultado depende del tamaño de la ronda a propósito:
//
//   * con `n <= 50` (la Subtarea 1) construye una cobertura **válida** que usa un
//     faro de más -- exactamente `optimo(n) + 1`, o sea la banda
//     `PUNTAJE_PARCIAL` del checker -- así que cada caso de esa subtarea
//     acredita `0.7 * 10 = 7` puntos;
//
//   * con `n > 50` la construcción no ilumina la ronda, así que el checker la
//     rechaza con `CheckerResult(False, 0)` y el lote no acredita fracción
//     alguna.  El formato sigue siendo válido (una cantidad, esa cantidad de
//     posiciones, todas distintas y dentro de 1..n); lo que falla es el objeto.
//
// El corte en 50 no es arbitrario: es el límite de la Subtarea 1, y con
// `n = 51` el patrón de un faro de más deja de cerrar.  Por eso este envío
// acredita **sólo** la Subtarea 1 y nada más: en cuanto el lote 2 corre su
// primer caso se topa con una ronda que no puede iluminar, el juez corta el
// lote, y los casos que quedan no llegan a aportar su fracción.
//
// Ese es el punto entero del modelo: el puntaje de este envío no es «0.7 del
// problema» ni «0.7 de cada lote», es `0.7 * (puntos de los lotes cuyos casos
// alcanzó a correr)`.  Con los lotes de `get_subtasks` -- 10, 20, 30, 40 -- el
// resultado es 7 sobre 100, y no se puede deducir sin correrlo: depende del
// orden de los casos y del corte del lote.  El número exacto lo fija una corrida
// real de `problemsetting verify`; ver el comentario del envío en
// submissions.yml.
//
// Compárese con `hasta-2000.cpp`, que falla en las rondas grandes igual que
// éste pero sí construye bien las medianas: puntúan 7 y 21 respectivamente
// (medido), porque lo que decide el puntaje de un lote fraccionario es **qué
// casos llegaron a correr**, no cuántos fallaron.
//
// El costo es O(n).

#include <iostream>

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    long long n;
    if (!(std::cin >> n)) {
        return 1;
    }

    if (n > 50) {
        // Un faro suelto: formato correcto, objeto inválido.  El checker lo
        // rechaza y el lote paga 0.  Ver el comentario del encabezado.
        std::cout << "1\n1\n";
        return 0;
    }

    // ceil(n / 5), la cantidad óptima.
    long long optimo = (n + 4) / 5;

    // Cobertura válida con un faro de más: el patrón óptimo (3, 8, 13, ...) más
    // la menor posición que ese patrón no usa.  `optimo + 1` nunca supera el
    // doble de `optimo` para `optimo >= 1`, así que la banda es siempre la
    // parcial y nunca la pobre.
    bool usada[64] = {false};
    long long posiciones[64];
    long long k = optimo;
    for (long long j = 0; j < optimo; ++j) {
        long long posicion = (2 + 5 * j) % n + 1;
        posiciones[j] = posicion;
        usada[posicion] = true;
    }
    for (long long p = 1; p <= n; ++p) {
        if (!usada[p]) {
            posiciones[k++] = p;
            break;
        }
    }

    std::cout << k << '\n';
    for (long long j = 0; j < k; ++j) {
        std::cout << (j ? " " : "") << posiciones[j];
    }
    std::cout << '\n';
    return 0;
}
