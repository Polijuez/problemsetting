// Envío que VIOLA el contrato del header -- el que demuestra que el problema
// rechaza una interfaz que no coincide.  Variante en **C**.
//
// La misma idea que `firma-incorrecta.cpp`, con el error puesto en otra parte de
// la firma: acá el nombre y los parámetros son los correctos, pero el **tipo de
// retorno** es `long long` donde `signature.hpp` declara `int`.  Para C son dos
// funciones incompatibles, así que la definición entra en conflicto con la
// declaración del header y `gcc` se niega a compilar.
//
// El veredicto es **CE**: el juez no consigue compilar la composición
// (`<problema>_submission.c`, `signature.hpp`, `<problema>c.c`), así que el envío
// nunca llega a correr.  Es la comprobación de que el mecanismo de firma está en
// vigor también cuando el envío es C -- y de que la interfaz del header es la
// misma para los dos lenguajes: si el header estuviera escrito en C++ (con
// `std::string`), este archivo ni siquiera sería un envío válido del problema.
//
// Los dos envíos con firma equivocada están declarados en submissions.yml con
// `verdict: CE`, y ninguno declara `score:` -- un envío que el juez nunca corrió
// no tiene puntaje que comparar.
//
// (Si en cambio definiera `int subpalindromo(const char *s)`, el envío sería
// correcto y sacaría 100.)

#include "signature.hpp"

#include <string.h>

long long subpalindromo(const char *s) {
    const int n = (int)strlen(s);
    int mejor = 0;
    for (int centro = 0; centro < n; ++centro) {
        int lo = centro, hi = centro;
        while (lo >= 0 && hi < n && s[lo] == s[hi]) {
            --lo;
            ++hi;
        }
        if (hi - lo - 1 > mejor) {
            mejor = hi - lo - 1;
        }
        lo = centro;
        hi = centro + 1;
        while (lo >= 0 && hi < n && s[lo] == s[hi]) {
            --lo;
            ++hi;
        }
        if (hi - lo - 1 > mejor) {
            mejor = hi - lo - 1;
        }
    }
    return mejor;
}
