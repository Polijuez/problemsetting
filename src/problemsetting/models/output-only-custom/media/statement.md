## 100000 como suma de Fibonacci

### Enunciado

Sea ~F(1) = 1~, ~F(2) = 2~ y ~F(n) = F(n-1) + F(n-2)~ para ~n \ge 3~ la sucesión
de Fibonacci: ~1, 2, 3, 5, 8, 13, \dots~

Hay que escribir ~100000~ como **suma de números de Fibonacci**, usando la menor
cantidad de sumandos posible.  Un mismo número puede usarse más de una vez.

**Este problema no se resuelve programando dentro del juez.** El envío es un
archivo `.txt` con tu representación y nada más: el juez no compila ni ejecuta tu
código, simplemente lee lo que escribiste.  Para obtener la representación tenés
que calcularla *fuera* del juez -- a mano, con una calculadora, o con un programa
que corras en tu propia máquina -- y subir el resultado.

### Formato de entrada

No hay entrada. El juez le da a tu envío un stdin vacío.

### Formato de salida

Dos líneas:

1. ~K~: la cantidad de sumandos que estás usando.
2. ~K~ enteros ~a_1, \dots, a_K~ separados por espacios: los sumandos, **en
   cualquier orden**.

Los ~K~ enteros tienen que ser números de Fibonacci de la lista de arriba, y
pueden repetirse: ~1 + 1 + \dots~ es válido como representación (aunque no sea
buena).  El valor de ~K~ tiene que coincidir con la cantidad de números que
imprimís: la respuesta se juzga por los sumandos que efectivamente están, no por
lo que la primera línea afirma.

El archivo lo lee el ejecutor `TEXT` del juez, que es literalmente `cat`: el
contenido del `.txt` es tu salida. El checker mira la salida por palabras y no le
importa *cuánto* espacio las separa -- ni el que sobra al principio o al final,
ni si terminás con una línea vacía, ni si el archivo usa retornos de carro de
Windows -- así que el formato de espacios y saltos de línea es libre. Lo que sí
importa es cualquier otro carácter.

### Restricciones

- ~1 \le K \le 20~.
- Cada ~a_i~ tiene que ser un número de Fibonacci de la lista, y pueden repetirse.
- La suma de los ~a_i~ tiene que ser exactamente ~100000~.

### Puntaje

Este problema **no es todo o nada**: el puntaje depende de la calidad de tu
representación.

| Resultado | Puntaje |
|-----------|---------|
| una representación **válida** con ~K = 9~ (el mínimo) | ~100\%~ |
| una representación **válida** con ~K > 9~ hasta ~20~ | ~70\%~ |
| todo lo demás: la salida está mal formada, un sumando no es de Fibonacci, ~K~ está fuera de ~1..20~, o los sumandos no suman ~100000~ | ~0\%~ |

Una "representación válida" es una en la que los ~K~ sumandos son números de
Fibonacci y suman exactamente ~100000~.  Todo lo que no sea eso saca ~0\%~, por
bien formateado que esté: el puntaje mide **el objeto construido**, no haber
acertado el formato.

En particular, subir un archivo con sólo la primera línea (~9~, y nada más) saca
~0\%~.  Es tentador pensar que "escribí la cantidad correcta" merece algo, pero
acá no: la primera línea **declara**, no construye, y no hay ninguna entrada que
entender para escribirla.  Un checker que puntuara por la cantidad declarada te
daría ~100\%~ por escribir ~9~ y nada más; éste recalcula la suma de lo que
realmente mandaste.

### Por qué 9, y cómo se encuentra

El camino corto es el **algoritmo goloso**: tomar siempre el mayor número de
Fibonacci que todavía entra, restarlo, y repetir.  Para ~100000~ eso da

$$75025 + 17711 + 6765 + 377 + 89 + 21 + 8 + 3 + 1 = 100000,$$

que son ~9~ sumandos.  Que el goloso dé el **mínimo** -- y no sólo *algún* mínimo
-- es el teorema de Zeckendorf, y es la parte del problema que hay que justificar
para confiar en la respuesta: usar el mayor posible no puede ser peor que usar uno
más chico, porque dos Fibonacci chicos consecutivos se reemplazan por uno grande
(~F(m-1) + F(m-2) = F(m)~), y cualquier representación con repetidos se puede
reducir así hasta una sin repetidos sin aumentar la cantidad de sumandos.

Ese método es el que usa el propio generador del problema (`generator.py`,
función `zeckendorf`) para producir la respuesta, y el checker **no le cree**:
recalcula el mínimo por programación dinámica, sin suponer que el goloso sea
óptimo.  Notá que el generador **no** es la solución del problema: es una
herramienta del autor.  Nadie lo ejecuta dentro del juez -- el juez sólo copia tu
respuesta.

### Subtareas

Hay un único lote que vale los 100 puntos.  El puntaje parcial de este problema
viene del **checker**, no de una escalera de subtareas; un problema que necesite
las dos cosas usa el modelo `batched-custom`.
