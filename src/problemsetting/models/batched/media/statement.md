## Subpalíndromo más largo

### Enunciado

Dada una cadena ~s~ formada por letras minúsculas, encontrá la longitud del
substring **contiguo** más largo que sea un palíndromo.  Un palíndromo es una
cadena que se lee igual de izquierda a derecha que de derecha a izquierda.

Por ejemplo, en ~s = \texttt{ababa}~ el palíndromo más largo es
~\texttt{ababa}~, de longitud 5; en ~s = \texttt{aabb}~ el más largo es
~\texttt{aa}~ (o ~\texttt{bb}~), de longitud 2.

Se pide **la longitud**, no el substring.

### Formato de entrada

Una única línea con la cadena ~s~, sin espacios.

### Formato de salida

Un único entero: la longitud del substring palindrómico más largo de ~s~.

### Restricciones

- ~s~ está formada sólo por letras minúsculas del alfabeto ~\{\texttt{a}, \texttt{b}\}~.
- ~1 \le |s| \le 10^5~.

### Subtareas

- **Subtarea 1 (20 puntos):** ~|s| \le 50~.
- **Subtarea 2 (25 puntos):** ~|s| \le 1000~.
- **Subtarea 3 (25 puntos):** ~|s| \le 5000~.  Se evalúa sólo si la Subtarea 2
  fue resuelta completamente.
- **Subtarea 4 (30 puntos):** ~|s| \le 10^5~, sin restricciones adicionales.

Los casos se acumulan hacia arriba: todo caso de la Subtarea 1 también es un caso
de la Subtarea 2, y así sucesivamente.  Una solución que sólo funciona para las
cadenas chicas no puede "zafar" de las grandes.

### Puntaje

| Subtarea | Puntaje |
|----------|---------|
| 1        | 20      |
| 2        | 25      |
| 3        | 25      |
| 4        | 30      |

Se obtiene el ~100\%~ de los puntos de una subtarea sólo si **todos** sus casos
son respondidos correctamente, y ~0\%~ en caso contrario.  El puntaje total es la
suma de los puntajes de cada subtarea.

La Subtarea 3 declara una **dependencia**: si la Subtarea 2 no se resuelve por
completo, los casos de la Subtarea 3 no se ejecutan y quedan marcados como
omitidos (~SC~).  Es una decisión del juez, no del enunciado: sus casos son los
mismos de la Subtarea 2 más los grandes, así que no tiene sentido correrlos si
los medianos ya fallaron.
