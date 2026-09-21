// Envío que VIOLA el contrato del header -- el que demuestra que el problema
// rechaza una interfaz que no coincide.
//
// El error es deliberado y es el más común de los que se cometen en un problema de
// firma: la función se llama igual y calcula lo correcto, pero su firma no es la
// declarada.  Acá el arreglo entra como `const int *` donde el header declara
// `int *`.  En C++ son dos parámetros de tipos distintos, así que la definición no
// es la declaración -- son dos sobrecargas -- y la llamada de `evaluator.cpp` queda
// apuntando a la declarada, que nunca se define.  La composición falla al linkear.
//
// El juez compila los tres archivos (`<problema>_submission.cpp`,
// `signature.hpp`, `<problema>cpp.cpp`) en una sola invocación del compilador, así
// que esa falta de definición rompe la **compilación y el enlazado** -- DMOJ reporta
// ambas como error de compilación, así que el veredicto es **CE**, no WA.  Es el
// resultado que submissions.yml declara, y la comprobación que
// demuestra que el mecanismo de firma está en vigor: con un problema de E/S
// normal, este mismo archivo compilaría y daría AC.
//
// (Si en cambio definiera la firma exacta del header, el envío sería correcto y
// sacaría 100.  La diferencia entre los dos es exactamente lo que el header -- y
// sólo el header -- define.)
//
// El mismo error en C, con la firma cambiada de otra forma (el tipo de retorno),
// está en `firma-incorrecta.c`: los dos dan CE, y por eso los dos están
// declarados.

#include "signature.hpp"

int iluminar(int n, const int *faros) {
    // Cuerpo irrelevante: el archivo no llega a compilar.  Se deja la
    // construcción correcta igual, para que el error sea *sólo* de firma y la
    // comprobación no esté midiendo dos cosas a la vez.
    const int k = (n + 4) / 5;
    int *destino = const_cast<int *>(faros);
    for (int j = 0; j < k; ++j) {
        destino[j] = (2 + 5 * j) % n + 1;
    }
    return k;
}
