# Evaluación (qwen2.5-coder:7b, 3 corridas)

## `feature/buggy` — esperado `REQUEST_CHANGES`

- Veredicto correcto: **3/3** corridas
- Tiempo total por corrida: 26–28 s
- Del cual, revisión LLM (sin carga del modelo): 19–21 s
- Falsos positivos bloqueantes: 0 en 3 corridas

| Bug | corrida 1 | corrida 2 | corrida 3 |
|---|---|---|---|
| sql-injection | bloquea | bloquea | bloquea |
| admin-sin-auth | bloquea | bloquea | bloquea |
| dinero-en-float | bloquea | bloquea | bloquea |
| cupon-reutilizable | no detectado | no detectado | no detectado |

Bloquean 9/12, solo comentario 0/12, no detectados 3/12.

## `feature/clean` — esperado `APPROVE`

- Veredicto correcto: **3/3** corridas
- Tiempo total por corrida: 30–32 s
- Del cual, revisión LLM (sin carga del modelo): 19–21 s
- Falsos positivos bloqueantes: 0 en 3 corridas
