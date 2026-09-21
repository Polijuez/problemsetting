## Fibonacci(10^12) mód 10^5

### Enunciado

Sea ~F(0) = 0~, ~F(1) = 1~ y ~F(n) = F(n-1) + F(n-2)~ para ~n \ge 2~ la sucesión
de Fibonacci.

Calculá los **últimos 5 dígitos** de ~F(10^{12})~, es decir
~F(10^{12}) \bmod 10^5~, y subí el resultado.

**Este problema no se resuelve programando dentro del juez.** El envío es un
archivo `.txt` con la respuesta y nada más: el juez no compila ni ejecuta tu
código, simplemente lee lo que escribiste y lo compara con la respuesta correcta.
Para obtener el número tenés que calcularlo *fuera* del juez -- a mano, con una
calculadora, o con un programa que corras en tu propia máquina -- y subir el
resultado.

### Formato de entrada

No hay entrada. El juez le da a tu envío un stdin vacío.

### Formato de salida

Un único entero: los últimos 5 dígitos de ~F(10^{12})~, **con exactamente cinco
dígitos**. Si el resto tuviera menos de cinco dígitos, se rellena con ceros a la
izquierda (por ejemplo, ~42~ se escribe ~00042~).

El archivo lo lee el ejecutor `TEXT` del juez, que es literalmente `cat`: el
contenido del `.txt` es tu salida. La comparación del juez mira la salida por
palabras y no le importa *cuánto* espacio las separa -- ni el que sobra al
principio o al final -- así que ~46875~, ~\ 46875~ y ~46875\ \ ~ cuentan como lo
mismo. Lo que sí importa es cualquier otro carácter: un dígito distinto, un
signo, o algo pegado al número, cambia la respuesta.

### Restricciones

- La respuesta es un número entre ~0~ y ~99999~.
- El tiempo y la memoria son irrelevantes: tu envío es un archivo de texto y el
  juez sólo lo copia a su salida.

### Cómo obtener la respuesta

La recurrencia directa es lineal en ~n~, y ~n = 10^{12}~ hace que iterarla sea
inviable: a mil millones de sumas por segundo siguen siendo unos 17 minutos. El
camino es **exponenciación de matrices**: la matriz ~[[1, 1], [1, 0]]~ elevada a
la ~n~ da ~[[F(n+1), F(n)], [F(n), F(n-1)]]~.

Cada producto de matrices ~2 \times 2~ cuesta una cantidad fija de operaciones, y
la potencia se calcula elevando al cuadrado ~\log_2 n~ veces, así que el total es
~O(\log n)~: unos 40 pasos para ~n = 10^{12}~. Como la suma y el producto son
compatibles con el resto, todo el cálculo puede hacerse módulo ~10^5~ sin
conservar los números gigantes, y el resultado son directamente los últimos 5
dígitos.

Ese método es el que usa el propio generador del problema
(`generator.py`, función `fibonacci_mod`) para producir la respuesta. Notá que el
generador **no** es la solución del problema: es una herramienta del autor. Nadie
lo ejecuta dentro del juez -- el juez sólo copia la respuesta a la salida.

### Puntaje

Este problema es **todo o nada**: 100 puntos si la respuesta es exactamente la
correcta, 0 en cualquier otro caso. No hay puntaje parcial, y por eso no hay
subtareas ni un checker propio: el juez compara texto y ya.
