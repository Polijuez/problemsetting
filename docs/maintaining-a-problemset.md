# Mantener un repositorio de problemas

Este documento es para **otra organización** (o para un mantenedor futuro) que
quiera levantar y operar su propio repositorio de problemas de Polijuez.

Vive en el toolkit —y no en el repositorio de problemas— a propósito: el toolkit
es lo que se vendoriza, así que quien vendoriza un commit del toolkit recibe
estas instrucciones **de ese commit**.  Si el toolkit cambia, cambia este
archivo con él, y el repositorio que lo vendoriza lo trae al actualizar el
submódulo.

Todos los comandos de este documento se corrieron contra el repositorio de
referencia (`problemset`, el repositorio privado de Polijuez) y la salida de los
bloques es la salida real de esas corridas: lo único que se recortó son rutas
absolutas (abreviadas con `/...`) y tramos repetidos (marcados con `...`).  Donde
un comando todavía no funciona tal cual, se dice y se explica por qué.

## 1. Obtener el repositorio, con sus submódulos

Un repositorio de problemas **vendoriza el toolkit como submódulo de git**, y el
toolkit a su vez vendoriza el `judge-server` de DMOJ como submódulo anidado:

```
problemas/                      (tu repositorio)
  vendor/problemsetting/        submódulo 1: el toolkit
    vendor/judge-server/        submódulo 2 (anidado): el juez de DMOJ
```

Por eso el clon no alcanza con `git clone`:

```console
$ git clone <url-del-repositorio> problemset
$ cd problemset
$ git submodule update --init --recursive
Submodule 'vendor/problemsetting' (https://github.com/Polijuez/problemsetting) registered for path 'vendor/problemsetting'
Cloning into 'problemset/vendor/problemsetting'...
Submodule path 'vendor/problemsetting': checked out '6f1d5601f1d0d5362846109fde16024f9a23806a'
Submodule 'vendor/judge-server' (https://github.com/DMOJ/judge-server.git) registered for path 'vendor/problemsetting/vendor/judge-server'
Cloning into 'problemset/vendor/problemsetting/vendor/judge-server'...
Submodule path 'vendor/problemsetting/vendor/judge-server': checked out '5ef74c5d6cad9efb2e86a5bb8ff2c90aaa6e435c'
```

(Esta corrida se hizo apuntando el submódulo a un checkout local del toolkit,
porque el pin actual todavía no está publicado — ver la subsección siguiente.
Con el commit empujado, la misma orden produce el mismo resultado desde el
remoto público.)

**`--recursive` no es opcional.**  Sin él, `git submodule update --init` llena
`vendor/problemsetting` y **deja vacío** `vendor/problemsetting/vendor/judge-server`,
que es un submódulo *del toolkit*.  Medido: tras un `--init` sin `--recursive`,
ese directorio existe pero tiene 0 entradas; con `--recursive`, 11.  La imagen
del juez se construye desde ahí (el contexto de build es su `.docker/tier3`), así
que sin el `--recursive` el primer `judges build` falla.

El `--recursive` además recorre los submódulos anidados que `git` encuentre.  En
los commits pinneados hoy el único que queda registrado es
`vendor/problemsetting/vendor/judge-server`; el `judge-server` declara un
submódulo propio en su `.gitmodules` (`dmoj/executors/java_sandbox`, que en este
commit viaja como `java_sandbox.jar` y no como *gitlink*), así que eso es lo que
`--recursive` cubre en general aunque hoy no materialice una tercera entrada.

### El pin del submódulo todavía necesita un push

El submódulo nombra una **revisión pública** del toolkit, no una ruta local.  En
este momento el pin apunta a `6f1d560`, un commit que **no está publicado**: el
toolkit local está 5 commits adelante de `origin/master` y esos commits no se
han empujado.  Por eso, hoy, un clon desde el remoto público falla:

```console
$ git submodule update --init --recursive
fatal: remote error: upload-pack: not our ref 6f1d5601f1d0d5362846109fde16024f9a23806a
fatal: Fetched in submodule path 'vendor/problemsetting', but it did not contain 6f1d5601f1d0d5362846109fde16024f9a23806a. Direct fetching of that commit failed.
```

