# Documento de decisiones — AI Code Review Agent

Ezequiel Aguirre · Reto técnico Full Stack Engineer · IA Agéntica

## 1. Qué parte del ciclo ataqué y por qué

De las fricciones del escenario elegí **la revisión de código**: es la que el enunciado describe
como lenta e inconsistente, ocurre en cada cambio y es donde un bug detectado temprano es más
barato. Las dos capacidades que demuestro forman un solo flujo:

1. **Revisar cambios** y dar feedback accionable: archivo, línea, severidad, por qué importa y
   qué hacer.
2. **Decidir si el cambio puede avanzar**: `APPROVE` o `REQUEST_CHANGES`, con la regla que lo
   disparó y un código de salida que permite usarlo como paso de CI.

Descarté las otras dos para hacer dos bien. *Responder preguntas sobre el código* (RAG) es otro
sistema con otros problemas: indexado, retrieval, frescura. *Proponer y validar correcciones* es
la extensión natural de este sistema y la dejé como primer paso a futuro (sección 6).

**Código base.** Generé un mini e-commerce propio (Flask + SQLite: catálogo, búsqueda, carrito,
checkout con cupones y alta de productos para admin) en lugar de usar un repo público. Así controlo
la verdad: sé exactamente qué bugs hay y puedo medir. Armé **dos ramas que implementan la misma
funcionalidad**: `feature/clean`, bien hecha, y `feature/buggy`, con cuatro bugs plantados de
naturaleza distinta (SQL injection, endpoint de admin sin autenticación, dinero calculado en
`float` y un cupón reutilizable). Con la misma funcionalidad en ambas, la comparación es justa: el
sistema tiene que aprobar una y frenar la otra. Los tests de la rama con bugs pasan (solo cubren
el camino feliz), como pasaría en un PR real.

## 2. Diseño del sistema

```
diff ─► determinístico ─────────► agente revisor ──► agente verificador ──► gate ──► reporte
        ruff · bandit ·           (LLM, por archivo)  (LLM, por hallazgo)   reglas   Markdown,
        reglas AST · pytest                                                          consola, JSON
```

Tres principios guiaron el diseño:

- **Lo determinístico primero.** Linter, tests y escaneo de seguridad son gratis, rápidos (~2 s)
  y certeros. El LLM se reserva para lo que esas herramientas no ven.
- **El LLM aconseja, las reglas deciden.** El veredicto lo da una función de ~40 líneas, testeada,
  que siempre da el mismo resultado ante el mismo input y deja escrito por qué.
- **No confiar en la salida del modelo.** La salida se fuerza a un esquema JSON y después se
  valida: un comentario que apunta a una línea fuera del diff se descarta, y un hallazgo solo
  puede bloquear si un segundo agente lo confirma.

**Componentes:**

- **Aislamiento.** Cada revisión corre en un `git worktree` temporal: el revisor nunca toca el
  directorio de trabajo de quien lo ejecuta.
- **Etapa determinística.** Corre ruff, bandit, pytest y una regla AST propia. Solo se le cobran
  al cambio los hallazgos en líneas que el diff agrega; la deuda preexistente se cuenta pero no
  bloquea. pytest es global: si el cambio rompe un test en otro archivo, igual es del cambio.
- **Agente revisor.** Hace un pedido por archivo. El prompt lleva:
  - una guía de revisión del equipo, en un archivo de texto editable;
  - el esquema de la base de datos;
  - lo que las herramientas ya reportaron, para que no lo repita;
  - el archivo numerado, con las líneas cambiadas marcadas.

  El modelo escribe primero un análisis breve y después los hallazgos.
- **Agente verificador.** Toma cada hallazgo de severidad media o mayor y lo revisa contra el
  código con un prompt escéptico. Si bandit o la regla AST ya reportaron lo mismo, el hallazgo se
  da por corroborado sin gastar una llamada.
- **Gate.** Bloquean: un test que falla, bandit con severidad media o mayor, una regla propia
  `high` o mayor, o un hallazgo del LLM `high` o mayor *verificado*. Si una herramienta
  determinística no pudo correr, se bloquea (fail-closed). Si el LLM no está disponible, decide la
  parte determinística y el reporte avisa "revisión parcial" (fail-open: el LLM es un asesor y que
  se caiga no debe frenar al equipo).
- **Reporte.** Cuando bandit y el LLM ven lo mismo, se fusionan en un solo hallazgo, con la
  sugerencia del LLM. Los descartados por el verificador quedan visibles con el motivo. Incluye
  tiempos, tokens y costo, y toda revisión se guarda en JSON y se puede repetir con `--replay`.
- **Pull requests.** Con `--post-pr N`, la revisión se publica como review de GitHub, con un
  comentario en cada línea. Solo sale el resultado, no el código. GitHub no permite aprobar ni
  rechazar un PR propio, así que con mi token se publica como comentario; con el token de un bot,
  el veredicto se aplica.

### Qué va con LLM y qué sin LLM (decidido con evidencia)

