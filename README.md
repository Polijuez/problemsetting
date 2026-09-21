# problemsetting

Toolkit para escribir problemas de Polijuez (un juez DMOJ) y verificarlos en
local.  Genera los casos, produce las salidas esperadas, arma el archivo que se
sube al sitio y corre las submissions declaradas contra el mismo juez que usa
producción.

## Escribir un problema, paso a paso

```bash
# 1. Crear el esqueleto a partir de una plantilla (por defecto `standard`)
uv run problemsetting new --model standard suma

# 2. Editar los archivos que van (ver «Qué archivos se editan» más abajo)

# 3. Generar casos, salidas esperadas y el .zip
uv run problemsetting build suma

# 4. Calificar las submissions declaradas contra el juez
uv run problemsetting verify suma
```

Todos los subcomandos toman el **nombre del problema** y lo resuelven contra el
directorio actual (`Path.cwd() / problema`), así que se corren desde el
directorio que contiene al problema — el mismo desde el que corriste `new`, no
desde adentro del problema.

Salida real de `new`:

```
$ uv run problemsetting new --model standard suma
created suma/ from model 'standard'
  solution     solution.cpp lang=CPP17
  limits       tl=1.0s ml=262144KiB
  next steps
    edit generator.py, then           problemsetting cases suma
    cases + outputs + archive         problemsetting build suma
    grade the declared submissions    problemsetting verify suma
```

Salida real de `build`:

```
$ uv run problemsetting build suma
==> cases suma
suma: 21 cases, 21 input files -> cases/
  batch 1: 100 pts, 21 cases
wrote /.../suma/init.yml
==> outputs suma
  $ /run/current-system/sw/bin/g++ -Wall solution.cpp -DONLINE_JUDGE -O2 -lm -std=c++17 -fmax-errors=5 -s -o __meta__/outputs/solution
suma: 21 expected output(s) -> cases/
==> archive suma
/.../suma/suma.zip: 42 members
```

Salida real de `verify` (con el pool de jueces ya levantado; el resumen de
arriba, los otros dos envíos y los checks completos están recortados acá):

```
$ uv run problemsetting verify suma
==> verify suma  (model standard, judge polijuez-judge-1)
  1. solution.cpp                  model     CPP17   AC   score 100/100 (100/100 pts, tl=1s ml=262144KiB from limits[.cpp])
      batch 1  100/100 pts  AC  (AC 21)
      measured  slowest case 0.003s, max 4020 KiB
  2. submissions/incorrecto.cpp    -         CPP17   WA   score 0/100 (0/100 pts, tl=1s ml=262144KiB from limits[.cpp])
  3. submissions/fuerza-bruta.cpp  brute     CPP17   AC   score 100/100 (100/100 pts, tl=1s ml=262144KiB from limits[.cpp])
verify: 3 submission(s), 3 with expectations, 0 mismatch(es)
checks:
  1. model solution scores full marks                            PASS
  2. intended-wrong submissions get their declared verdict       PASS
  3. a correct-but-too-slow submission gets TLE                  SKIP
  4. brute force agrees with the model solution on the declared cases  PASS
  5. the checker rejects a deliberately malformed output         SKIP
  6. measurements are reported for calibration                   PASS
```

`verify` sale con estado 0 sólo si ningún envío declarado se desvió y ningún
check falló.

Salida real de `stress`:

```
$ uv run problemsetting stress suma --cases 20
==> stress suma  (model standard, seed 11960316, 20 case(s) from gen_small)
    model     solution.cpp (CPP17, tl=1.0s ml=262144KiB)
    brute     submissions/fuerza-bruta.cpp (CPP17, tl=1.0s ml=262144KiB)
    judges    polijuez-judge-1  (1 chunk(s) of ~20)
    brute     submissions/fuerza-bruta.cpp: no disagreement on 20 case(s)
stress: no counterexample -- the brute force agreed with the model solution on all 20 case(s) (seed 11960316)
```

**Elegí el nombre con cuidado.** El id del problema es el nombre del directorio,
y tiene que ser único entre *todos* los problemas que ve el juez: el pool monta
el checkout entero, así que también ve el testsuite que viene dentro de
`vendor/judge-server/testsuite/`.  Un problema llamado `aplusb`, `batched` o
`helloworld` choca con uno de esos y el juez lo avisa:

```
Warning: duplicate problem aplusb found at /problems/vendor/judge-server/testsuite/aplusb, ignoring in favour of /problems/work/readme/aplusb
```

Lo que se observa es peor que lo que dice el aviso: con un problema propio
llamado `aplusb`, `verify` califica contra los casos del problema vendido (los de
5, 20 y 75 puntos) y la solución modelo da `WA` con `0/100`, en vez de usar los
21 casos que declara tu `init.yml`.  Antes de bautizar el problema, comprobá que
el nombre no exista en `vendor/judge-server/testsuite/`.

### Requisito para `verify` (y `stress`): la imagen del juez

`verify` y `stress` no simulan nada: corren las submissions dentro de un
contenedor con el juez real.  El toolkit necesita la imagen

```
localhost/dmoj/judge-tier3:latest
```

Si no está, la construye él mismo a partir del submódulo `vendor/judge-server`
(el mismo `DMOJ/judge-server`, con `--build-arg TAG=master`):

```bash
uv run problemsetting judges build
```

**La primera construcción es grande y lenta**: la imagen pesa del orden de
15 GB, y bajarla y compilarla la primera vez tarda bastante.  Una vez construida
queda en el store de podman.  `judges build` construye siempre (para forzar una
imagen nueva hay que usar ese comando); `judges start` y `verify` construyen
**sólo si falta**.  `new`, `cases`, `outputs`, `archive` y `build` **no**
necesitan la imagen.

### El pool de jueces

Arrancar un juez tarda porque cada contenedor descubre los problemas y
autotestea todos los ejecutores.  Para no pagar eso en cada corrida, el toolkit
mantiene un pool de contenedores con nombre que sobrevive entre invocaciones:

```bash
uv run problemsetting judges start       # levanta el pool (default: min(nproc, 8))
uv run problemsetting judges status      # qué contenedores hay y en qué estado
uv run problemsetting judges update      # hace que re-descubran los problemas
uv run problemsetting judges stop        # los apaga y los borra
```

`verify` arranca uno solo si no hay ninguno corriendo.  El pool se apaga solo
tras un rato de inactividad (`--idle-timeout`, 1800 s por defecto).

**Trampa importante:** el pool monta este checkout en `/problems`, así que un
problema sólo se puede calificar si vive **dentro de este repo**.  Y DMOJ
descubre problemas con el `glob` de Python, que ignora los directorios que
empiezan con punto: un problema en `.scratch/` o `.work/` nunca se ve y toda
submission falla con `error: unknown problem`.  Usá un directorio normal, por
ejemplo `work/`.

`verify` y `stress` re-descubren los problemas en cada corrida (le piden al
contenedor que vuelva a escanear, así que un problema recién creado se ve sin
reiniciar nada).  `judges update` existe para el caso en que manejes un
contenedor por fuera del toolkit y quieras forzar el reescaneo a mano.

## Los 8 modelos

Un **modelo** es un preset: el problema se describe por ejes ortogonales
(grader, checker, batch, io, submission) y cada modelo fija una combinación.
`new --model <m>` copia la plantilla de ese modelo, que es un problema completo
y funcionando (no un esqueleto vacío) con comentarios que explican cada parte.

| Modelo | Descripción |
|---|---|
| `standard` | ICPC clásico: entrada/salida por stdin/stdout, todo o nada (un solo lote). |
| `batched` | Como `standard` pero con subtareas (un lote DMOJ por subtarea, con dependencias opcionales). |
| `custom` | Como `standard` pero con un `checker.py` propio, para puntaje por calidad u optimización (fraccionario). |
| `batched-custom` | Subtareas **y** checker propio. |
| `output-only` | El concursante sube un `.txt` con la respuesta, sin programa; todo o nada. |
| `output-only-custom` | Sube un `.txt` y un checker propio lo puntúa. |
| `signature-batched` | IOI: el concursante escribe **una función de C o C++** contra un header dado, con subtareas. |
| `signature-batched-custom` | Firma de C/C++ con subtareas **y** checker propio. |

