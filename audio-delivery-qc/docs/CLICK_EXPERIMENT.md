# Experimento local de clicks — plan y registro

Plan aprobado en conversación: comparar baseline `2e74a097455dbb30cd2f2df312e078aeae35a426`
(sensibilidad low), contexto temporal y predicción lineal sobre Print Masters.
No cambiar la aplicación. Objetivo reservado: 50 % menos falsas alarmas y retener
90 % de los clicks reales detectados por baseline. Audio real local, sin publicaciones.
El usuario pidió preparar herramienta y plantilla; etiquetará material real después.

## Registro de implementación

- Base: `2e74a09`, rama existente, árbol inicialmente limpio.
- Tareas: (1) manifiesto/métricas; (2) scoring y lectura acotada; (3) ejecución,
  congelación e informes; (4) validación sintética, revisión y regresión.
- Interfaces compartidas: intervalos half-open absolutos en muestras, canales
  físicos one-based, programme y split explícitos. El matching usa representantes
  originales, no posiciones estimadas por los scorers.
- Ruling: conservar rama actual y registrar aquí decisiones duraderas; no ejecutar
  scripts de Skills que creen worktrees, commits o cambien exclusiones Git. El
  plan aprobado prohíbe esas acciones y no requiere un archivo de plan adicional.
- Ruling: evaluar eventos por canal; mostrar issues originales aparte. No sumar
  ambos como defectos únicos. Las reducciones se calculan sin alterar agrupación.
- Ruling: límite de 60 s por fragmento, 200 fragmentos, 2.000 anotaciones por
  fragmento y 128 MiB de PCM temporal por fragmento. Permite lecturas por bloques
  y evita cargar masters completos o listas ilimitadas en memoria.

## Uso y anotación

Herramienta independiente; no añade opciones a la GUI ni modifica el detector,
la política QC, los dropouts o los presets de producción. No requiere entrenamiento
ni dependencias nuevas. Usar el entorno existente con FFmpeg/ffprobe.

1. Copiar [la plantilla](examples/click_experiment.yaml) a una carpeta local externa
   al repositorio. Ajustar rutas (relativas al YAML), sample rate, canales e intervalos.
2. Escuchar y etiquetar clicks técnicos confirmados como `technical_click`, pasos,
   armas y demás transitorios intencionados como `intentional_transient`; dudas como
   `uncertain`. No basta con etiquetar solamente los candidatos del detector: anotar
   también clicks que este omita. `reviewed: true` declara revisión completa del intervalo.
3. Separar programas completos entre development y validation, nunca fragmentos del
   mismo programa entre ambos. Reservar al menos dos programas independientes. No
   reutilizar la reserva para ajustar umbrales después de consultar sus resultados.
4. Ejecutar, desde `audio-delivery-qc`, con un destino nuevo separado de las fuentes:

```sh
.venv/bin/python scripts/evaluate_clicks.py --manifest /ruta/experimento.yaml --output /ruta/resultados-nuevos
```

Fuentes mono, stereo o seis canales PCM. Para 5.1 seleccionar `[1, 2, 3, 4, 5, 6]`;
los números identifican canales físicos, no una asignación automática de altavoces.
Las muestras son enteras relativas al archivo; extremo final exclusivo. BWF y TC
no se usan para decidir si un candidato coincide con una anotación. Tolerancia de
matching: 1 ms inclusivo, en muestras, mismo archivo/fragmento y canal.

## Comparación reproducible

Baseline fija identificada por SHA y hashes de módulos importados, sensibilidad
`low`. Se conserva su agrupación y el representante original. Se evalúan ventanas
25/50 ms y umbrales 4/8/16/32 para contexto temporal y predicción lineal bidireccional.
La predicción usa orden proporcional al sample rate (24 a 48 kHz, límites 4–64).
Estos parámetros son hipótesis experimentales, no una calibración profesional.
Contexto insuficiente, silencio no ajustable o predicción inestable conservan el
candidato. Un confirmador no recupera clicks omitidos por la baseline.

