# Fuerza bruta O(N^3): recorre todos los substrings y verifica si es palíndromo.
#
# Sin poda por "el mejor hasta ahora": verifica *todos* los substrings, que es lo
# que hace el algoritmo de tres bucles del enunciado y lo que le da su costo real
# Theta(N^3).  Ese detalle no es cosmético y es la razón por la que este envío
# tarda lo que tarda: con una poda que descarte los substrings más cortos que el
# mejor ya visto, las cadenas uniformes ("aaaa...") se vuelven baratas -- el
# primer substring ya da la respuesta -- y la fuerza bruta pasaría la Subtarea 2
# sin haber demostrado nada.  Los casos uniformes y alternantes del generador
# existen justamente para castigar al bucle triple honesto.
#
# Esperado: pasa sólo la primera subtarea (20 puntos).  Con N <= 50 el costo es
# despreciable; con N <= 1000 la cadena uniforme de ST2 ya lo lleva por encima
# del límite de 1 s, así que ST2 falla, el resto de ST2 se corta (SC) y ST3 --
# que depende de ST2 -- no se corre en absoluto.  ST4 no tiene dependencia, así
# que sí se corre y también falla por tiempo.
#
# Es el envío que demuestra que la escalera de subtareas significa algo: una
# solución correcta pero de complejidad insuficiente *se lleva los puntos de la
# escalera que sí alcanza*, en vez de sacar 0 como en el modelo `standard`.
#
# El puntaje esperado de submissions.yml sale de una corrida real con
# `problemsetting verify`, no de razonarlo: en un problema con subtareas el
# puntaje que queda es una composición del corte del lote (que también dispara
# un TLE, porque un caso agotado lleva el flag de WA), de la omisión por
# dependencia y del orden en que ocurren, y adivinarla es exactamente cómo se
# publican expectativas equivocadas.

import sys


def palindromo(s, i, j):
    """¿Es `s[i:j+1]` un palíndromo?  Compara los extremos hacia adentro."""
    while i < j:
        if s[i] != s[j]:
            return False
        i += 1
        j -= 1
    return True


def main():
    s = sys.stdin.readline().strip()
    mejor = 0
    for i in range(len(s)):
        for j in range(i, len(s)):
            if palindromo(s, i, j):
                mejor = max(mejor, j - i + 1)
    print(mejor)


main()
