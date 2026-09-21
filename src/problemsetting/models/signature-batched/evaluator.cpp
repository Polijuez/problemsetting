// evaluator.cpp -- el programa que el concursante NO escribe.
//
// Éste es el archivo que `init.yml` nombra como
// `signature_grader: {entry: evaluator.cpp}`.  El juez lo compila **junto con el
// envío del concursante** como una sola unidad de traducción, después de
// prefijarle a ese envío un `#include "signature.hpp"` y un
// `#define main main_<uuid>` (los detalles del mecanismo están en la cabecera de
// `signature.hpp`, que es el archivo que el concursante sí ve).  Por eso:
//
//   * el `main` que vive acá es el **único** `main` efectivo del programa: el del
//     envío queda renombrado por el `#define`;
//   * el envío sólo tiene que *definir* la función declarada en `signature.hpp`,
//     sin leer ni imprimir nada;
//   * este archivo es el que lee la entrada y el que imprime la respuesta, así que
//     un cambio acá cambia el formato para todos los casos (y los `.out`).
//
// Escribirlo como un evaluador y no como una solución tiene una consecuencia
// práctica para el autor: **este archivo no puede depender de la solución**.  Si
// el evaluador imprimiera, por ejemplo, el resultado de un cálculo propio, el
// problema dejaría de evaluar lo que el enunciado pide.

#include "signature.hpp"

#include <iostream>
#include <string>

int main() {
    // Igual que un programa de concurso normal: entrada por stdin, salida por
    // stdout, y nada más.  No hay `freopen`: el toolkit (`problemsetting
    // outputs`) y el juez le pasan la entrada por stdin, y agregar un
    // `freopen(argv[1], ...)` haría que la corrida local y la del juez leyeran
    // archivos distintos.
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    std::string s;
    if (!(std::cin >> s)) {
        return 1;  // input ausente o mal formado: mejor fallar ruidosamente
    }

    // Una llamada por caso.  El único resultado que el checker espera es esta
    // línea, así que no se imprime nada más.
    std::cout << subpalindromo(s) << '\n';
    return 0;
}