Selección exclusivamente en development, priorizando menos falsas alarmas con
retención emparejada de al menos 90 % de los clicks detectados por baseline. Desempate:
contexto temporal, ventana menor, umbral menor. `frozen_selection.json` se escribe
antes de analizar validation y se comprueba su hash al terminar. También se compara
la mejor variante de cada método, sin seleccionar de nuevo con la reserva.

`VIABLE` exige en reserva real: ≥20 clicks detectados por baseline, ≥20 falsas
alarmas, ≥2 programas, reducción ≥50 % y retención ≥90 %. Datos sintéticos no cuentan
para esta puerta. Candidatos sin etiqueta, truncamiento, análisis incompleto,
evidencia fallida o fuentes alteradas impiden aceptar. Las dudas se contabilizan
por separado y se excluyen de las métricas confirmadas. No prueban ausencia de error.
El matching es uno a uno; detecciones duplicadas de un click cuentan como falsas
alarmas adicionales. No se pueden compensar clicks perdidos con otros distintos.

## Salidas y límites

- `report.html`, `results.json`, `candidates.csv`: resultados globales/por programa,
  candidatos retenidos/descartados y provenance; JSON por fragmento con datos originales.
- Evidencia WAV para todos los candidatos descartados, agrupada por issue original,
  conservando canales, orden y amplitud mediante el exportador existente. Enlaces locales.
- `manifest_snapshot.json`, selección congelada, hashes de código, versiones y huellas
  SHA-256/tamaño/mtime antes/después. `EXPERIMENT_COMPLETE.json` solo tras entregar informes.
  Ante fallo, `EXPERIMENT_ERROR.json` cuando el disco lo permita; nunca significa QC PASS.
- Salida CLI: 0 VIABLE, 1 NOT_VIABLE, 2 error operativo, 3 INSUFFICIENT_EVIDENCE,
  130 cancelación. Un resultado insuficiente es normal con la plantilla o datos sintéticos.

Recuentos por evento de canal físico, separados de los issues originales. Tasas por
hora de fuente y hora de canal, no supuesto número único de defectos de un programa.
Los JSON conservan clicks omitidos por cada método. Tiempo y memoria trazada de
Python/NumPy se registran; **no** incluyen RSS de FFmpeg ni buffers del SO.

Procesamiento por bloques y spool temporal ≤128 MiB por fragmento; ≤60 segundos,
≤200 fragmentos, ≤2000 anotaciones por fragmento, YAML ≤2 MiB. El límite compartido
original de 1000 issues permanece y bloquea aceptación si se alcanza. Los límites
no garantizan duración corta: FFmpeg decodifica desde el principio para recortar
muestras exactas; elegir archivos cortos facilita la evaluación. El contexto se
lee alrededor del fragmento; no equivale a inspeccionar el master completo.

Solo rutas locales; nada se sube. Salidas con audio real deben estar fuera del
repositorio. No incluir fuentes, snippets ni informes reales en Git. Se rechazan
solapamientos y copias idénticas entre programas, pero no se puede reconocer por
hash audio reutilizado tras cambiar metadata/encoding: la independencia del corpus
requiere revisión humana. Un resultado VIABLE tampoco demuestra reconocimiento
semántico de intención artística ni autoriza integrar el método en producción.

## Validación de implementación — 20/10/2026

Revisión independiente de solo lectura: se corrigieron dos riesgos de falsa mejora.
El matching que encuentra clases distintas dentro de tolerancia queda `unclassified`
y bloquea aceptación; una variante no puede reasignarlo de falsa alarma a click.
Las copias byte-idénticas se verifican también por canal e intervalo, incluso dentro
del mismo programa. Ambas correcciones tienen pruebas que fallaron antes del arreglo.
También se corrigió la cobertura de contexto a 8 kHz, alineándola a los bloques
reales del detector; reproducción fallida seguida de prueba satisfactoria.

