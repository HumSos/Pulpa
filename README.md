La base actual se guarda antes de sobrescribirla.

Después de restaurar, verifica que el esquema coincida con el código antes de
levantar el servidor:

    uv run alembic current   # debe mostrar la última revisión con "(head)"
    uv run alembic check     # debe decir "No new upgrade operations detected"

Si no coinciden, aplica `uv run alembic upgrade head`.

## Al generar migraciones

Ejecuta los comandos de Alembic de uno en uno y lee la salida. Encadenarlos
mezcla los mensajes y es fácil dar por bueno un resultado que no lo es.
Siempre abre el archivo generado y confirma que `upgrade()` contenga las
operaciones esperadas antes de aplicarlo.