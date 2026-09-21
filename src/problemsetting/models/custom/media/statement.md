## Faros

### Enunciado

En una isla hay una ronda de ~n~ posiciones numeradas ~1, 2, \dots, n~, ubicadas
en círculo: la posición ~n~ es vecina de la ~1~.

Un faro colocado en la posición ~i~ ilumina la posición ~i~, su vecina anterior
~i-1~ y su vecina siguiente ~i+1~ (todas en círculo: si ~i = 1~, la anterior es
~n~; si ~i = n~, la siguiente es ~1~).

Hay que **iluminar toda la ronda**.  Se gana el puntaje completo colocando la
**menor cantidad posible** de faros; cualquier otra cantidad válida obtiene
puntaje parcial.

Por ejemplo, para ~n = 6~ alcanza con dos faros, en las posiciones ~2~ y ~5~:
entre los dos iluminan ~1, 2, 3~ y ~4, 5, 6~.  Para ~n = 9~ alcanzan tres, en
~2, 5~ y ~8~.

### Formato de entrada

Una única línea con un entero ~n~: la cantidad de posiciones de la ronda.

### Formato de salida

Dos líneas:

1. ~K~: la cantidad de faros que se colocan.
2. ~K~ enteros ~b_1, \dots, b_K~ separados por espacios: las posiciones de los
   faros, en cualquier orden.

Los ~K~ enteros tienen que ser distintos y estar entre ~1~ y ~n~.  El valor de
~K~ tiene que coincidir con la cantidad de posiciones que se imprimen: la salida
se juzga por los faros que efectivamente están, no por lo que la primera línea
afirma.

### Restricciones

- ~1 \le n \le 18~
- ~3 \mid n~ en todos los casos del juez.

### Puntaje

Este problema **no es todo o nada**: el puntaje depende de la calidad de la
construcción.

| Resultado | Puntaje |
|-----------|---------|
| ~K = \lceil n/3 \rceil~ (óptimo) | ~100\%~ |
| ~K~ válido y como mucho el doble del óptimo | ~70\%~ |
| ~K~ válido pero más del doble del óptimo | ~40\%~ |
| la construcción no ilumina la ronda, o la salida está mal formada | ~0\%~ |

Una respuesta que no ilumina todas las posiciones saca ~0\%~ aunque el formato
esté bien: el puntaje mide el objeto construido, no haber acertado el formato.

### Subtareas

Hay un único lote que vale los 100 puntos.  El puntaje parcial de este problema
viene del **checker**, no de una escalera de subtareas; un problema que necesite
las dos cosas usa el modelo `batched-custom`.
