// Fuerza bruta: suma los operandos avanzando de a uno.
//
// Es correcta, y su costo es O(|b|): con b = 10^9 da mil millones de vueltas.
//
// Su papel en el toolkit es ser la **referencia del stress test**: `role: brute`
// en submissions.yml la declara como aquello contra lo que `problemsetting
// stress` compara la solución modelo sobre casos diminutos
// (`Generator.gen_small`), donde el rango chico hace que el costo sea
// despreciable.
//
// Sobre el tiempo: NO alcanza para demostrar el límite de meta.yml.  Medida con
// g++ -O2 (como compila el juez, ver `dmoj/executors/c_like_executor.py`) tarda
// ~0.24 s en el peor caso, contra un `tl` de 1 s, así que no da TLE y por eso acá
// no se declara veredicto esperado.  Es una limitación del problema, no del
// toolkit: A+B se resuelve en O(1), así que ningún envío correcto-pero-lento
// natural existe para este enunciado -- fabricar uno artificialmente (un bucle
// vacío gigante) no probaría nada sobre el límite.  La comprobación de "un envío
// correcto pero demasiado lento da TLE" se ejerce donde sí hay una escalera de
// complejidades real: el modelo `batched`.
//
// Si convertís este archivo en un envío que deba dar TLE, subí el trabajo por
// unidad hasta que el peor caso supere el `tl` declarado, y verificá el veredicto
// corriéndolo -- no lo deduzcas.

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
