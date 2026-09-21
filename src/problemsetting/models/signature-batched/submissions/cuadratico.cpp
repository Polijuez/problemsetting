// O(N^2): expande alrededor de cada centro (el algoritmo "clásico" del problema).
//
// Es *correcta*, y por eso es el envío interesante de la escalera: pasa ST1, ST2
// y ST3, y se cae en ST4 con la cadena uniforme de 10^5 caracteres, donde el peor
// caso son ~5*10^9 comparaciones.  En C++ el caso de 5000 de ST3 tarda unos pocos
// milisegundos, o sea que ST3 lo pasa con muchísimo margen: la cuadrática no
// "casi no llega", llega.  El corte real es ST4 (N = 10^5), donde sólo entra una
// solución lineal (Manacher, como en solution.cpp).
//
// Este envío es el sujeto de la comprobación 3 de `verify` ("un envío correcto
// pero lento da TLE"): no falla por respuesta incorrecta -- sus casos chicos son
// AC -- sino por tiempo en el lote grande.  Por eso también es la evidencia de
// que el `tl` de 1 s de meta.yml separa de verdad a la cuadrática de la lineal.
//
// El puntaje esperado (70/100) sale de una corrida real de
// `problemsetting verify`, no de razonarlo: la composición del corte del lote,
// la omisión por dependencia y el tiempo agotado no se predicen a mano.

#include "signature.hpp"

#include <algorithm>
#include <string>

int subpalindromo(const std::string& s) {
    const int n = static_cast<int>(s.size());
    int mejor = 0;
    for (int centro = 0; centro < n; ++centro) {
        // Palíndromo impar con centro en `centro`.
        int lo = centro, hi = centro;
        while (lo >= 0 && hi < n && s[lo] == s[hi]) {
            --lo;
            ++hi;
        }
        mejor = std::max(mejor, hi - lo - 1);
        // Palíndromo par con centro entre `centro` y `centro + 1`.
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
