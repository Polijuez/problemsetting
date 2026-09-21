// Solución modelo del problema «subpalíndromo más largo» (plantilla del modelo
// `batched`).
//
// Este archivo es el que `problemsetting outputs` compila y corre sobre cada
// `cases/{i}.in` para producir `cases/{i}.out`.  Debe leer exactamente el mismo
// formato que escribe `generator.py` (`TestCase.write_file`): una línea con la
// cadena.
//
// Algoritmo: **Manacher**, O(|s|).  Es lo que hace falta para ST4 (N <= 10^5):
// la expansión alrededor de cada centro es O(N^2), y ver
// `submissions/cuadratico.py` -- exactamente eso -- pasa las tres primeras
// subtareas y da TLE en la cuarta.  Ese par de archivos es la demostración de
// que el límite de tiempo separa a las dos complejidades, y no un adorno del
// enunciado.
//
// Manacher sobre la cadena transformada: se intercalan separadores ('#' entre
// cada par de caracteres) para tratar longitudes pares e impares con el mismo
// código.  En la cadena transformada, un palíndromo de radio k corresponde a un
// palíndromo real de largo k en la original.

#include <algorithm>
#include <iostream>
#include <string>
#include <vector>

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    std::string s;
    if (!(std::cin >> s)) {
        return 1;  // input ausente o mal formado: mejor fallar ruidosamente
    }

    // Cadena transformada: #a#b#a# ...
    std::string t;
    t.reserve(2 * s.size() + 1);
    for (char c : s) {
        t.push_back('#');
        t.push_back(c);
    }
    t.push_back('#');

    const int n = static_cast<int>(t.size());
    std::vector<int> radio(n, 0);  // radio[i]: cuántos caracteres a cada lado
    int centro = 0, borde = 0;     // palíndromo más a la derecha ya conocido
    int mejor = 0;

    for (int i = 0; i < n; ++i) {
        int r = 0;
        if (i < borde) {
            // Dentro del palíndromo ya conocido se puede copiar el radio de la
            // posición espejo; lo que sobra se verifica carácter por carácter.
            r = std::min(radio[2 * centro - i], borde - i);
        }
        while (i - r - 1 >= 0 && i + r + 1 < n && t[i - r - 1] == t[i + r + 1]) {
            ++r;
        }
        radio[i] = r;
        if (i + r > borde) {
            centro = i;
            borde = i + r;
        }
        mejor = std::max(mejor, r);
    }

    // En la cadena transformada el radio es directamente el largo del
    // palíndromo en la cadena original (el separador aporta la mitad).
    std::cout << mejor << '\n';
    return 0;
}