Prueba CLI ejecutada con tres WAV sintéticos stereo PCM24/BWF de tres segundos,
un programa de desarrollo y dos de reserva. Baseline reservada: 2 clicks etiquetados
y 2 transitorios intencionados detectados; selección congelada temporal/25 ms/16.
Salida real: `INSUFFICIENT_EVIDENCE`, exit 3; fuentes SHA-256/tamaño/mtime intactas.
Tiempo observado 0,418 s; pico trazado 4.662.011 bytes (no RSS total). Se generaron
HTML/JSON/CSV y evidencia de descartados. Estos números validan el recorrido técnico,
no eficacia perceptiva: los transitorios de esta prueba son impulsos sintéticos.

Pruebas focalizadas: `python -m pytest -q tests/test_click_experiment.py`: **27 passed**.
Incluyen seis canales con evidencia sin cambio de orden/amplitud, fallo de escritura,
no finitos, rango inválido, fuga de corpus, separación previa de reserva, posiciones
exactas y límites de matching. No se ha realizado escucha en DAW ni evaluación real.

Regresión completa ejecutada en macOS/ARM64, Python 3.14.8, FFmpeg 9.0.2:
`python -m pytest -q`: **717 passed in 40.78s**, sin fallos ni omisiones.
Plantilla validada (3 fragmentos, todos pendientes de revisión); enlaces HTML locales
comprobados con destino existente y atributos `target="_blank" rel="noopener"`.
Código de producción sin modificaciones. No se ejecutó CI remota ni se publicó.

Registro cerrado: tareas 1–4 implementadas y verificadas con fixtures sintéticos;
evaluación real pendiente. Decisiones de alcance: rama conservada y sin commits;
métricas por canal (no defectos únicos); límites de fragmento explícitos (material
más largo exige dividir intervalos sin solapar). No quedan observaciones menores
diferidas de la revisión independiente.

## Comparación independiente con Essentia — protocolo v2

Ampliación aprobada el 22/10/2026, implementación/validación local el 23/10.
Se conserva el recorrido v1 anterior; `--essentia` activa un experimento distinto
(JSON experimental schema 2), no cambia los informes ni el detector de producción.
No implementa/acepta M7 ni modifica M5/M6, GUI, presets, política QC o dropouts.

### Objetivo y etiquetas

Se comparan baseline `low`, baseline+confirmador temporal, baseline+predicción
bidireccional y Essentia independiente. Los confirmadores solo eliminan candidatos;
Essentia recorre TODOS los samples de cada intervalo/canal y puede detectar omisiones.
La unidad sigue siendo el evento por canal físico; issues de archivo/programa no
se suman a esos recuentos. Se conserva la agrupación canónica de 1 ms.

Usar [la plantilla schema 2](examples/click_detector_comparison.yaml), fuera de Git.
Conserva todos los campos y tipos v1 y requiere por anotación:

- `qc_disposition`: `reject`, `acceptable` o `uncertain`.
- `basis`: `operator` o `documented_rejection`.

`kind` sigue describiendo el sonido: `technical_click`, `intentional_transient`,
`uncertain`. Un click técnico/vocal confirmado puede ser aceptable; un transitorio
intencionado no se etiqueta como click rechazable. Una duda sigue siendo dudosa.
`documented_rejection` indica evidencia profesional de rechazo, no certificación
automática de Netflix. Los documentos privados que la sustentan permanecen locales.

