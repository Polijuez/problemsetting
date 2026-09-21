// Envío inválido a propósito: un solo faro, sin importar el tamaño de la ronda.
//
// El formato de salida es correcto -- una cantidad y esa cantidad de posiciones
// -- pero la construcción no ilumina el círculo.  Es la distinción que este
// modelo existe para mostrar: el checker **valida el objeto construido**, así
// que una salida bien formateada que no resuelve el problema saca 0, no «puntaje
// parcial por haber participado».
//
// El camino que ejercita: el checker parsea todo, encuentra que los faros no
// cubren todas las posiciones y devuelve `CheckerResult(False, 0)`.  Una
// submission así se ve igual que la subóptima -- mismo formato, misma cantidad
// de líneas -- y la única diferencia está en lo que el objeto *es*.  Ese es el
// caso que un checker que confiara en la cantidad declarada no podría distinguir.
//
// En submissions.yml se declara `verdict: WA` y `score: 0`, y también es el
// sujeto de la comprobación 2 de `verify` (un envío que debe fallar, falla).
//
// Si el checker estuviera roto de la otra forma -- aceptando cualquier cosa --
// este envío daría AC y `verify` fallaría en la comprobación 2.  O sea: este
// archivo es evidencia de que la validación existe.

#include <iostream>

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    long long n;
    if (!(std::cin >> n)) {
        return 1;
    }

    // Un faro en la posición 1: cubre 1, 2 y n.  Con n > 3 deja posiciones a
    // oscuras, y con n <= 3 daría justo en el óptimo, pero el generador del
    // problema nunca produce esos tamaños (ver `TAMANOS` en generator.py).
    std::cout << "1\n1\n";
    return 0;
}
