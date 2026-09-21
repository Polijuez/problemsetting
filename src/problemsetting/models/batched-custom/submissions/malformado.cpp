// Envío deliberadamente malformado: texto donde el formato pide números.
//
// Es el sujeto de la comprobación 5 de `verify` (`role: checker-test`), que
// exige que el checker **rechace** una salida malformada en vez de romperse.  El
// checker la rechaza en su rama barata y determinista -- la primera línea no es
// un entero -- y devuelve `CheckerResult(False, 0)`, que DMOJ traduce en WA.
//
// La distinción con `invalido.cpp` es la que importa:
//
//   * `invalido.cpp` es un objeto **inválido**: el formato está bien y la
//     construcción no ilumina la ronda.  Eso lo decide el *recalculo* de la
//     cobertura.
//   * este archivo es una salida **ilegible**: no hay objeto que validar.  Eso
//     lo decide el *parseo*.
//
// Los dos dan WA y 0, y los dos recorren caminos distintos del checker.  Un
// checker que se rompiera con basura -- una excepción en vez de un
// `CheckerResult` -- no daría WA: el juez la reportaría como error interno, o
// sea un problema roto, y `verify` lo diría al fallar esta comprobación.  Como
// el checker tampoco devuelve parcial acá (a diferencia de `custom`, que le da
// un piso a una primera línea válida), el resultado es 0 en cualquier lote.
//
// Si el checker estuviera roto aceptando esto, la comprobación 5 fallaría con
// «el checker aceptó una salida deliberadamente malformada».

#include <iostream>

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    long long n;
    if (!(std::cin >> n)) {
        return 1;
    }

    std::cout << "tantos faros como hagan falta\n";
    return 0;
}
