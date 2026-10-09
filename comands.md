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

## Extras
ver logs en vivo
`docker compose logs -f backend`   
estado de los servicios
`docker compose ps`