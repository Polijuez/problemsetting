// Envío incorrecto a propósito: imprime a + b + 1.
//
// Sirve para dos cosas:
//
//   * `problemsetting verify` comprueba que este envío reciba el veredicto
//     declarado en submissions.yml (WA) -- si recibiera AC, el problema (o el
//     checker) está mal, no la submission.
//   * Falla *todos* los casos, así que el lote único del modelo `standard` corta
//     en el primer caso y el puntaje esperado es 0.
//
// Un envío que falla solo algunos casos es más útil (distingue "no entendió el
// problema" de "no cubre los límites"), pero en `standard` un solo caso fallado
// ya deja el puntaje en 0.  Para puntajes parciales, ver el modelo `batched`.

#include <iostream>

int main() {
    long long a, b;
    std::cin >> a >> b;
    std::cout << a + b + 1 << '\n';
    return 0;
}