**Remedio:** los commits del toolkit que el pin referencia tienen que estar
empujados al remoto público *antes* de clonar.  Es una decisión del dueño del
repositorio, no un bug del repositorio de problemas: el pin es correcto, lo que
falta es publicar el commit.  Mientras no se empuje, la única forma de
inicializar el submódulo es apuntarlo a un checkout local que sí tenga el commit:

```console
$ git config submodule."vendor/problemsetting".url /ruta/al/toolkit
$ git -c protocol.file.allow=always submodule update --init --recursive
```

(La verificación de la sección «Clon recién hecho», más abajo, se hizo así —con
la URL del submódulo apuntada a un checkout local—: es una muleta para probar en
este entorno, no el procedimiento documentado.)

## 2. Dejar el toolkit vendorizado utilizable

El toolkit corre desde **su propio virtualenv**, el que `uv sync` crea dentro del
submódulo.  No hace falta un `pyproject.toml` en el repositorio de problemas ni
declarar el toolkit como dependencia `uv`: el toolkit ya es un submódulo, y su
`.venv` es local al submódulo.

```console
$ (cd vendor/problemsetting && uv sync)
$ ./problemsetting --version
problemsetting 0.1.0
```

El shim `./problemsetting` de la raíz del repositorio hace `exec` del console
script del venv, así que la invocación no depende de recordar una ruta larga.
Falla con un mensaje accionable si los submódulos no están inicializados o si el
venv todavía no existe:

```console
$ ./problemsetting --version
error: the vendored toolkit at /.../vendor/problemsetting is not set up yet (no /.../vendor/problemsetting/.venv/bin/problemsetting)

The console script comes from the toolkit's own virtualenv, which uv creates.
In /.../vendor/problemsetting run:

    uv sync

Then re-run this command.
```

Con el venv ya creado, `verify` y `stress` necesitan además la imagen del juez
(sección 7).  `new`, `cases`, `outputs`, `archive`, `build` y `regenerate` no la
necesitan.

## 3. La estructura del repositorio: las dos raíces

Acá está la confusión más común, así que conviene decirla entera: **hay dos
raíces, y son distintas.**

| Raíz | Qué es | Para qué |
|---|---|---|
| **raíz del toolkit** — `vendor/problemsetting/` | el checkout del toolkit, el que contiene `vendor/judge-server/` | de dónde se **construye la imagen del juez** |
| **raíz de problemas** — `problems/` | el directorio del repositorio de problemas | qué se **monta como `/problems`** dentro de los contenedores |

En un repositorio de problemas se monta **sólo** `problems/`, nunca el toolkit ni
su `judge-server`.  Consecuencia directa: **todo problema calificable tiene que
vivir bajo `problems/`**.  Y el toolkit y su testsuite (`vendor/judge-server/testsuite/`,
~46 problemas) quedan estructuralmente fuera del alcance del contenedor, no
enmascarados por corrida.

La raíz de problemas se resuelve en tres pasos, en este orden:

1. `PROBLEMS_ROOT`, si está definida: nombra la raíz sin ambigüedad.
2. **Detección**: se camina hacia arriba desde el directorio actual buscando un
   directorio que tenga **ambos** `problems/` y `vendor/problemsetting/` — esa
   combinación es la firma de un repositorio de problemas.  Cualquiera de los dos
   por separado no significa nada (el checkout del toolkit tiene `vendor/`, pero
   no `problems/`).
3. Si no se detecta nada, cae a la **raíz del toolkit**.  Ese es el caso del
   toolkit mismo, donde el toolkit *es* la raíz de problemas; es lo que usan sus
   propios tests.

Gracias a la detección, correr un comando desde cualquier subdirectorio del
repositorio resuelve igual de bien:

```console
$ cd problems/suma && ../../problemsetting cases suma
suma: 21 cases, 21 input files -> cases/
  batch 1: 100 pts, 21 cases
wrote /.../problemset/problems/suma/init.yml
```

Los comandos aceptan tanto `<problema>` (resuelto contra la raíz de problemas)
como `problems/<problema>` (resuelto contra el directorio actual).  Si un nombre
desnudo existe en los dos lugares **y no son el mismo directorio**, se rechaza en
vez de elegir uno en silencio:

