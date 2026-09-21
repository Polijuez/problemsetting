// evaluator.cpp -- el programa que el concursante NO escribe.
//
// Éste es el archivo que `init.yml` nombra como
// `signature_grader: {entry: evaluator.cpp}`.  El juez lo compila **junto con el
// envío del concursante** como una sola unidad de traducción, después de
// prefijarle a ese envío un `#include "signature.hpp"` y un
// `#define main main_<uuid>` (el mecanismo completo está en `signature.hpp`).  Por
// eso:
//
//   * el `main` que vive acá es el **único** `main` efectivo del programa;
//   * el envío sólo tiene que *definir* `iluminar`, sin leer ni imprimir nada;
//   * este archivo es el que lee la entrada, reserva el arreglo que la función
//     recibe y **convierte su resultado en el texto que el checker lee**, así que
//     un cambio acá cambia el formato para todos los casos (y los `.out`).
//
// Escribe el evaluador, no la solución: **este archivo no puede depender de la
// solución**.  Si imprimiera, por ejemplo, una construcción propia, el problema
// dejaría de evaluar lo que el enunciado pide.
//
// ── El formato de salida es de acá, no del concursante ──────────────────────
//
// Esa es la diferencia con la plantilla de E/S (`batched-custom`): allá la
// submission imprimía «K en la primera línea, K posiciones después».  Acá la
// función *devuelve* K y *escribe* las posiciones en el arreglo, y este archivo
// es el que produce esas dos líneas.  El checker no cambió -- sigue leyendo el
// mismo formato -- y ése es el punto: la interfaz de firma reemplaza *cómo el
// concursante entrega la respuesta*, no el formato del problema.
//
// ── Por qué su contenido se queda en el subconjunto común de C y C++ ────────
//
// El nombre dice `.cpp`, pero eso no decide cómo se compila: el juez lo reescribe
// como `<problema><ext>.<ext>` -- `sigc.c` para `C11`, `sigcpp.cpp` para `CPP17`
// (`CLikeExecutor.create_files`; `outputs.signature_layout` reproduce esos
// nombres) -- y el compilador despacha por ese sufijo.  Con `solutionlang: .c`
// este archivo se compila como C.  Por eso usa `scanf`/`printf`/`malloc` de
// `<stdio.h>` y `<stdlib.h>` y no `std::cin`: es el mismo código válido en los
// dos lenguajes.

#include "signature.hpp"

#include <stdio.h>
#include <stdlib.h>

int main(void) {
    // Igual que un programa de concurso normal: entrada por stdin, salida por
    // stdout, y nada más.  No hay `freopen`: el toolkit (`problemsetting
    // outputs`) y el juez le pasan la entrada por stdin, y agregar un
    // `freopen(argv[1], ...)` haría que la corrida local y la del juez leyeran
    // archivos distintos.
    int n;
    if (scanf("%d", &n) != 1 || n < 1) {
        return 1;  // input ausente o mal formado: mejor fallar ruidosamente
    }

    // Capacidad `n`: es la obligación que el header documenta.  `malloc` y no un
    // arreglo en el stack porque el caso más grande del problema tiene 200000
    // posiciones, y una función se reserva sin el `n` del caso.
    int *faros = (int *)malloc(sizeof(int) * (size_t)n);
    if (faros == NULL) {
        return 1;
    }

    const int colocados = iluminar(n, faros);

    // La cantidad que se imprime primero es la que devolvió la función, **sin
    // corregirla**: si miente, el checker tiene que ver la mentira para poder
    // rechazarla ("declara K faros pero manda M posiciones").
    printf("%d\n", colocados);

    // Pero las posiciones que se *leen* del arreglo van acotadas a su capacidad,
    // que es `n`: la función promete no escribir más de `n`, así que leer más allá
    // sería leer memoria ajena -- comportamiento indefinido, y un fallo del
    // proceso en vez del WA que corresponde.  Con `colocados > n` el lazo imprime
    // `n` posiciones y la primera línea queda mintiendo, que es exactamente lo que
    // el checker detecta.
    const int a_imprimir = colocados < n ? colocados : n;
    for (int i = 0; i < a_imprimir; ++i) {
        printf("%s%d", i ? " " : "", faros[i]);
    }
    printf("\n");

    free(faros);
    return 0;
}
