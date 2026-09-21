// Envío que VIOLA el contrato del header -- el que demuestra que el problema
// rechaza una interfaz que no coincide.  Variante en **C++**.
//
// El error es deliberado y es el más común de los que se cometen en un problema
// de firma: la función se llama igual y calcula lo correcto, pero su firma no es
// la declarada.  Acá toma `std::string` **por valor** donde `signature.hpp`
// declara `const char *`.
//
// Para C++ son dos funciones distintas: la definición no es la declaración, así
// que la llamada de `evaluator.cpp` queda apuntando a la declarada -- que nunca
// se define -- y la composición falla al linkear.
//
// El juez compila los tres archivos (`<problema>_submission.cpp`,
// `signature.hpp`, `<problema>cpp.cpp`) como una sola unidad de traducción, así
// que esa falta de definición es un error de compilación: el veredicto es **CE**,
// no WA.  Es el resultado que submissions.yml declara, y la comprobación que
// demuestra que el mecanismo de firma está en vigor: con un problema de E/S
// normal, este mismo archivo compilaría y daría AC.
//
// (Si en cambio definiera `int subpalindromo(const char *)`, el envío sería
// correcto y sacaría 100.  La diferencia entre los dos es exactamente lo que el
// header -- y sólo el header -- define.)
//
// El mismo error en C, con la firma cambiada de otra forma (el tipo de retorno),
// está en `firma-incorrecta.c`: los dos dan CE, y por eso los dos están
// declarados.

#include "signature.hpp"

#include <algorithm>
#include <string>

int subpalindromo(std::string s) {
    const int n = static_cast<int>(s.size());
    int mejor = 0;
    for (int centro = 0; centro < n; ++centro) {
        int lo = centro, hi = centro;
        while (lo >= 0 && hi < n && s[lo] == s[hi]) {
            --lo;
            ++hi;
        }
        mejor = std::max(mejor, hi - lo - 1);
        lo = centro;
        hi = centro + 1;
        while (lo >= 0 && hi < n && s[lo] == s[hi]) {
            --lo;
            ++hi;
        }
        mejor = std::max(mejor, hi - lo - 1);
    }
    return mejor;
}
