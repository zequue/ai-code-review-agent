# Evaluación (solo determinístico)

## `feature/buggy` — esperado `REQUEST_CHANGES`

- Veredicto correcto: **1/1** corridas
- Tiempo total por corrida: 2–2 s
- Falsos positivos bloqueantes: 0 en 1 corridas

| Bug | corrida 1 |
|---|---|
| sql-injection | bloquea |
| admin-sin-auth | bloquea |
| dinero-en-float | no detectado |
| cupon-reutilizable | no detectado |

Bloquean 2/4, solo comentario 0/4, no detectados 2/4.

## `feature/clean` — esperado `APPROVE`

- Veredicto correcto: **1/1** corridas
- Tiempo total por corrida: 2–2 s
- Falsos positivos bloqueantes: 0 en 1 corridas
