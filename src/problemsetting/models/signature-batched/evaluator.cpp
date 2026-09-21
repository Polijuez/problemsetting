// evaluator.cpp -- el programa que el concursante NO escribe.
//
// Éste es el archivo que `init.yml` nombra como
// `signature_grader: {entry: evaluator.cpp}`.  El juez lo compila **junto con el
// envío del concursante** en la misma invocación del compilador, después de
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
//
// ── Por qué su contenido se queda en el subconjunto común de C y C++ ────────
//
// El nombre del archivo dice `.cpp`, pero eso no decide cómo se compila: el juez
// lo reescribe como `<problema><ext>.<ext>` -- `sigc.c` para el ejecutor `C11`,
// `sigcpp.cpp` para `CPP17` (`CLikeExecutor.create_files`, y el toolkit reproduce
// exactamente esos nombres en `outputs.signature_layout`) -- y **el compilador
// despacha por ese sufijo**.  O sea: con `solutionlang: .c` este archivo se
// compila como C, y con `.cpp` como C++.
//
// Por eso usa `scanf`/`printf` de `<stdio.h>` y un arreglo estático, y no
// `std::cin`/`std::string`: es el mismo código válido en los dos lenguajes, que es
// la condición para que la misma plantilla sirva a las dos variantes sin
// duplicar el evaluador.  (Ver el bloque "Por qué la interfaz está escrita en C"
// de `signature.hpp`.)

#include "signature.hpp"

#include <stdio.h>

// N_MAX del enunciado (10^5) más el terminador.  `%100000s` le dice a `scanf`
// que nunca escriba más de eso, así que el tamaño del arreglo y el ancho del
// formato tienen que moverse juntos si cambia el límite del problema.
static char cadena[100005];

int main(void) {
    // Igual que un programa de concurso normal: entrada por stdin, salida por
    // stdout, y nada más.  No hay `freopen`: el toolkit (`problemsetting
    // outputs`) y el juez le pasan la entrada por stdin, y agregar un
    // `freopen(argv[1], ...)` haría que la corrida local y la del juez leyeran
    // archivos distintos.
    if (scanf("%100000s", cadena) != 1) {
        return 1;  // input ausente o mal formado: mejor fallar ruidosamente
    }

    // Una llamada por caso.  El único resultado que el checker espera es esta
    // línea, así que no se imprime nada más.
    printf("%d\n", subpalindromo(cadena));
    return 0;
}