```console
$ cd /tmp && PROBLEMS_ROOT=/.../problemset/problems \
    /.../problemset/problemsetting cases suma
error: 'suma' names two different directories: /tmp/suma and /.../problemset/problems/suma.  The problems root is /.../problemset/problems; pass the path you mean
```

### Qué se commitea y qué se genera

El repositorio commitea las **entradas** de un build y los **checksums** de lo
que produjeron; nunca los datos de test.

```
problems/
  <slug>/
    meta.yml                    <- se commitea (se edita a mano)
    generator.py                <- se commitea (se edita a mano)
    solution.cpp                <- se commitea (se edita a mano)
    submissions.yml             <- se commitea (se edita a mano)
    submissions/                <- se commitea
    media/statement.md          <- se commitea
    <slug>.zip.sha256sum        <- SE COMMITEA
    <slug>.zip.cases.sha256sum  <- SE COMMITEA
    init.yml                    <- se genera (ignorado)
    cases/*.in, cases/*.out     <- se genera (ignorado)
    <slug>.zip                  <- se genera (ignorado)
    __meta__/                   <- se genera (ignorado)
vendor/problemsetting/          <- submódulo
problemsetting                  <- shim ejecutable, se commitea
```

Un `init.yml` o un `.zip` commiteado es un artefacto viejo esperando a
desincronizarse del generador.  Los dos checksums sí van versionados: el primero
ata el artefacto empaquetado a las fuentes commiteadas, y el segundo es un
checksum independiente sobre los datos de caso en sí.

## 4. Escribir un problema

El toolkit trae 8 modelos (presets).  `new` copia la plantilla de uno, que es un
problema completo y funcionando, no un esqueleto vacío:

```console
$ ./problemsetting new --model standard mi-problema
created mi-problema/ from model 'standard'
  solution     solution.cpp lang=CPP17
  limits       tl=1.0s ml=262144KiB
  next steps
    edit generator.py, then           problemsetting cases mi-problema
    cases + outputs + archive         problemsetting build mi-problema
    grade the declared submissions    problemsetting verify mi-problema
```

Corrido en la raíz del repositorio (o en su `problems/`), `new` crea el problema
**bajo `problems/`**, que es donde tiene que estar para ser calificable.
`--model`/`-m` elige el preset, `--solutionlang`/`-s` la extensión de la solución
modelo, y `--force` reemplaza un directorio existente.

**Elegí el nombre con cuidado.**  Tiene que ser único entre *todos* los problemas
que el juez ve, y el sitio rechaza nombres de más de 20 caracteres:

```console
$ ./problemsetting new this-name-is-way-too-long
error: problem name 'this-name-is-way-too-long' is 25 characters; the judge site accepts at most 20
```

Un modelo que no existe falla nombrando los que sí hay en esta build:

```console
$ ./problemsetting new -m bogus x
error: unknown model 'bogus'; valid models: batched, batched-custom, custom, output-only, output-only-custom, signature-batched, signature-batched-custom, standard
```

Qué se edita a mano: `meta.yml` (modelo, lenguaje de la solución, límites,
overrides de ejes), `generator.py` (qué casos se generan), `solution.<ext>` (la
solución modelo, la que produce los `.out`), `submissions.yml` (los envíos de
prueba y su resultado esperado) y `media/` (el enunciado).  El esquema de cada
archivo está comentado en la plantilla; la referencia de los 8 modelos y de los
esquemas de `meta.yml` y `submissions.yml` está en el `README.md` del toolkit.

## 5. Generar los casos

```console
$ ./problemsetting cases mi-problema
mi-problema: 21 cases, 21 input files -> cases/
  batch 1: 100 pts, 21 cases
wrote /.../problems/mi-problema/init.yml
```

`cases` corre `generator.py` y escribe `cases/*.in` + `init.yml`.  Después,
`outputs` corre la solución modelo sobre cada caso y escribe los `*.out`:

```console
$ ./problemsetting outputs mi-problema
  $ /run/current-system/sw/bin/g++ -Wall solution.cpp -DONLINE_JUDGE -O2 -lm -std=c++17 -fmax-errors=5 -s -o __meta__/outputs/solution
mi-problema: 21 expected output(s) -> cases/
```

La segunda corrida, sin cambios, no recompila ni vuelve a correr:

```console
$ ./problemsetting outputs mi-problema
mi-problema: 21 expected output(s) already up to date
```