| Bug plantado | Lo detecta | Por qué ahí |
|---|---|---|
| SQL injection | bandit (B608) + LLM, corroborado | Patrón sintáctico conocido: la herramienta es certera y gratis. |
| Admin sin autenticación | **Regla AST propia** | El plan original era el LLM, pero no lo detectó en ninguna variante de prompt. Es un patrón estructural: 20 líneas sobre el AST lo ven siempre. |
| Dinero en `float` | **LLM**, verificado | Requiere entender que esos números son dinero; ninguna herramienta estática lo marca. |
| Cupón reutilizable | Ninguno (de forma confiable) | Regla de negocio pura: necesita entender la intención. Es el límite del modelo local (sección 4). |

La línea base sin LLM acierta el veredicto, pero detecta 2 de 4 bugs; el LLM agrega el de dinero.
No es un resultado espectacular, pero es medido, y muestra dónde rinde cada herramienta.

## 3. Decisiones y alternativas descartadas

| Decisión | Alternativa descartada | Por qué |
|---|---|---|
| Pipeline plano en Python | LangGraph u otro orquestador | Son etapas secuenciales sin ciclos ni estado compartido complejo. Un framework sumaba dependencias y superficie sin aportar nada que una función no haga. |
| Modelo local (Ollama, `qwen2.5-coder:7b`) | API en la nube | Privacidad por defecto y costo cero. La nube queda a un cambio de `.env` (`LLM_PROVIDER=openai`). |
| API nativa de Ollama | Su API compatible con OpenAI | La compatible no permite fijar el tamaño de contexto: si el prompt no entra, Ollama **recorta el principio sin avisar**. Tampoco permite mantener el modelo cargado. |
| Un pedido por archivo | Todo el diff en un pedido | Prompts chicos y enfocados para un modelo de 7B; un archivo que falla no arrastra al resto. |
| Esquema de la base como contexto | Las líneas de los otros archivos del PR | Lo probé: con más contexto el modelo de 7B **mezclaba problemas entre archivos**. El esquema es chico y dirigido. |
| Verificador como segundo agente | Usar la `confidence` del modelo | Medido: el modelo declaraba 1.0 tanto en aciertos como en errores. No sirve como señal. |
| Gate por reglas | Que el LLM decida | Un veredicto tiene que ser auditable y reproducible. |
| Guía del equipo en un `.md` | Reglas dentro del prompt en código | El conocimiento de dominio es configuración: otro equipo la adapta sin tocar código. |
| Esquema JSON con topes de largo | Texto libre o JSON sin límites | Sin topes, el modelo entraba en loops de repetición hasta el timeout. |

### Cómo llegué al diseño del LLM

No lo diseñé de una vez: lo iteré midiendo contra las dos ramas.

1. **Prompt base.** Detectaba el float y la SQL injection con severidad baja, y no veía el admin
   ni el cupón.
2. **Más contexto** (guía del equipo y los otros archivos del PR). Aparecieron loops de
   repetición y el modelo mezclaba problemas entre archivos.
3. **Topes en el esquema** (largo de los textos y cantidad de hallazgos). Se terminaron los loops.
4. **Esquema de la base en lugar de los otros archivos.** Salida limpia, con severidades y
   categorías correctas.
5. **"Análisis antes de los hallazgos".** Apareció el cupón, pero también 7 falsos positivos en la
   rama limpia.
6. **Verificador.** Probé tres variantes de prompt sobre 9 casos conocidos. La escéptica rechazó
   los 6 falsos positivos, pero también el cupón. Ninguna variante separó el cupón de los falsos
   positivos. Elegí la escéptica: en un gate, un falso positivo que bloquea erosiona la confianza
   del equipo más rápido que un bug que se escapa a revisión humana.

## 4. Condiciones del reto y cómo las balanceé

| Condición | Qué hice | Resultado medido |
|---|---|---|
| **Costo** | Modelo local. Solo se envía el archivo cambiado, recortado a ±40 líneas si es grande, y el esquema; nunca el repo entero. Las herramientas filtran antes del LLM. | 0 por revisión. ~6 mil tokens de entrada y ~0,5 mil de salida por PR, más ~1 llamada corta de verificación por hallazgo. |
| **Tiempo** | Defino "razonable" como **menos de 2 minutos con el modelo cargado**: muy por debajo de lo que espera un PR por revisión humana y comparable con un CI. Se reporta el tiempo por etapa y la carga del modelo aparte. | 26–32 s por PR. La primera carga del modelo tarda ~3 min en mi máquina; `--warmup` y `keep_alive` la evitan. |
| **Privacidad** | El código no sale de la máquina. Antes de armar cualquier prompt se borran secretos (claves, tokens, contraseñas en asignaciones, credenciales en URLs). | Con un proveedor en la nube, el README advierte que el código sí sale. El borrado de secretos es una red de seguridad, no una garantía. |
| **Operabilidad** | README paso a paso, `.env.example`, un comando por acción, códigos de salida para CI, worktrees aislados y `--replay` para ver el sistema sin instalar el modelo. | 48 tests del sistema; evaluación reproducible con `eval/run_eval.py`. |