Se mantienen dos evaluaciones: todos los clicks técnicos y el subconjunto motivo
de rechazo. La decisión experimental usa este último; no genera FAIL de producción.
La referencia inicial aprobada es el criterio del operador. Las
[directrices Netflix para doblaje](https://partnerhelp.netflixstudios.com/hc/en-us/articles/11220839130771-Dubbing-Creative-Guidelines-Films-Series-English)
incluyen contexto interpretativo; no equivalen a un umbral numérico universal para
Print Masters. Essentia no reconoce intención artística ni gravedad contractual.

Anotar intervalos completos, también clicks que la baseline omita. Incluir Foley,
pasos, armas, golpes, percusión, consonantes y dudas. `reviewed: true` afirma escucha
completa; etiquetar solo issues previos no permite recall. Candidatos nuevos sin
etiqueta quedan `unclassified`: no se convierten automáticamente en falsas alarmas.
La revisión de dudas/no clasificados requiere escucha; no ajustar parámetros con
la reserva ni convertirla en development después de verla.

### Instalación opcional y reproducible

Entorno comprobado: Apple Silicon, macOS 26.5.2, CPython 3.14.8, NumPy 2.5.3,
PyYAML 6.0.3, Essentia `2.1b6.dev1438`, `six` 1.17.0. El wheel ARM64 exige macOS 15+;
la distribución seleccionada no incluye wheel Python 3.11. La aplicación mantiene
su compatibilidad y sus dependencias originales; Essentia no se añade a pyproject.
No se instala nada al importar el experimento ni al ejecutar tests.

Solo tras autorización, crear un venv independiente y usar el
[lock ARM64](../scripts/click_experiment/requirements-essentia-macos-arm64.txt):

```sh
python3.14 -m venv /ruta/entorno-experimental
/ruta/entorno-experimental/bin/python -m pip install --only-binary=:all: --require-hashes \
  -r scripts/click_experiment/requirements-essentia-macos-arm64.txt \
  --report /ruta/instalacion-essentia.json
PYTHONPATH=src /ruta/entorno-experimental/bin/python scripts/evaluate_clicks.py \
  --essentia --manifest /ruta/corpus.yaml --output /ruta/resultados-nuevos
```

Comandos desde `audio-delivery-qc/`. Rutas con espacios deben ir entre comillas.
No se instala el proyecto en el venv: `PYTHONPATH=src` selecciona este checkout.
El experimento usa workers secuenciales POSIX (macOS/Linux), no `--jobs`; Windows
se rechaza explícitamente. Linux/3.11 no están validados para esta integración.
No intentar compilación, Rosetta o sustituciones del entorno principal si falla
el binario: documentar el bloqueo y aprobar otra vía antes de continuar.

El entorno de esta sesión quedó en `/private/tmp/xqc-essentia-20261022-gDsb3A/venv`;
su registro de instalación hermano `install.json` conserva hashes y versiones.
Es temporal y puede ser eliminado por el sistema. La aplicación `.venv` conserva
NumPy/PyYAML originales y no tiene Essentia instalado.

### Adaptador y precisión

Se reutiliza PCMClip/FFmpeg con atrim entero, sin MonoLoader, downmix, normalización,
remuestreo ni cambios a fuentes/BWF. Una instancia por canal/fragmento. El análisis
de Essentia usa float32: PCM24 normalizado se representa exactamente; PCM32/float64
puede redondearse en memoria, sin modificar la fuente. No se promete identidad
bit a bit de los cálculos entre formatos de mayor precisión.

Frames de 512 muestras, hop 256, LPC orden 12, estimación de potencia 10 y umbral
de silencio −50; solo se exploran `detectionThreshold` 20/30/40 dB en development.
El sample rate es el original, explícito. No son umbrales QC ni calibration Netflix.
Cada frame es dueño de su hop central. Se usa contexto real disponible, padding
solo fuera de la fuente, grilla global en muestras y recorte al intervalo evaluado.

El binding devuelve segundos float32 relativos a su contador de frames, con extremo
final inclusivo. Se convierte al sample local verificando round-trip y resolución
inferior a una muestra, se suma el origen entero y se transforma a `[inicio, fin)`.
Un origen de archivo grande nunca pasa por float32. Las salidas crudas y su origen
se conservan en JSONL; el representante consolidado conserva sus mediciones.
La precisión de coordenadas no prueba que el detector delimite perfectamente el
defecto: LPC puede ensanchar el intervalo alrededor de un impulso.

Ruling: se usa `_essentia.Algorithm('ClickDetector')`, encapsulado y fijado a la
versión verificada. `essentia.standard` construye todos los algoritmos al importar
y tardó ~39 s en una comprobación local; el binding específico funcionó sin esa
inicialización general. Al ser una API de bajo nivel, una nueva versión exige
revalidar el adaptador. Tests reales comprueban salidas, silencio y estado por canal.

Fuentes técnicas consultadas:
[referencia](https://essentia.upf.edu/reference/std_ClickDetector.html),
[tutorial](https://essentia.upf.edu/tutorial_audioproblems_clickdetector.html),
[código C++](https://github.com/MTG/essentia/blob/master/src/algorithms/audioproblems/clickdetector.cpp).
El runtime registra hashes del binding/binario y versiones; no presume que master
sea idéntico al wheel instalado.

### Límites, selección y métricas

Se conservan los máximos de 60 s, 200 fragmentos, 2.000 anotaciones/fragmento y
128 MiB de spool PCM. Essentia entrega frames pequeños; no se carga el master.
El cap de 1.000 issues se aplica después de consolidación intra/cross-channel,
usando la misma construcción que producción. Un segundo límite explícito de
100.000 salidas crudas por variante/fragmento protege el JSONL: alcanzarlo marca
cobertura truncada, aunque exista un solo issue. Nunca equivale a inspección completa.
Cada worker tiene deadline de 300 s; timeout/cancelación terminan su grupo de
procesos. FFmpeg puede decodificar desde el principio para atrim sample-accurate:
el coste de fragmentos tardíos de un master largo puede ser considerable.

La selección usa solo development, preferentemente real. Se congelan parámetros,
grid, baseline, hashes de código, versión de Essentia y hash del manifiesto antes
de analizar validation. No se elige el ganador con los resultados de la reserva.
Si una familia no tiene variante elegible, se ejecuta una configuración diagnóstica
fija (Essentia 30; confirmador 25 ms/4), se declara y no se acepta su eficacia.

Se reportan TP, FP, FN, precision, recall, retención emparejada, nuevas detecciones,
omisiones, duplicados, dudas y no clasificados. El matching uno-a-uno mantiene la
tolerancia inclusiva de 1 ms y el canal físico; clases incompatibles en tolerancia
quedan no clasificadas. Las tasas usan unión de intervalos por fuente y por canal;
no duplican horas al evaluar canales de un mismo archivo en entradas distintas.
Cobertura incompleta/error/no clasificados dejan precision/recall/tasas no evaluables,
conservando los recuentos parciales. Dudas se excluyen y cuentan aparte.

`VIABLE` por método requiere reserva real suficiente (mínimo 20 rechazos detectados
por baseline, 20 falsas alarmas y dos programas), cero pérdidas emparejadas de
rechazos baseline, cero rechazos anotados omitidos y ≥50 % menos falsas alarmas.
El mínimo es una puerta experimental, no una garantía estadística profesional.
Errores, truncamiento, cambios de fuentes/código/etiquetas o calibración insuficiente
impiden aceptar. Datos sintéticos nunca certifican eficacia. Este criterio v2 no
reescribe el histórico de retención ≥90 % del experimento v1.

Tiempo/RSS se miden en procesos frescos por método/fragmento. La memoria incluye
C++/NumPy/Python; el pico del hijo FFmpeg/ffprobe se informa aparte, no se suma como
si fuera un máximo simultáneo. Para confirmadores se declara dependencia baseline
y tiempo total secuencial de ambos pasos. Development incluye toda la grid;
validation solo la variante congelada. No confundir esos costes.

HTML/JSON/CSV muestran cada método y programa, posiciones/provenance, límites y
enlaces locales de evidencia, incluidos eventos propios de Essentia. Se reutiliza
el exportador multicanal original; ventanas idénticas baseline/Essentia dentro de
un fragmento comparten evidencia. Se preservan canales, orden y amplitud.
`EXPERIMENT_COMPLETE.json` significa entrega del experimento, nunca PASS acústico.
Fallos de reporte dejan `EXPERIMENT_ERROR.json` si el disco lo permite, sin marcador
de finalización. Fuentes se verifican con SHA-256, tamaño y mtime antes/después.

### Licencia y distribución pendiente

El wheel declara AGPL-3.0-only. UPF ofrece una vía comercial; antes de distribuir
habría que revisar obligaciones del producto y bibliotecas incluidas. La separación
en un subprocess no demuestra por sí sola exención de obligaciones. Una licencia
UPF tampoco cubre automáticamente derechos de todas las dependencias.
[Información oficial de licencias](https://essentia.upf.edu/licensing_information.html).
No se descargan modelos; sus licencias son otro asunto. La instalación experimental
no autoriza distribución ni integración en producción. Solo se consultaron fuentes
públicas y descargaron paquetes; no se transmitió audio o documentación privada.

### Validación v2 — 23/10/2026

Estado de partida/final: rama `codex/m6-programme-measurement`, HEAD
`2bf68add64fed03e82b4d18c013efef75470ae60`. Árbol inicialmente limpio; cambios de
esta ampliación sin commit ni push. No se han cambiado ramas/referencias Git.
Código `src/audio_qc/`, presets, pyproject y workflow CI sin cambios; hashes de
baseline experimental comprobados de nuevo. Resultados anteriores siguen históricos.

Registro de ejecución del plan aprobado:

1. Instalación aislada y prueba real del binding completadas. `pip check` sin
   requisitos rotos; el lock reproduce los hashes descargados. `.venv` de la app
   sigue sin Essentia y conserva NumPy 2.5.3 / PyYAML 6.0.3.
2. Adaptador, etiquetas y métricas: tests inicialmente fallidos por APIs ausentes
   y schema no admitido, seguidos de implementación y resultados satisfactorios.
   Se comprobó separación de temporales/predicción sin ejecutar el segundo dentro
   de la medición del primero. Clock local de 60 s probado a 48/192 kHz y origen
   entero `2**54+7`, sin pérdida de coordenadas.
3. Workers, congelación, informes y fallos: pruebas de timeout/reap, fallo nativo,
   evidencia/disco y permisos de reporte; no generan aceptación ni pierden los
   resultados baseline disponibles. Integridad y cap permanecen visibles.
4. Revisión independiente: detectó la ruta accidental schema 2 → aceptación
   legacy 90 %. Se añadió una prueba que falló, guardia de modo/schema y repetición
   satisfactoria. También se aclararon `elapsed` (ejecución) y `wall` (arranque e
   imports incluidos), con tiempo del pipeline de cada confirmador. El revisor
   no encontró otros defectos importantes; la documentación fue comprobada localmente.

Rulings: v1 se conserva y v2 exige `--essentia`; API de bajo nivel fijada (una
actualización de Essentia exige revalidación); cap de JSONL separado y explícito
(puede impedir evaluar clips extremadamente densos); fallback diagnóstico no
calibrado cuando no existe selección elegible (no puede convertirse en VIABLE).
No quedan observaciones menores diferidas de la revisión.

Comandos de pruebas, desde `audio-delivery-qc/`:

```sh
XQC_ESSENTIA_PYTHON=/private/tmp/xqc-essentia-20261022-gDsb3A/venv/bin/python \
  .venv/bin/python -m pytest -q tests/test_click_experiment.py \
  tests/test_essentia_experiment.py tests/test_essentia_runtime.py --tb=short
# 52 passed in 17.66s

QT_QPA_PLATFORM=offscreen \
XQC_ESSENTIA_PYTHON=/private/tmp/xqc-essentia-20261022-gDsb3A/venv/bin/python \
  .venv/bin/python -m pytest -q --tb=short
# 742 passed in 57.04s; 0 failed, 0 skipped
```

La variable permite a los tests usar el intérprete aislado. Si falta, solo los
nuevos tests del binario opcional se omiten explícitamente; eso no verifica Essentia.
No se desactivó ninguna prueba existente. No se ejecutó CI remota ni Python 3.11/Linux.

Smoke CLI real (audio sintético): tres fuentes PCM24/BWF 48 kHz, stereo/stereo/seis
canales, tres programas, 3 s cada uno, TimeReference 172800000. Incluye impulso,
control etiquetado intencionado y salto permanente de señal que la baseline omite.
Los controles son artificiales y no prueban discriminación de Foley o diálogo.

```sh
PYTHONPATH=src /private/tmp/xqc-essentia-20261022-gDsb3A/venv/bin/python \
  scripts/evaluate_clicks.py --essentia \
  --manifest reports/essentia-20261023-smoke/corpus.yaml \
  --output reports/essentia-20261023-smoke/comparison
# INSUFFICIENT_EVIDENCE; exit 3
```

Rutas locales ignoradas por Git; repetir requiere un destino nuevo. Reserva sintética:

| Método | TP rechazo | FP conocidos | FN rechazo | Sin clasificar |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 2 | 2 | 2 | 0 |
| Temporal | 2 | 2 | 2 | 0 |
| Predicción | 2 | 2 | 2 | 0 |
| Essentia | 4 | 2 | 0 | 2 |

Los dos candidatos adicionales no clasificados de Essentia están en el final de
las fuentes. Precision/recall completos de Essentia quedan null; no se han cambiado
las etiquetas para mejorar el resultado. Todos los métodos alternativos usaron
fallback diagnóstico explícito por falta de selección elegible. No hubo reducción
de falsas alarmas conocidas, corpus real ni evidencia suficiente para aceptación.

Verificados SHA-256/tamaño/mtime intactos en las tres fuentes; cuatro snippets
distintos del caso de seis canales comparados muestra a muestra contra el rango
original: igualdad de amplitud y orden, 48 kHz/seis canales. El contexto efectivo
del exportador es 1 s antes/después. Enlaces HTML locales existentes con escaping,
`target="_blank" rel="noopener"`. Plantilla validada; enlaces documentales y
`git diff --check` correctos. La CLI sin dependencia opcional sale con código 2,
sin instalar ni crear salida. No se ha realizado escucha real ni validación en DAW.

Pendiente: corpus real exhaustivo y separación por programas, juicio de rechazo
del operador, reserva independiente y eventual revisión de licencia antes de una
distribución. Esta tarea prepara la evaluación; no demuestra mejora perceptiva ni
autoriza integración en producción.

### Protección de la fuente al exportar evidencia (25/10/2026)

Ambas versiones del experimento conservan `source_signature` (tamaño, mtime en
nanosegundos e inode) desde antes de leer el PCM. El exportador común comprueba
esa identidad antes/después de cada snippet; no toma una nueva baseline al
exportar. V2 exige además que baseline y Essentia se refieran a la misma identidad.
Si no puede verificarse, devuelve diagnósticos y enlaces nulos, conservando los
resultados medidos. Registros antiguos sin ese campo requieren un nuevo análisis
para generar evidencia; no se actualizan retrospectivamente. Los SHA-256 globales
del experimento siguen siendo independientes y no se relajan. El control stat no
es un bloqueo ni detecta toda modificación con atributos restaurados. No cambia
el detector, la selección de parámetros ni los criterios de aceptación.

### Compatibility with independent signal-loss checking (2026-10-26)

The experimental baseline remains `2e74a097455dbb30cd2f2df312e078aeae35a426`.
The production configuration now adds an independent `signal_loss` section, which
the experiment does not execute. `click_experiment/audio.py` explicitly allows the
reviewed configuration hash and checks a frozen copy of every `defects` default.
The original configuration hash is preserved; detector, consolidation, issue and
model hashes remain unchanged. This is configuration compatibility, not a new click
baseline, parameter tuning or evidence of experimental detector efficacy.