`outputs` es incremental: si nada cambió no recompila ni vuelve a correr; si se
edita un caso, corre sólo ese caso.

## 6. Producir el archivo

```console
$ ./problemsetting archive mi-problema
/.../problems/mi-problema/mi-problema.zip: 42 members
/.../problems/mi-problema/mi-problema.zip.sha256sum: sha256 of the archive
/.../problems/mi-problema/mi-problema.zip.cases.sha256sum: sha256 of the case data
```

`archive` mete en el `.zip` los casos que `init.yml` referencia y escribe los dos
checksums al lado.  `build` hace los tres pasos en orden:

```console
$ ./problemsetting build mi-problema
==> cases mi-problema
mi-problema: 21 cases, 21 input files -> cases/
  batch 1: 100 pts, 21 cases
wrote /.../problems/mi-problema/init.yml
==> outputs mi-problema
mi-problema: 21 expected output(s) already up to date
==> archive mi-problema
/.../problems/mi-problema/mi-problema.zip: 42 members
/.../problems/mi-problema/mi-problema.zip.sha256sum: sha256 of the archive
/.../problems/mi-problema/mi-problema.zip.cases.sha256sum: sha256 of the case data
```

El nombre del archivo lo declara `init.yml` (`archive:`), y el nombre de los
checksums se deriva de ahí, así que el archivo y su checksum siempre coinciden.

## 7. Calificar en local

`verify` y `stress` no simulan nada: corren los envíos dentro de un contenedor
con el juez real.  Hace falta la imagen:

```console
$ ./problemsetting judges build
applied hask-mempolicy.patch to the judge-server submodule
building localhost/dmoj/judge-tier3:latest from /.../vendor/problemsetting/vendor/judge-server/.docker/tier3
  base image dmoj/runtimes-tier3; this pull plus build is multi-GB and slow
...
Successfully tagged localhost/dmoj/judge-tier3:latest
```

**La primera construcción es grande y lenta** (~15 GB), y una vez construida
queda en el store de podman.  `judges build` construye siempre; `judges start` y
`verify` construyen sólo si falta.

Arrancar un juez tarda porque cada contenedor descubre los problemas y
autotestea todos los ejecutores.  Para no pagar eso en cada corrida hay un pool
de contenedores con nombre:

```console
$ ./problemsetting judges start
started polijuez-judge-1
...
8 judge container(s) available; waiting for discovery
  polijuez-judge-1 ready
  ...
$ ./problemsetting judges status
  polijuez-judge-1  running  mounted on /.../problemset/problems
  ...
image  localhost/dmoj/judge-tier3:latest  present
```

`judges status` imprime **qué raíz monta cada contenedor**, que es lo que explica
un rechazo (sección «Fallos probables»).  El pool se apaga solo tras un rato de
inactividad (`--idle-timeout`, 1800 s por defecto) y se apaga y borra a mano con
`judges stop`.

Con el pool arriba:

```console
$ ./problemsetting verify mi-problema
==> verify mi-problema  (model standard, judge polijuez-judge-1)
  1. solution.cpp                  model     CPP17   AC   score 100/100 ...
  2. submissions/incorrecto.cpp    -         CPP17   WA   score 0/100 ...
  3. submissions/fuerza-bruta.cpp  brute     CPP17   AC   score 100/100 ...
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
check falló.  Un check que el problema no permite correr se imprime como **skip
con el motivo**, nunca como un pass.

`verify` y `stress` re-descubren los problemas en cada corrida, así que un
problema recién creado se ve sin reiniciar nada.  `judges update` existe para el
caso en que manejes un contenedor por fuera del toolkit y quieras forzar el
reescaneo a mano:

```console
$ ./problemsetting judges update
polijuez-judge-1: 200 As you wish.
...
```

`stress` compara la solución modelo contra el envío declarado `role: brute` sobre
casos diminutos aleatorios:

```console
$ ./problemsetting stress mi-problema --cases 20
==> stress mi-problema  (model standard, seed 1661355656, 20 case(s) from gen_small)
    ...
