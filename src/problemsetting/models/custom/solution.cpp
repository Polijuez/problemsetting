// Solución modelo del problema «Faros» (plantilla del modelo `custom`).
//
// Este archivo es el que `problemsetting outputs` compila y corre sobre cada
// `cases/{i}.in` para producir `cases/{i}.out`.  Debe leer exactamente el mismo
// formato que escribe `generator.py` (`TestCase.write_file`): un entero `n` en
// una línea.
//
// Devuelve la construcción **óptima** del problema.  No es un detalle: el
// checker recalcula `óptimo(n)` y falla ruidosamente si este archivo no lo
// alcanza, porque entonces los `.out` estarían mal y ninguna submission podría
// sacar puntaje completo.  Es la asimetría que documenta `checker.py`: la
// submission es hostil y se aguanta; el artefacto del problema es nuestro y se
// exige.
//
// La construcción es un greedy sobre el círculo: se toma la primera posición sin
// iluminar y se pone un faro en la que le sigue, que cubre esa posición, la
// siguiente y la anterior.  Repetido hasta cubrir todo, da exactamente
// ceil(n/3) faros:
//
//   * cada faro cubre 3 posiciones nuevas, así que nunca se puede hacer con
//     menos de ceil(n/3);
//   * y el greedy siempre coloca esa cantidad, porque la posición elegida cubre
//     la primera descubierta y las dos siguientes.
//
// El caso chico es el que importa: con n = 1 o n = 2 la posición «siguiente» se
// da la vuelta y cae sobre una ya cubierta; el índice circular de abajo lo
// maneja sin un caso especial, y por eso el archivo es correcto para todo n >= 1
// y no sólo para los tamaños que el generador usa en el problema real.  Eso
// habilita `gen_small` (el stress test corre la fuerza bruta contra este archivo
// sobre n de 1 a 9, donde un caso de borde asoma).
//
// El costo es O(n): se recorre cada posición una vez.

#include <iostream>
#include <vector>

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    long long n;
    if (!(std::cin >> n)) {
        return 1;  // input ausente o mal formado: mejor fallar ruidosamente
    }

    // `cubierta` es 1-indexado por posición; las posiciones van de 1 a n.
    std::vector<char> cubierta(n + 1, 0);
    std::vector<long long> faros;

    // La primera posición descubierta: se le pone un faro a continuación, que la
    // cubre junto con las dos que siguen.
    auto siguiente = [&](long long posicion) { return posicion % n + 1; };

    for (long long primera = 1; primera <= n; ++primera) {
        if (cubierta[primera]) {
            continue;
        }
        long long faro = siguiente(primera);
        faros.push_back(faro);
        // Marca las tres posiciones que el faro ilumina (en círculo).
        for (long long delta = -1; delta <= 1; ++delta) {
            long long iluminada = (faro - 1 + delta + n) % n + 1;
            cubierta[iluminada] = 1;
        }
    }

    std::cout << faros.size() << '\n';
    for (size_t i = 0; i < faros.size(); ++i) {
        std::cout << (i ? " " : "") << faros[i];
    }
    std::cout << '\n';
    return 0;
}
