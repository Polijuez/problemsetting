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
según lo que la salida afirme.

Por ejemplo, para ~n = 6~ alcanzan dos faros, en las posiciones ~3~ y ~6~:
entre los dos iluminan ~1, 2, 3, 4, 5, 6~.

### Formato de entrada

Una única línea con un entero ~n~: la cantidad de posiciones de la ronda.

### Formato de salida

Dos líneas:

1. ~K~: la cantidad de faros que se colocan.
2. ~K~ enteros ~b_1, \dots, b_K~ separados por espacios: las posiciones de los
   faros, en cualquier orden.

Los ~K~ enteros tienen que ser distintos y estar entre ~1~ y ~n~.  El valor de
~K~ tiene que coincidir con la cantidad de posiciones que se imprimen.

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

Dentro de una subtarea, el puntaje parcial se acumula caso por caso.  Un caso
que la construcción no resuelve corta el resto de **esa** subtarea: los casos
siguientes no se ejecutan y no aportan su parte.  Una subtarea cuyos casos
corrieron todos y son válidos pero subóptimos otorga exactamente el ~70\%~ de
sus puntos.

### Subtareas

- **Subtarea 1 (10 puntos):** ~n \le 50~.
- **Subtarea 2 (20 puntos):** ~n \le 2000~.
- **Subtarea 3 (30 puntos):** ~n \le 50000~.  Se evalúa sólo si la Subtarea 2
  fue resuelta completamente.
- **Subtarea 4 (40 puntos):** ~n \le 200000~, sin restricciones adicionales.

Los casos se acumulan hacia arriba: todo caso de la Subtarea 1 también es un caso
de la Subtarea 2, y así sucesivamente.

La Subtarea 3 declara una **dependencia**: si la Subtarea 2 no se resuelve por
completo, los casos de la Subtarea 3 no se ejecutan y quedan marcados como
omitidos (~SC~).  Es una decisión del juez, no del enunciado: sus casos son los
mismos de la Subtarea 2 más los grandes, así que no tiene sentido correrlos si
los medianos ya fallaron.

Una subtarea con puntaje parcial **cuenta como resuelta** para la dependencia:
las dependencias miran los veredictos, no los puntajes, así que usar más faros
de los necesarios no bloquea a la subtarea siguiente.