stress: no counterexample -- the brute force agreed with the model solution on all 20 case(s)
```

## 8. El flujo de regeneración y los checksums

Un clon recién hecho **no trae los casos**: trae las fuentes y los checksums.
`regenerate` cierra el círculo: reconstruye `cases/`, `init.yml`, el `.zip` y los
checksums, y reporta por problema si el rebuild sigue coincidiendo.

```console
$ ./problemsetting regenerate --check
==> regenerate 2 problem(s)  (check: nothing is written)
==> cases subpalindromo
subpalindromo: 28 cases, 28 input files -> cases/
  batch 1: 20 pts, 10 cases
  ...
wrote /tmp/regenerate-subpalindromo-jlcakvap/subpalindromo/init.yml
...
  OK    subpalindromo  subpalindromo.zip.cases.sha256sum, subpalindromo.zip.sha256sum match the rebuild
  OK    suma           suma.zip.cases.sha256sum, suma.zip.sha256sum match the rebuild
regenerate: 2 OK
```

(Estos dos son los problemas que el repositorio de referencia trae commiteados;
`mi-problema`, creado en la sección 4, aparecería como una tercera línea.)

Tres resultados posibles, por problema:

- **`OK`** — el rebuild coincide con los checksums commiteados.
- **`NEW`** — no hay nada commiteado con qué comparar: es el primer build.
- **`DRIFT`** — el generador commiteado ya no reproduce el checksum commiteado.
  Un rebuild con drift **no** pisa el checksum commiteado, y `regenerate` sale
  con estado distinto de cero: el fallo tiene que verse, no auto-repararse.

```console
$ ./problemsetting regenerate --check suma
==> cases suma
suma: 21 cases, 21 input files -> cases/
  batch 1: 100 pts, 21 cases
wrote /tmp/regenerate-suma-s3wafg8_/suma/init.yml
==> outputs suma
suma: 10 of 21 expected output(s) rebuilt, 11 reused -> cases/
==> archive suma
/tmp/regenerate-suma-s3wafg8_/suma/suma.zip: 42 members
  DRIFT suma  suma.zip.cases.sha256sum: the rebuild differs from the committed checksum
        suma.zip.sha256sum: the rebuild differs from the committed checksum
regenerate: 1 DRIFT
```

Ese `DRIFT` se provocó cambiando a mano la semilla del `generator.py`; los
checksums commiteados quedaron intactos.

Sin argumento recorre todos los problemas bajo la raíz de problemas; con un
problema, sólo ése.  `--check` construye una copia temporal y compara **sin
escribir nada** — es la forma segura de correrlo en CI, porque no puede
«arreglar» un drift pisando el checksum.  `--seed` fija la semilla del generador.

Cuando `verify`, `outputs` o `archive` no encuentran `init.yml`, el error nombra
los checksums y apunta a este comando:

```console
$ rm -rf problems/suma/cases problems/suma/init.yml problems/suma/__meta__
$ ./problemsetting verify suma
error: /.../problemset/problems/suma/init.yml not found -- init.yml, the cases it names and the committed `*.sha256sum` checksums beside them are all build products of meta.yml and generator.py; rebuild them with `problemsetting regenerate suma`
```

### Clon recién hecho, paso a paso

```bash
git clone <url-del-repositorio> problemset
cd problemset
git submodule update --init --recursive      # --recursive es obligatorio
(cd vendor/problemsetting && uv sync)        # crea el venv del toolkit
./problemsetting regenerate                  # reconstruye los casos y verifica los checksums
./problemsetting judges start                # (una vez) arranca el pool
./problemsetting verify mi-problema          # califica
```

## 9. Los dos fallos probables, y su arreglo

### a. El submódulo anidado del juez quedó vacío

Síntoma: `judges build` (o `verify`, si la imagen falta) falla nombrando el
submódulo.  Causa: el clon no usó `--recursive`, así que
`vendor/problemsetting/vendor/judge-server` quedó vacío.

```console
$ ./problemsetting judges build
error: the vendored judge-server is missing or empty at /.../vendor/problemsetting/vendor/judge-server.
  The judge image is built from it (the build context is its .docker/ directory), so it has to be populated first.
  Populate it in /.../vendor/problemsetting with:  git submodule update --init --recursive
  --recursive is required: judge-server has a submodule of its own (dmoj/executors/java_sandbox), which the image build needs.
