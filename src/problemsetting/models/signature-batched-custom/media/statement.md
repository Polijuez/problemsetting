## Ronda

### Enunciado

En una ronda hay ~n~ posiciones numeradas ~1, 2, \dots, n~, ubicadas en círculo:
la posición ~n~ es vecina de la ~1~.

Un faro colocado en la posición ~i~ ilumina las **dos** posiciones a cada lado,
además de la propia: ~i-2~, ~i-1~, ~i~, ~i+1~ e ~i+2~ (todas en círculo: si
~i = 1~, las anteriores son ~n~ y ~n-1~; si ~i = n~, las siguientes son ~1~ y
~2~).

Hay que **iluminar toda la ronda**.  Se gana el puntaje completo colocando la
**menor cantidad posible** de faros; cualquier otra cantidad válida obtiene
puntaje parcial, y se gana según los faros que la construcción usa de verdad, no
según lo que la función afirme.

Por ejemplo, para ~n = 6~ alcanzan dos faros, en las posiciones ~3~ y ~6~: entre
los dos iluminan ~1, 2, 3, 4, 5, 6~.

### Interfaz: tenés que implementar una función

A diferencia de un problema de entrada/salida, acá **no escribís un programa** ni
imprimís nada: escribís **una función**.  El juez te da este archivo de cabecera:

```cpp
int iluminar(int n, int *faros);
```

y compila tu envío junto con un evaluador que hace la entrada y la salida.  Tu
envío tiene que **definir** `iluminar` con exactamente esa firma.  La función:

- **recibe** ~n~ (la cantidad de posiciones de la ronda) y el arreglo `faros`,
  que el evaluador reserva con **capacidad ~n~**;
- **escribe** en `faros` las posiciones elegidas (en cualquier orden);
- **devuelve** la cantidad de faros que escribió.

No escribas `main`: lo aporta el evaluador.  Tampoco imprimas nada: el evaluador
imprime la cantidad que devolviste y las posiciones que escribiste, y a partir de
ahí se juzga tu construcción.

Escribir **más de ~n~ posiciones** no produce una respuesta incorrecta:
corrompe memoria, y tu programa falla.  El arreglo tiene exactamente la capacidad
que dice el enunciado, así que esa cantidad es un límite duro.

La función se puede implementar en **C o en C++**, a elección: la declaración está
escrita en el subconjunto común de los dos lenguajes para que sirva a los dos.  En
C++ el header envuelve la declaración en `extern "C"`, así que el símbolo es el
mismo desde cualquiera de los dos.  Lo que **no** se puede cambiar es el nombre ni
los tipos: son la interfaz del problema.  Una definición que no coincida -- por
ejemplo, una cuyo arreglo sea `const int *`, o que devuelva `long long` -- no
compila, y el veredicto es ~CE~.

### Formato de entrada

Una única línea con un entero ~n~: la cantidad de posiciones de la ronda.  Lo lee
el evaluador: vos no tenés que leer nada.

### Formato de salida

Dos líneas, las imprime el evaluador a partir del valor que devuelve tu función y
de lo que escribiste en `faros`:

1. ~K~: la cantidad de faros que colocaste (tu valor de retorno).
2. ~K~ enteros ~b_1, \dots, b_K~ separados por espacios: las posiciones que
   escribiste.

Los ~K~ enteros tienen que ser distintos y estar entre ~1~ y ~n~.  El valor de
~K~ tiene que coincidir con la cantidad de posiciones que escribiste.

### Restricciones

- ~1 \le n \le 200000~

### Puntaje

Este problema **no es todo o nada**: el puntaje depende de la calidad de la
construcción, y se reparte entre subtareas.

| Resultado | Puntaje |
|-----------|---------|
| ~K = \lceil n/5 \rceil~ (óptimo) | ~100\%~ del lote |
| ~K~ válido y como mucho el doble del óptimo | ~70\%~ del lote |
| ~K~ válido pero más del doble del óptimo | ~40\%~ del lote |
| la construcción no ilumina la ronda, o la salida está mal formada | ~0\%~ |

Una respuesta que no ilumina todas las posiciones saca ~0\%~ aunque el formato
esté bien: el puntaje mide el objeto construido, no haber acertado el formato.

Dentro de una subtarea, el puntaje parcial se acumula caso por caso.  Un caso que
la construcción no resuelve corta el resto de **esa** subtarea: los casos
siguientes no se ejecutan y no aportan su parte.  Una subtarea cuyos casos
corrieron todos y son válidos pero subóptimos otorga exactamente el ~70\%~ de sus
puntos.

### Subtareas

- **Subtarea 1 (10 puntos):** ~n \le 50~.
- **Subtarea 2 (20 puntos):** ~n \le 2000~.
- **Subtarea 3 (30 puntos):** ~n \le 50000~.  Se evalúa sólo si la Subtarea 2 fue
  resuelta completamente.
- **Subtarea 4 (40 puntos):** ~n \le 200000~, sin restricciones adicionales.

Los casos se acumulan hacia arriba: todo caso de la Subtarea 1 también es un caso
de la Subtarea 2, y así sucesivamente.

La Subtarea 3 declara una **dependencia**: si la Subtarea 2 no se resuelve por
completo, los casos de la Subtarea 3 no se ejecutan y quedan marcados como
omitidos (~SC~).  Es una decisión del juez, no del enunciado: sus casos son los
mismos de la Subtarea 2 más los grandes, así que no tiene sentido correrlos si los
medianos ya fallaron.

Una subtarea con puntaje parcial **cuenta como resuelta** para la dependencia: las
dependencias miran los veredictos, no los puntajes, así que usar más faros de los
necesarios no bloquea a la subtarea siguiente.