Las plantillas viajan dentro del paquete y se agregan a medida que se
implementan; si un modelo todavía no tiene la suya, `new` falla nombrando las
que sí están disponibles en esta build, en vez de crear un problema incompleto.

Los presets están en `src/problemsetting/meta.py` (`MODELS`).  Los ejes se
resuelven de nuevo en cada corrida: `meta.yml` guarda `model:` más los
overrides, nunca la expansión.

### Codegolf

No hay un modelo `codegolf`.  Un problema de codegolf se puntúa por lo **corto**
del fuente, y toda la mecánica ya está en `custom`: el checker recibe
`submission_source`.  La receta comentada vive al final de
`src/problemsetting/models/custom/checker.py`, junto con lo que le falta para
ser un problema publicado (referencia de tamaño en el enunciado, normalización
del puntaje contra el total).

### Lo que ve el concursante en un problema de firma

En los modelos `signature-*` el concursante no escribe un programa sino **una
función** de C o C++ contra el header que se le da (`signature.hpp`).  El juez
compone el envío textualmente:

```
#include "signature.hpp"
#define main main_<uuid>
<el envío, tal cual>
```

y compila eso junto con `evaluator.cpp` (el archivo del autor, que aporta el
único `main` que existe) **en una sola invocación del compilador**, cada
archivo como su propia unidad de traducción, enlazadas al final.

De ahí sale la restricción que hay que documentarle al concursante: el
mecanismo **prefija el header y renombra `main`**, así que

* el código de interfaz **no puede definir su propio `main`** — el `main` del
  envío queda renombrado por el `#define`, de modo que un concursante que
  escribió un `main` para probar localmente no rompe la compilación, pero la
  interfaz del problema (el header) sí tiene prohibido definir uno;
* el `main` efectivo es el de `evaluator.cpp`, que es el que lee la entrada e
  imprime la respuesta, así que el envío sólo tiene que **definir** la función
  declarada, sin leer ni imprimir nada;
* el header **sólo declara**: lo incluyen tanto el envío como `evaluator.cpp`, y
  como cada uno es una unidad de traducción aparte, una definición ahí adentro
  da `multiple definition` al enlazar (a menos que sea `inline`).

El nombre de la función lo elige el autor del problema, pero una vez publicado
es la interfaz: cambiarlo invalida todos los envíos.  `signature.hpp`,
`evaluator.cpp` y `solution.cpp` tienen que estar de acuerdo.  Los detalles
están comentados en `signature.hpp`, que es el archivo que el concursante ve.

### Problemas con entrada/salida por archivo

**Todavía no están soportados.**  El eje `io:` los tiene reservado (`io: file`
es un valor declarado pero no implementado), así que agregarlos más adelante es
una plantilla nueva y no una migración de formato.  Hoy `io: file` es un error.

## Qué archivos se editan y cuáles se generan

Un problema es un directorio con un `meta.yml`.  El autor **edita**:

- `meta.yml` — la configuración escrita a mano (modelo, lenguaje de la solución,
  límites, overrides de ejes).
- `generator.py` — el generador de casos: qué casos se generan, cómo se escribe
  su input y a qué subtarea pertenece cada uno.
- `solution.<ext>` — la solución modelo, la que produce las salidas esperadas.
- `submissions.yml` — las submissions de prueba y el resultado que se espera de
  cada una.
- `media/` — el enunciado (`statement.md`) y los archivos que lo acompañan.

El toolkit **genera** (y por lo tanto **no se commitea**):

- `init.yml` — el archivo que lee DMOJ; sale de `meta.yml` + `generator.py`.
- `cases/*.in` y `cases/*.out` — los casos y sus salidas esperadas.
- `__meta__/` — caché incremental de `outputs` y binarios compilados.
- `*.zip` — el archivo que se sube al sitio.

Todos están en `.gitignore`.  Un `init.yml` o un `.zip` commiteado es un
artefacto viejo esperando a desincronizarse del generador.

## El esquema de `meta.yml`

Es el **único** archivo de configuración que se edita a mano.  Claves:

```yaml
model: standard          # requerido: uno de los 8 presets
solutionlang: .cpp       # requerido: extensión de la solución modelo
limits:                  # opcional: límites por lenguaje, valores absolutos
  .cpp:
    tl: 1.0              # segundos
    ml: 262144           # KiB (la unidad de DMOJ)
```