**Las tensiones reales:**

- **Privacidad contra calidad.** Es la central. Elegir un modelo local de 7B garantiza que el código
  no salga, pero es la razón por la que el cupón reutilizable no se detecta. La arquitectura deja
  la decisión abierta: un equipo que acepte enviar código a un proveedor cambia `LLM_PROVIDER` y
  mide con `eval/run_eval.py` antes de adoptarlo. Para código de una empresa prioricé la
  privacidad, y documenté lo que cuesta.
- **Calidad contra tiempo y costo.** El verificador duplica llamadas al modelo. Lo acoté: solo
  verifica hallazgos de severidad media o mayor, y lo que una herramienta ya confirmó no se
  verifica. Con un modelo local el costo adicional es tiempo (~5 s por hallazgo), no dinero.
- **Privacidad contra tiempo.** El modelo local paga un arranque en frío que una API no tiene. Lo
  mitigué manteniéndolo cargado y precalentándolo, y lo hice visible en el reporte en lugar de
  esconderlo en el promedio.
- **Precisión contra cobertura.** Configuré el gate para no bloquear por error: en la rama limpia
  hubo 0 falsos positivos bloqueantes en 3 de 3 corridas. El precio es un bug de negocio que se
  escapa. Ese bug igual aparece como comentario cuando el revisor lo propone, y queda para la
  revisión humana.

### Resultados

Evaluación sobre las dos ramas, 3 corridas cada una (`eval/results.md`):

- Veredicto correcto en **6 de 6** corridas.
- SQL injection, admin sin autenticación y dinero en `float` bloquean en **3 de 3**.
- Cupón reutilizable: **0 de 3**.
- **0** falsos positivos bloqueantes.
- Con temperatura 0 y semilla fija, las tres corridas dieron exactamente lo mismo.

Un caso de prueba de dos ramas es poco para conclusiones generales: el valor está en tener el
mecanismo de evaluación para seguir midiendo.

## 5. Qué haría diferente o agregaría con más tiempo

1. **Proponer y validar correcciones (capacidad 2).** Para cada hallazgo verificado: generar un
   parche, aplicarlo en el worktree, correr los tests y sumar un test que reproduzca el bug. Toda
   la infraestructura para eso (worktree aislado, pytest, gate) ya existe.
2. **Medir un modelo más grande** sobre el mismo set de evaluación: uno local más grande, si el
   hardware lo permite, o uno en la nube, para cuantificar cuánto cuesta en calidad la decisión de
   privacidad. Sobre todo para el cupón.
3. **Un set de evaluación más grande**, con PRs reales del equipo y bugs históricos, que sirva como
   regresión de cada cambio de prompt o de modelo.
4. **Integración con el flujo:** un GitHub Action sobre un runner propio con Ollama, que corra la
   revisión en cada PR sin sacar el código de la infraestructura, y una GitHub App como autor del
   review, para que el veredicto bloquee el merge.
5. **Más reglas determinísticas** a partir de lo que el LLM detecta seguido (semgrep o reglas AST).
   Cada patrón estable que pasa del LLM a una regla gana certeza y velocidad y se vuelve gratis.
6. **Ciclo de aprendizaje:** registrar los comentarios que el equipo descarta y usarlos para ajustar
   la guía y medir la precisión real en producción.
7. **Rendimiento:** cache por hash de archivo y revisión de archivos en paralelo cuando el servidor
   del modelo lo permita.

Si lo empezara de nuevo, armaría `eval/` el primer día y no al final: la mitad de las decisiones
del LLM salieron de medir, y las primeras iteraciones las hice con pruebas ad hoc.

## 6. Uso de IA en este trabajo

Trabajé con **Claude Code (Claude Opus 5.5)** a lo largo de todo el reto, además de investigación
propia.

- **Análisis y decisiones.** Usé Claude para analizar el enunciado, contrastar alternativas y
  evaluar las decisiones técnicas, complementado con investigación propia. Las decisiones de
  alcance y de rumbo las tomé yo:
  - qué capacidades atacar;
  - generar un código base propio con bugs plantados;
  - pipeline plano en lugar de un framework;
  - modelo local por privacidad;
  - priorizar el documento por sobre funcionalidades.
- **Código.** El código del sistema, los tests y la tienda de prueba los escribió Claude Code bajo
  mi dirección. La tienda se generó con IA a propósito y sin pulir: es el sujeto de prueba, no el
  producto.
- **Validación.** Validé lo construido con los tests, con la evaluación contra bugs conocidos y
  revisando las salidas del modelo en cada iteración. Las decisiones sobre el diseño del LLM (por
  ejemplo, agregar el verificador o pasar el control de auth a una regla AST) salieron de esos
  experimentos medidos, no de suposiciones.
- **Este documento.** Lo redacté con apoyo de Claude a partir de la bitácora de decisiones y
  experimentos del proyecto.