```

El texto exacto del error depende del commit del toolkit que estés usando.  El
pin de los repositorios actuales (`6f1d560`) imprime, con el mismo espíritu pero
otro comando:

```console
$ ./problemsetting judges build
error: no image build context at /.../vendor/problemsetting/vendor/judge-server/.docker/tier3; the judge-server submodule is missing -- fetch it with 'git submodule update --init --depth 1 vendor/judge-server'
```

**Arreglo:** correr el `--recursive` en el checkout del toolkit.  Es el comando
que funciona en ambos commits:

```bash
git submodule update --init --recursive
```

Un submódulo pintado de vacío no impide calificar **si la imagen ya está
construida**: el submódulo se necesita sólo cuando el build —el único paso que
lee el código del juez— va a correr de verdad.  Por eso `verify` puede funcionar
con una imagen presente y un `vendor/judge-server` vacío, y `judges build` no.

### b. El pool pertenece a otro repositorio

Síntoma: `verify`, `stress` o `judges start` rechazan el pool.  Causa: el pool
default se reusa entre invocaciones, y un contenedor arrancado para el root de
**otro** repositorio sigue vivo.  El toolkit lee la raíz montada **del propio
contenedor** (`podman inspect`), no de nada que haya anotado, así que la
diferencia se detecta y se rechaza en vez de calificar contra los problemas
equivocados:

```console
$ ./problemsetting verify mi-problema
error: judge container polijuez-judge-1 already exists but must not be reused: this command grades against /tmp/psclone/problems, while polijuez-judge-1 is mounted on /.../problemset/problems.  A verdict from it would describe a different set of problems.  Stop the foreign pool and start one for this root: 'problemsetting judges stop', then 'problemsetting judges start'.
```

**Arreglo:** parar el pool ajeno y arrancar uno para esta raíz:

```console
$ ./problemsetting judges stop
stopped polijuez-judge-1
...
$ ./problemsetting judges start
```

`judges status` muestra la raíz montada de cada contenedor antes de intentar
calificar, así que el conflicto se ve antes de que el rechazo aparezca.

## 10. La toolchain: qué fija el flake y qué no

La toolchain soportada la fija la infraestructura de la organización con un flake
de Nix: `infra/flake.lock` pinea `nixpkgs` (rev
`95ca1e203c0750115fd4a6f17d5a245dfe6b1edd`), así que `uv`, `podman` y el
compilador salen de un conjunto de paquetes fijo en vez de la máquina de turno.
Del lado del toolkit, `requires-python` es amplio (`>=3.13`) a propósito, y
`uv.lock` pinea las dependencias de Python.

**Pero el pin de la toolchain fija las herramientas, no los artefactos
generados.**  Que dos máquinas corran el mismo `uv` y el mismo `g++` no hace que
el `.zip` sea idéntico: la reproducibilidad del **dato generado** viene del flujo
de generación, no del flake.  Dos cosas la sostienen:

1. El `generator.py` usa una semilla fija (`SEMILLA`) y documenta por qué no hay
   que usar `random.seed()` sin argumento ni `time.time()`.
2. El archivo se escribe con un helper que pinea lo que `ZipFile.write` filtraría
   (mtime de cada miembro, atributos, nivel de compresión y orden), porque
   `ZipFile.write` toma el timestamp del archivo fuente.

Lo medido: dos checkouts independientes con las mismas fuentes producen el mismo
`suma.zip` (`sha256 76c6d1a3d6aa05e8d178405071a7abd19f705f38ffa9f93c6b45596e1a0fff1a`
en ambos), y `regenerate --check` en un clon limpio reporta `OK` contra los
checksums commiteados.  **Eso es lo que se afirma y no más**: reproducibilidad
per-input medida en este entorno, no una promesa de identidad byte a byte entre
máquinas arbitrarias bajo cualquier toolchain.

## 11. Requisitos

- [`uv`](https://docs.astral.sh/uv/) y Python 3.13+.
- `git`, para los submódulos.
- Un compilador de C/C++ (`g++`) en el `PATH`, y `python3` para los envíos `.py`.
- [`podman`](https://podman.io/) (rootless) para la imagen del juez y el pool.
- La imagen `localhost/dmoj/judge-tier3:latest` para `verify` y `stress`
  (`./problemsetting judges build`, ~15 GB, una sola vez).
