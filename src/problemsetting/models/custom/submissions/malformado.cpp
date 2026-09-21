// Salida deliberadamente malformada: texto donde el formato pide números.
//
// Este archivo es el sujeto de la **comprobación 5** de `verify` ("the checker
// rejects a deliberately malformed output") y por eso lleva `role: checker-test`
// en submissions.yml.  No está acá para probar el problema sino para probar el
// *checker*: es la única evidencia de que la validación existe y de que la basura
// se **rechaza** en vez de romper el checker.
//
// Por qué elige este camino del checker, y no el del puntaje parcial:
//
//   * La salida no tiene ni una primera línea válida -- no hay un entero al
//     principio -- así que el checker cae en la rama que devuelve
//     `CheckerResult(False, 0)`, o sea **WA**.  Esa rama es baratísima y
//     determinista precisamente para poder rechazar basura temprano.
//   * El otro camino defensivo del checker, el de «primera línea válida, basura
//     después», devuelve puntaje **parcial** con `passed=True` -- o sea AC, no
//     WA.  Ese camino se ejercita en `tests/test_model_custom.py`, no acá, porque
//     un envío declarado `role: checker-test` que diera AC haría fallar la
//     comprobación 5 con el mensaje correcto: el checker aceptó basura.
//
// Si este envío diera `RTE`, la comprobación 5 también falla, y con razón: DMOJ
// saltea el checker cuando la submission ya falló por su cuenta
// (`dmoj/graders/standard.py:53-56`, los checkers pueden ser carísimos), así que
// un RTE significa que el checker nunca vio esta salida, no que la rechazó.  Por
// eso el programa sale limpio (0) y sólo imprime basura: el fallo tiene que venir
// del checker, no del proceso.
//
// Un checker que se comiera la excepción -- sin el `try` de `check()` -- daría
// error interno en vez de WA, y `verify` lo reportaría como un problema roto.
// Ese es exactamente el modo de falla que esta plantilla documenta.

#include <iostream>

int main() {
    // Ni siquiera lee el input: imprime algo que no es una cantidad de faros.
    std::cout << "tantos faros como hagan falta\n";
    return 0;
}