Además acepta overrides de los ejes del preset, todos opcionales:

- `grader`: `standard` | `signature`
- `checker`: `none` | `custom`
- `batch`: `single` | `subtasks`
- `io`: `stdio` | `file` (`file` todavía no implementado)
- `submission`: `program` | `text`
- `executor`: el ejecutor DMOJ con el que se corre la solución modelo (por
  ejemplo `CPP20` o `PYPY3`); si falta, se infiere de `solutionlang`.

Los límites son **absolutos**, en las unidades de DMOJ: `tl` en segundos y `ml`
en **KiB**.  No hay multiplicadores por sitio.  Un lenguaje que no aparezca en
`limits:` usa 2 s / 262144 KiB.

La extensión de `solutionlang` tiene que ser válida para el modelo: los modelos
de firma sólo aceptan `.c`/`.cpp` (el grader de firma de DMOJ existe únicamente
para C y C++), y los output-only sólo `.txt`.  Un override que contradiga al
preset (por ejemplo `model: standard` con `grader: signature` y un `.py`) es un
error al validar, no un problema que falla raro después.

La clave vieja `problemtype:` ya no existe: se llama `model:`.

## El esquema de `submissions.yml`

Es la lista de submissions del problema **y el resultado que se espera de cada
una**.  Cada entrada declara qué espera, y `verify` falla cuando la realidad no
coincide, en vez de asumir que todo lo que esté en `submissions/` debe dar AC.

```yaml
submissions:
  - source: solution.cpp        # requerido, relativo al directorio del problema
    verdict: AC                 # opcional: veredicto DMOJ que debe obtener
    score: 100                  # opcional: puntaje esperado, % del total (0..100)
    role: model                 # opcional: para qué sirve dentro del toolkit
    executor: CPP17             # opcional: overrides de la inferencia por sufijo
```

- **`source`** — ruta al archivo, relativa al directorio del problema.
- **`verdict`** — veredicto esperado: `AC`, `CE`, `IE`, `TLE`, `MLE`, `OLE`,
  `RTE`, `IR`, `WA` o `SC`.
- **`score`** — puntaje esperado como porcentaje del total del problema.
- **`role`** — informativo para `verify`, pero los checks y el stress lo leen en
  vez de volver a declarar la submission:
  - `model` — la solución modelo (la que produce los `.out`).
  - `brute` — la fuerza bruta de referencia, contra la que el stress test
    compara a la solución modelo en casos diminutos.
  - `checker-test` — salida deliberadamente malformada, para comprobar que el
    checker la rechaza en vez de romperse.
- **`executor`** — el ejecutor con el que correr esta submission cuando no se
  quiere inferir del sufijo.

Una entrada **sin `verdict` ni `score`** es informativa: se corre y se reporta,
pero no puede hacer fallar a `verify`.  Los límites salen de `meta.yml`: el
lenguaje se infiere del sufijo (con `executor` como override) y se usan el `tl`
y el `ml` declarados para ese lenguaje.

Los puntajes esperados de un problema con checker fraccionario hay que
anotarlos de una corrida real, no razonarlos: DMOJ corta el resto del lote
apenas un caso falla, y predecir a mano qué puntaje deja eso es exactamente cómo
se publican expectativas equivocadas.

## Los subcomandos

Estas son las descripciones tal como las imprime `problemsetting --help`:

```
problemsetting new       scaffold a new problem from a model template
problemsetting cases     generate cases/*.in and init.yml from the problem's generator.py
problemsetting outputs   run the model solution over every case to produce cases/*.out
problemsetting archive   zip the cases init.yml references into the declared archive
problemsetting build     run cases, outputs and archive in order
problemsetting judges    manage the judge image and the pool of long-lived judge containers
problemsetting verify    grade the submissions declared in submissions.yml and check their expectations
problemsetting stress    compare the model solution against the declared brute force on tiny random cases
```

- **`new <nombre>`** — crea el directorio del problema desde una plantilla.
  `--model`, `--solutionlang` (extensión de la solución modelo), `--force`
  (reemplaza el directorio si ya existe).  El nombre es el id del problema:
  minúsculas, dígitos, `-` y `_`, y como máximo 20 caracteres (el límite del
  sitio).
