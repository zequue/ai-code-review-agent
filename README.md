# AI Code Review Agent

Prototipo de un sistema de agentes que **revisa cambios de código** de un e-commerce y **decide si
pueden avanzar**. Combina herramientas determinísticas (linter, tests, escaneo de seguridad, reglas
propias) con dos agentes LLM que corren **localmente**: un revisor que propone hallazgos y un
verificador que los filtra. Al final, una política de reglas explícita da el veredicto.

```
diff ──► ruff · bandit · reglas AST · pytest ──► agente revisor (LLM) ──► agente verificador (LLM) ──► gate ──► reporte
         determinístico, ~2 s                      un pedido por archivo     segunda opinión por hallazgo   reglas    Markdown / consola
```

Capacidades del reto que demuestra:

1. **Revisar cambios de código** y dar feedback accionable por archivo y línea, con sugerencia.
2. **Decidir si un cambio está listo para avanzar**: `APPROVE` o `REQUEST_CHANGES`, con la regla que
   lo disparó. El código de salida (0/1) permite usarlo en CI.

Las decisiones de diseño, las alternativas descartadas y los experimentos están en
[docs/DECISIONES.md](docs/DECISIONES.md).

## Requisitos

| | Versión | Para qué |
|---|---|---|
| Python | 3.11 o superior | todo el proyecto |
| git | 2.30 o superior | diffs y worktrees temporales |
| [Ollama](https://ollama.com/download) | reciente | correr el modelo localmente |
| Disco | ~5 GB libres | el modelo `qwen2.5-coder:7b` |
| GPU | recomendada (8 GB de VRAM o más) | sin GPU funciona, pero la revisión es varias veces más lenta |

No hace falta ninguna API key ni cuenta paga.

## Instalación

### 1. Clonar el repositorio con sus ramas de prueba

```bash
git clone https://github.com/zequue/ai-code-review-agent.git
cd ai-code-review-agent
git fetch origin feature/clean:feature/clean feature/buggy:feature/buggy
```

El repo tiene tres ramas: `main` (la tienda base), `feature/clean` (una funcionalidad bien hecha) y
`feature/buggy` (la misma funcionalidad con bugs plantados). El revisor compara cada rama contra
`main`.

### 2. Crear el entorno de Python

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 3. Descargar el modelo

Con Ollama instalado y corriendo:

```bash
ollama pull qwen2.5-coder:7b
```

### 4. Verificar la instalación

```bash
python -m pytest -q                              # tests de la tienda y del revisor
python review.py --head feature/buggy --no-llm   # revisión sin LLM: tarda ~2 s
```

## Uso

```bash
# 1. Cargar el modelo en memoria (la primera carga puede tardar minutos según el disco)
python review.py --warmup

# 2. Revisar la rama con bugs: debe pedir cambios (código de salida 1)
python review.py --head feature/buggy --markdown runs/buggy.md --out runs/buggy.json

# 3. Revisar la rama limpia: debe aprobar (código de salida 0)
python review.py --head feature/clean --markdown runs/clean.md --out runs/clean.json
```

Salida de ejemplo (`feature/buggy`):

```
VEREDICTO: REQUEST_CHANGES   (main...feature/buggy, 27 s)
  - seguridad: bandit reportó un problema de severidad medium o mayor
  - reglas del equipo: violación de severidad high o mayor
  - revisión LLM: hallazgo high o mayor confirmado

BLOQUEANTES (3)
  CRITICAL shop/app.py:46         [regla propia `ADMIN-NO-AUTH`]
           El endpoint de administración `/admin/products` no verifica autenticación: cualquiera puede llamarlo.
  HIGH     shop/db.py:72          [bandit `B608` + LLM]
           Possible SQL injection vector through string-based query construction. (CWE-89)
           -> Use placeholders (`?`) para los parámetros de búsqueda.
  HIGH     shop/checkout.py:27    [LLM (verificado)]
           La conversión de `subtotal` a float para calcular el descuento puede causar errores de redondeo o truncación.
           -> Calcular el descuento directamente en centavos sin convertir a float.
```

Los reportes completos de ejemplo están en [runs/buggy.md](runs/buggy.md) y
[runs/clean.md](runs/clean.md).

### Sin Ollama: repetir una revisión guardada

Toda revisión guardada con `--out` se puede volver a mostrar sin ejecutar nada. Sirve como salida
de respaldo y para ver el sistema sin instalar el modelo:

```bash
python review.py --replay runs/buggy.json
```

### Opciones

| Opción | Descripción |
|---|---|
| `--head RAMA` | Revisa `RAMA` contra `--base` (por defecto `main`). |
| `--patch ARCHIVO` | Revisa un archivo `.patch` aplicado sobre `--base`. |
| `--base REF` | Rama o commit de referencia. Default: `main`. |
| `--repo RUTA` | Repositorio a revisar. Default: el directorio actual. |
| `--no-llm` | Solo la etapa determinística. |
| `--markdown ARCHIVO` | Guarda el reporte en Markdown. |
| `--out ARCHIVO` | Guarda la revisión completa en JSON (para `--replay`). |
| `--replay ARCHIVO` | Muestra una revisión guardada, sin re-ejecutarla. |
| `--warmup` | Carga el modelo en memoria y sale. |

Código de salida: `0` aprobado, `1` cambios requeridos, `2` error (ref inexistente, archivo no
encontrado, etc.).

El revisor nunca toca tu directorio de trabajo: analiza cada cambio en un `git worktree`
temporal que se borra al terminar.

## Configuración

Todo se configura en `.env` (ver [.env.example](.env.example)):

| Variable | Default | Descripción |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` (local) u `openai` (cualquier API compatible con OpenAI). |
| `LLM_BASE_URL` | `http://localhost:11434` | Host de Ollama, o URL base del proveedor. |
| `LLM_MODEL` | `qwen2.5-coder:7b` | Modelo a usar. |
| `LLM_API_KEY` | — | Solo para `LLM_PROVIDER=openai`. |
| `LLM_TIMEOUT_S` | `180` | Timeout por pedido al modelo. |
| `LLM_NUM_CTX` | `8192` | Tamaño de contexto (Ollama). |
| `LLM_KEEP_ALIVE` | `30m` | Cuánto tiempo Ollama mantiene el modelo cargado. |
| `LLM_MAX_TOKENS` | `1024` | Tope de tokens de salida por pedido. |
| `LLM_GUIDELINES` | `reviewer/guidelines.md` | Guía de revisión del equipo; `none` la desactiva. |

**Usar un modelo en la nube.** Con `LLM_PROVIDER=openai`, `LLM_BASE_URL`, `LLM_MODEL` y
`LLM_API_KEY` el sistema funciona con cualquier proveedor compatible con OpenAI, sin cambios de
código. Tené en cuenta que en ese caso el código revisado **sale de la máquina** (los secretos se
borran antes de enviarlo, pero el resto del código no).

**Adaptarlo a otro proyecto.** Las reglas de dominio que el revisor exige (dinero en centavos,
rutas de admin con auth, cupones de un solo uso, etc.) están en
[reviewer/guidelines.md](reviewer/guidelines.md), en texto plano. Editarlas cambia el
comportamiento del revisor sin tocar código.

## Evaluación

```bash
python eval/run_eval.py --no-llm     # línea base: solo herramientas determinísticas
python eval/run_eval.py --runs 3     # sistema completo, 3 corridas por rama
```

Compara los hallazgos contra los bugs esperados de [eval/expected.json](eval/expected.json) y
escribe el resultado en `eval/results.md` (y `eval/results-no-llm.md`).

Resultados con `qwen2.5-coder:7b` local (RX 6700 XT), 3 corridas por rama:

| | Solo determinístico | Sistema completo |
|---|---|---|
| Veredicto correcto | 2/2 | **6/6** |
| SQL injection | bloquea | bloquea (3/3) |
| Endpoint de admin sin auth | bloquea | bloquea (3/3) |
| Dinero en `float` | no detectado | **bloquea (3/3)** |
| Cupón reutilizable | no detectado | no detectado (0/3) |
| Falsos positivos que bloquean | 0 | 0 |
| Tiempo por revisión (modelo ya cargado) | ~2 s | 26–32 s |

El cupón reutilizable es una regla de negocio que el modelo de 7B no detecta de forma confiable:
el revisor a veces lo propone, pero el verificador no logra separarlo de los falsos positivos.
Es la principal limitación del modelo local; el análisis está en
[docs/DECISIONES.md](docs/DECISIONES.md).

## Estructura

```
├── review.py            CLI
├── reviewer/            el sistema
│   ├── diff.py          parseo del diff
│   ├── workspace.py     git diff + worktree temporal
│   ├── static.py        ruff, bandit, pytest
│   ├── rules.py         reglas AST propias
│   ├── llm.py           agente revisor
│   ├── guidelines.md    guía de revisión del equipo
│   ├── verify.py        agente verificador
│   ├── redact.py        borrado de secretos
│   ├── gate.py          política de veredicto
│   └── report.py        reporte Markdown / consola
├── shop/                mini e-commerce de prueba (Flask + SQLite)
├── tests/               tests del revisor
├── eval/                evaluación contra bugs esperados
├── runs/                revisiones grabadas (respaldo para --replay)
└── docs/DECISIONES.md   documento de decisiones
```

## Problemas conocidos

- **Primera revisión lenta.** Ollama tarda en cargar el modelo la primera vez (de segundos a varios
  minutos, según el disco). El reporte muestra ese tiempo aparte. `python review.py --warmup` lo
  carga por adelantado y `LLM_KEEP_ALIVE` lo mantiene cargado entre revisiones.
- **Reproducibilidad.** Con temperatura 0 y semilla fija, las corridas en una misma máquina dan el
  mismo resultado. Con otro hardware, otra versión de Ollama u otro modelo, los hallazgos del LLM
  pueden cambiar; por eso existe `eval/run_eval.py`.
- **Solo Python.** El revisor LLM y las reglas propias analizan archivos `.py`; otros archivos del
  diff se listan pero no se revisan.

## La tienda de prueba

`shop/` es un mini e-commerce (productos, búsqueda, carrito, checkout con cupones, alta de
productos para admin) generado con IA y sin pulir a propósito: es el sujeto de prueba, no el
producto. Para levantarlo:

```bash
python -m shop.app       # http://localhost:5000/products
```
