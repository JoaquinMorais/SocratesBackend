# Comandos Docker

## Ejecutar

la primera vez
`docker compose up --build -d`

`docker compose up`      
- `-d` levanta todo en segundo plano
- `restart: unless-stopped` que se inicien cada vez que se prende la pc    

## Reconstruir
Cuándo sí hay que reconstruir
| Codigo | Acción |
|---|---|
| `.py` | Nada, se recarga solo |
| `requirements.txt` o `Dockerfile` | ```docker compose up --build -d``` |
| ```docker-compose.yml``` o `.env` | `docker compose up -d` (recrea los servicios afectados) |
| Cambiar columnas de una tabla existente | `create_all` no las modifica: en desarrollo usa `docker compose down -v` (borra la BD) o, mejor, Alembic más adelante |


## Apagar
`docker compose down`

- `-v` Borra el volumen (BD vacia)

## Probar Tests
`docker compose exec backend pytest -q`

detenerse al primer fallo 
`docker compose exec backend pytest -x`

probar solo algunos test
`docker compose exec backend pytest tests/test_auth.py -k refresh`

### Dos sesiones en paralelo
Cada corrida usa su propia BD de test. Para que dos sesiones (por ejemplo, una de
historias y otra de bugs) no se pisen, cada una fija su sufijo con `TEST_DB_SUFFIX`
(nombre estable que se recicla en cada corrida):

```bash
# sesión de historias
docker compose run --rm --no-deps -T -e TEST_DB_SUFFIX=historias backend python -m pytest -q
# sesión de bugs
docker compose run --rm --no-deps -T -e TEST_DB_SUFFIX=bugs backend python -m pytest -q
```

Sin `TEST_DB_SUFFIX` el sufijo es aleatorio: también aísla, pero deja BD nuevas si
una corrida se interrumpe de golpe. Para ver y limpiar BD de test huérfanas:

```bash
# listar
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d postgres -Atc "SELECT datname FROM pg_database"' | grep -F _test_
# borrar una
docker compose exec db sh -c 'dropdb -U "$POSTGRES_USER" --force --if-exists socrates_db_test_historias'
# o directamente todas: docker compose down -v (borra el volumen entero)
```

## Extras
ver logs en vivo
`docker compose logs -f backend`   
estado de los servicios
`docker compose ps`