- **`cases <problema>`** — corre el `generator.py` y escribe `cases/*.in` +
  `init.yml`.  `--seed` fija la semilla (por defecto, la del propio generador).
- **`outputs <problema>`** — corre la solución modelo sobre cada caso y escribe
  `cases/*.out`.  Es incremental: si nada cambió, no recompila ni vuelve a
  correr; si se edita un caso, corre sólo ese caso.  Para los modelos
  output-only es una copia de archivo, no una ejecución.
- **`archive <problema>`** — mete en el `.zip` los casos que `init.yml`
  referencia.
- **`build <problema>`** — `cases` + `outputs` + `archive`, en orden.
- **`judges {build,start,status,stop,update}`** — la imagen y el pool.
  `--count` (tamaño del pool, `min(nproc, 8)` por defecto) y `--idle-timeout`.
- **`verify <problema>`** — califica cada entrada de `submissions.yml` en el
  juez y compara contra la expectativa declarada, e imprime seis checks
  nombrados: (1) la solución modelo saca el puntaje completo; (2) las
  submissions que deben fallar obtienen el veredicto declarado; (3) una
  submission correcta pero lenta da `TLE`; (4) la fuerza bruta coincide con la
  solución modelo en los casos declarados; (5) el checker rechaza una salida
  malformada; (6) el juez reporta las mediciones para calibrar los límites.  Un
  check que el problema no permite correr se imprime como **skip con el motivo**,
  nunca como un pass.
- **`stress <problema>`** — compara la solución modelo contra la fuerza bruta
  (`role: brute`) sobre casos diminutos aleatorios (`Generator.gen_small`), para
  encontrar el contraejemplo que `verify` no puede ver porque compara contra las
  salidas que la propia solución modelo produjo.  `--cases` (200 por defecto) y
  `--seed` (por defecto una por corrida, siempre reportada).  Corre todo dentro
  del juez, así que necesita el pool.

## Instalación

Este repo es **el** toolkit: los repos de problemas lo consumen como una
dependencia Git de `uv`, fijada a un commit.  Desde un repo de problemas:

```bash
uv add "problemsetting @ git+https://github.com/Polijuez/problemsetting@<commit-sha>"
```

Eso deja en el `pyproject.toml`:

```toml
[tool.uv.sources]
problemsetting = { git = "https://github.com/Polijuez/problemsetting", rev = "<commit-sha>" }
```

y el `uv.lock` fija el commit exacto, así que dos máquinas construyen las mismas
versiones.  La CLI queda disponible como `uv run problemsetting ...` dentro de
ese repo, y las plantillas viajan **dentro del paquete** (son package data), así
que no hay un directorio de plantillas que mantener sincronizado aparte.

Con la dependencia alcanza para `new`, `cases`, `outputs`, `archive` y `build`.
**`verify` y `stress` necesitan además un checkout del toolkit**, porque montan
el directorio que contiene `vendor/judge-server` (y desde ahí construyen la
imagen del juez) como `/problems` dentro del contenedor.  Una copia instalada
del paquete no tiene ese `vendor/`, así que el toolkit no puede adivinarlo: hay
que nombrárselo con la variable de entorno `PROBLEMSETTING_ROOT`, apuntando al
checkout del toolkit.  Y como el pool monta **ese** directorio, el problema que
se quiere calificar tiene que estar adentro suyo (ver «El pool de jueces»).

Para desarrollar el toolkit mismo alcanza con clonar este repo y `uv sync`;
`uv run problemsetting --help` muestra la superficie completa.

## Requisitos

- [`uv`](https://docs.astral.sh/uv/) y Python 3.13+.
- Un compilador de C/C++ en el `PATH` (`gcc`/`g++`) y `ghc`/`python3` si el
  problema usa Haskell o Python.  El runtime de Java se resuelve desde
  `$JAVA_HOME/bin` (el contenedor del juez ya trae Java).
- [`podman`](https://podman.io/) (rootless) para la imagen del juez y el pool.
- La imagen `localhost/dmoj/judge-tier3:latest` para `verify` y `stress`
  (`problemsetting judges build`).
