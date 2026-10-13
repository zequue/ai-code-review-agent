## ❌ Cambios requeridos

Revisión de `main...feature/buggy` · 5 archivos · 42 s

### Por qué

- seguridad: bandit reportó un problema de severidad medium o mayor
- reglas del equipo: violación de severidad high o mayor
- revisión LLM: hallazgo high o mayor confirmado

### Bloqueantes (3)

**`shop/app.py:46`** · CRITICAL · autenticación · regla propia `ADMIN-NO-AUTH`

El endpoint de administración `/admin/products` no verifica autenticación: cualquiera puede llamarlo.

> **Sugerencia:** Agregar un decorador o chequeo de credenciales (p. ej. `@require_admin`) antes de ejecutar la operación.

**`shop/db.py:72`** · HIGH · seguridad · bandit `B608` + LLM

Possible SQL injection vector through string-based query construction. (CWE-89)

> **Sugerencia:** Use placeholders (`?`) para los parámetros de búsqueda.

**`shop/checkout.py:27`** · HIGH · dinero · LLM (verificado)

La conversión de `subtotal` a float para calcular el descuento puede causar errores de redondeo o truncación.

> **Sugerencia:** Calcular el descuento directamente en centavos sin convertir a float.

### Métricas

| Etapa | Tiempo | Estado | Hallazgos |
|---|---|---|---|
| ruff | 0.2 s | ok | 0 |
| bandit | 0.6 s | ok | 1 |
| rules | 0.0 s | ok | 1 |
| pytest | 1.3 s | ok | 0 |
| llm | 34.0 s | ok | 2 |
| verifier | 5.5 s | ok | 0 |

- Modelo: `qwen2.5-coder:7b` (local, el código no sale de la máquina)
- Carga del modelo: 2.0 s · revisión: 32.0 s
- Tokens: 5605 de entrada / 421 de salida · costo: 0 (modelo local)
- Secretos borrados antes de enviar al modelo: 0
- Verificador: 1 confirmados, 1 corroborados por herramientas, 0 descartados
