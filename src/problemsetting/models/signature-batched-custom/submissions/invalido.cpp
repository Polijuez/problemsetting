// Envío inválido a propósito: un solo faro, sin importar el tamaño de la ronda.
//
// El formato de salida es correcto -- una cantidad y esa cantidad de posiciones,
// que es lo que el evaluador imprime a partir del valor de retorno -- pero la
// construcción no ilumina el círculo.  Es la distinción que este modelo existe
// para mostrar: el checker **valida el objeto construido**, así que una salida
// bien formateada que no resuelve el problema saca 0, no «puntaje parcial por
// haber participado».
//
// El camino que ejercita: el checker parsea todo, encuentra que los faros no
// cubren todas las posiciones y devuelve `CheckerResult(False, 0)`.  Una
// submission así se ve igual que la subóptima -- mismo formato, misma cantidad de
// líneas -- y la única diferencia está en lo que el objeto *es*.  Ese es el caso
// que un checker que confiara en la cantidad declarada no podría distinguir.
//
// En submissions.yml se declara `verdict: WA` y `score: 0`, y también es el sujeto
// de la comprobación 2 de `verify` (un envío que debe fallar, falla).  El fallo es
// en **todos** los lotes, así que este envío no aporta nada a ningún lote: el
// primer caso de cada subtarea ya lo rechaza y el resto queda en `SC`.
//
// Si el checker estuviera roto aceptando cualquier cosa, este envío daría AC y
// `verify` fallaría en la comprobación 2.  O sea: este archivo es evidencia de que
// la validación existe.
//
// El costo es O(1).

#include "signature.hpp"

int iluminar(int n, int *faros) {
    // Un faro en la posición 1: ilumina 1, 2, 3 y las dos últimas posiciones.  Con
    // n <= 5 daría justo en el óptimo; el generador nunca produce esos tamaños
    // (ver TAMANOS_ST1 en generator.py: el más chico es 6).
    (void)n;
    faros[0] = 1;
    return 1;
}
