# O(N^2): expande alrededor de cada centro (el algoritmo "clásico" del problema).
#
# Es *correcta*, y por eso es el envío interesante de la escalera: pasa ST1, ST2
# y ST3, y se cae en ST4 con la cadena uniforme de 10^5 caracteres, donde el peor
# caso son ~5*10^9 comparaciones.  En Python el caso de 5000 de ST3 tarda ~0.55 s
# medidos dentro del contenedor del juez, o sea que pasa con poco margen: la
# cuadrática no "casi no llega" a ST3, llega.
#
# En C++ esta misma idea aguanta mucho más, así que si reescribís este envío en
# C++ el corte de la escalera cambia: medilo con `problemsetting verify` en vez
# de suponerlo, que es el punto de todo el archivo de expectativas.
#
# El corte que de verdad importa es ST4 (N = 10^5): ahí sólo entra una solución
# lineal (Manacher, como en solution.cpp), y los casos uniformes y alternantes
# del generador son los que hacen visible esa separación; no los "arregles".
#
# Puntaje esperado (70/100) tomado de una corrida real de `problemsetting verify`.

import sys


def main():
    s = sys.stdin.readline().strip()
    n = len(s)
    mejor = 0
    for centro in range(n):
        # Palíndromo impar con centro en `centro`.
        lo, hi = centro, centro
        while lo >= 0 and hi < n and s[lo] == s[hi]:
            lo -= 1
            hi += 1
        mejor = max(mejor, hi - lo - 1)
        # Palíndromo par con centro entre `centro` y `centro + 1`.
        lo, hi = centro, centro + 1
        while lo >= 0 and hi < n and s[lo] == s[hi]:
            lo -= 1
            hi += 1
        mejor = max(mejor, hi - lo - 1)
    print(mejor)


main()
