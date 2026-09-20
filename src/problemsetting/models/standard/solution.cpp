// Solución modelo del problema A+B (plantilla del modelo `standard`).
//
// Este archivo es el que `problemsetting outputs` compila y corre sobre cada
// `cases/{i}.in` para producir `cases/{i}.out`.  Debe leer exactamente el mismo
// formato que escribe `generator.py` (`TestCase.write_file`): dos enteros en una
// línea.
//
// Sobre el tipo: con operandos de hasta ±10^9 la suma llega a ±2·10^9, que
// todavía entra en un `int` de 32 bits con signo (el máximo es 2^31 - 1 ≈
// 2.147·10^9).  Igual se usa `long long`, porque en A+B el costo es cero y
// porque el hábito importa: apenas una restricción suba a 2·10^9, o aparezca un
// tercer sumando, `int` desborda en silencio y el WA es difícil de ver.  Los
// casos límite de ST2 están para ejercitar esos extremos.

#include <iostream>

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    long long a, b;
    if (!(std::cin >> a >> b)) {
        return 1;  // input ausente o mal formado: mejor fallar ruidosamente
    }
    std::cout << a + b << '\n';
    return 0;
}
