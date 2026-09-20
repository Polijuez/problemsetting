// Fuerza bruta: suma los operandos avanzando de a uno.
//
// Es correcta en el rango chico y lentísima en el grande: con a = 0, b = 10^9 el
// bucle da mil millones de vueltas, así que en los casos límite de ST2 el juez la
// mata por tiempo (TLE) y en los chicos termina al instante.  Esa asimetría es
// exactamente lo que la hace útil: es correcta donde importa y no se puede usar
// como solución real.
//
// Dos papeles en el toolkit:
//
//   * `role: brute` en submissions.yml la declara como la referencia contra la
//     que `problemsetting stress` compara la solución modelo sobre casos
//     diminutos (`Generator.gen_small`), donde las 2000 iteraciones del rango
//     chico no cuestan nada.
//   * Es el envío que demuestra que un límite de tiempo existe: `verify` la
//     reporta con TLE en los casos grandes, y así el límite de meta.yml queda
//     justificado en vez de ser un número elegido a ojo.  En A+B, donde la
//     solución real es O(1), ningún límite razonable la deja pasar, así que acá
//     se declara sin veredicto esperado (se reporta, no hace fallar a verify).

#include <iostream>

static long long sumar_despacio(long long a, long long b) {
    long long total = a;
    const long long paso = (b >= 0) ? 1 : -1;
    for (long long i = 0; i != b; i += paso) {
        total += paso;
    }
    return total;
}

int main() {
    long long a, b;
    std::cin >> a >> b;
    std::cout << sumar_despacio(a, b) << '\n';
    return 0;
}
