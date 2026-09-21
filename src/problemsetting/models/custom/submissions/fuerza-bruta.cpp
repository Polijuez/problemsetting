// Fuerza bruta: codicioso obvio sobre el círculo.
//
// Es correcta y devuelve el óptimo, pero a diferencia de solution.cpp **no
// construye**: recorre el círculo tomando decisiones locales sin justificar por
// qué el resultado es mínimo.  Su papel en el toolkit es ser la **referencia del
// stress test**: `role: brute` en submissions.yml la declara como aquello contra
// lo que `problemsetting stress` compara la solución modelo sobre casos
// diminutos (`Generator.gen_small`), donde un caso de borde -- n = 1, 2, 3 -- sí
// asoma.
//
// O sea: en este problema la fuerza bruta es *la misma idea* que el modelo, sin
// la demostración.  Es lo honesto para un problema de optimización cuyo óptimo
// es una fórmula conocida; una fuerza bruta que probara todos los subconjuntos
// sería exponencial y no correría ni con n = 18.  Lo que importa para el stress
// test es que sea una **implementación independiente** del mismo criterio: así un
// error de índice (el clásico: olvidar que el vecino de n es 1) aparece como
// desacuerdo en vez de reproducirse en las dos.
//
// Chequeo de correctitud del lote único: como devuelve el óptimo en todos los
// casos, la comprobación de «un envío correcto pero demasiado lento da TLE» no
// aplica acá; para eso ver el modelo `batched`.  Y como saca puntaje completo,
// es también la evidencia de que el checker no castiga una construcción distinta
// de la del modelo.
//
// El costo es O(n), igual que la solución modelo: la diferencia está en la
// justificación, no en la cota.

#include <iostream>
#include <vector>

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    long long n;
    if (!(std::cin >> n)) {
        return 1;
    }

    std::vector<char> cubierta(n + 1, 0);
    std::vector<long long> faros;

    // Recorre el círculo dos veces: la segunda pasada cubre las posiciones del
    // final que el vecino de la 1 podría haber iluminado.
    for (long long vuelta = 0; vuelta < 2; ++vuelta) {
        for (long long posicion = 1; posicion <= n; ++posicion) {
            if (!cubierta[posicion]) {
                // Pone el faro en la posición siguiente y marca lo que ilumina.
                long long faro = posicion % n + 1;
                faros.push_back(faro);
                for (long long delta = -1; delta <= 1; ++delta) {
                    long long iluminada = (faro - 1 + delta + n) % n + 1;
                    cubierta[iluminada] = 1;
                }
            }
        }
    }

    std::cout << faros.size() << '\n';
    for (size_t i = 0; i < faros.size(); ++i) {
        std::cout << (i ? " " : "") << faros[i];
    }
    std::cout << '\n';
    return 0;
}
