// Envío declarado: correcto y subóptimo en las rondas medianas, inválido en las
// grandes.  Es el envío que **falla una subtarea concreta**.
//
// Su resultado por subtarea, que es lo que el manifest declara:
//
//   * Subtarea 1 (n <= 50): válido y subóptimo -> `0.7 * 10 = 7`.
//   * Subtarea 2 (n <= 2000): válido y subóptimo -> `0.7 * 20 = 14`.
//   * Subtarea 3 (n <= 50000): el primer caso es una ronda que no puede iluminar,
//     así que el lote se corta -> `0`.
//   * Subtarea 4 (n <= 200000): igual -> `0`.
//
// Total 21 sobre 100.
//
// La parte que vale la pena mirar es la Subtarea 3, porque muestra un detalle del
// mecanismo de `dependencies` que no es obvio: **una subtarea que acredita puntaje
// parcial cuenta como aprobada.**  La dependencia de ST3 es `[2]`, y el juez la
// resuelve contra `passed_batches`, que se llena cuando el lote no entró en
// cortocircuito (`dmoj/judge.py:541-543`) -- y el cortocircuito se levanta sólo
// ante un flag de WA (`dmoj/judge.py:526-533`).  Un checker que devuelve
// `CheckerResult(True, 0.7 * point_value)` marca el caso como AC, no como WA, así
// que el lote queda en `passed_batches` **aunque sólo haya pagado el 70%**.  Es
// decir: ST3 sí se ejecuta acá, y falla por su propio caso, no por omisión.
//
// Comparar con `solo-chicos.cpp`, que falla ST2: ahí ST3 sí queda en `SC` sin
// correr.  Los dos envíos tienen un lote que no completan y la diferencia entre
// «omitida» y «fallada» es exactamente el puntaje de la subtarea anterior -- y por
// eso el reporte de `verify` distingue `SC` de `WA`.
//
// La construcción del caso válido es la misma que en `solo-chicos.cpp`: el patrón
// óptimo más un faro.  El costo es O(n).

#include "signature.hpp"

int iluminar(int n, int *faros) {
    const int optimo = (n + 4) / 5;

    if (n > 2000) {
        // Posiciones consecutivas: el formato es correcto, el objeto no ilumina la
        // ronda.  Con `optimo(n)` posiciones seguidas las demás quedan a oscuras
        // -- el checker lo rechaza y el lote paga 0.
        for (int j = 0; j < optimo; ++j) {
            faros[j] = j + 1;
        }
        return optimo;
    }

    // Cobertura válida con un faro de más, sobre el patrón óptimo 3, 8, 13, ...
    int usada[2100] = {0};
    int k = optimo;
    for (int j = 0; j < optimo; ++j) {
        faros[j] = (2 + 5 * j) % n + 1;
        usada[faros[j]] = 1;
    }
    for (int p = 1; p <= n; ++p) {
        if (!usada[p]) {
            faros[k++] = p;
            break;
        }
    }
    return k;
}
