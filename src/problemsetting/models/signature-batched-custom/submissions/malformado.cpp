// Envío deliberadamente malformado: el evaluador imprime una cantidad fuera del
// rango legal, así que la salida no es un objeto válido del problema.
// Es el sujeto de la comprobación 5 de `verify` (`role: checker-test`), que exige
// que el checker **rechace** una salida malformada en vez de romperse.
//
// Ojo con cómo se logra acá, porque en un problema de firma no es tan directo como
// en uno de E/S: el concursante no imprime nada -- el que imprime es el evaluador,
// y su formato es fijo.  Lo que este archivo sí controla es **el valor que
// devuelve**, que es la primera línea de la salida del evaluador.  Devolviendo un
// `K` negativo, el evaluador imprime un `-1` como primera línea; el bucle de
// impresión no se ejecuta, así que la salida queda como una sola línea con un
// entero fuera del rango del problema.
//
// El checker la rechaza en su rama determinista: la primera línea es un entero,
// pero `1 <= declarados <= n` no se cumple, así que devuelve
// `CheckerResult(False, 0)` -- WA -- sin llegar a parsear posiciones.  Es el mismo
// camino que documenta `batched-custom/submissions/malformado.cpp`, alcanzado por
// otra vía: allá la basura venía del texto, acá del valor de retorno.
//
// Un envío que devolviera un `K` mayor que las posiciones que escribió también
// sería malformado, pero de una forma distinta: el evaluador leería **fuera** del
// arreglo (comportamiento indefinido) para imprimir esas posiciones, así que no es
// un envío honesto ni determinista.  Por eso este archivo se queda en el `K`
// inválido, que el evaluador puede imprimir sin tocar memoria ajena.
//
// Si el checker estuviera roto aceptando esto, la comprobación 5 fallaría con «el
// checker aceptó una salida deliberadamente malformada».

#include "signature.hpp"

int iluminar(int n, int *faros) {
    (void)n;
    (void)faros;
    // Fuera del rango legal `1..n`, así que el checker lo rechaza antes de mirar
    // posiciones.  No se escribe nada en `faros`: el evaluador no va a leerlo.
    return -1;
}
