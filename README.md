# Electoral Platform: Docker Compose starter

Minimal local development stack with PostgreSQL 18 + PostGIS 3.7 and Python 3.12 + FastAPI. Intended only for local development.

## 1. Prerequisites

- Docker Desktop running with the Linux/WSL 2 backend (or Docker Engine with Compose on Linux)
- PowerShell and VS Code (instructions below), or equivalent shell

## 2. Configure secrets

From the project folder in PowerShell:

```powershell
Copy-Item .env.example .env
notepad .env
```

Replace `POSTGRES_PASSWORD` with a strong password. `.env` is ignored by Git.

## 3. Start the stack

```powershell
docker compose config
docker compose up -d --build
docker compose ps
```

Wait for `db` to show `(healthy)` and `api` to show `Up`.

## 4. Verify

Open:

- http://localhost:8000/health
- http://localhost:8000/health/db
- http://localhost:8000/docs

Check PostGIS directly:

```powershell
docker compose exec db psql -U electoral_user -d electoral -c "SELECT PostGIS_Version();"
```

Change database name/user in this command if you changed them in `.env`.

## 5. Work on code

Edit `backend/app/main.py` in VS Code. The `api` development service runs with Uvicorn reload and mounts the source folder.

## 6. Useful commands

```powershell
docker compose logs -f api
docker compose logs -f db
docker compose ps
docker compose down
docker compose up -d --build
```

Do not use `docker compose down -v` unless you mean to delete the local PostgreSQL data volume.

## Notes

- `db` is reachable **from inside Docker** at hostname `db` on port `5432`. It is reachable **on the host** at `localhost` port `${POSTGRES_PORT}` (default `5432`).
- API is published only to `127.0.0.1:8000`.
- DB credentials in `.env` are appropriate for a local example, not production secret management.
- Docker image upgrades and PostgreSQL major upgrades require tested backups/migration procedures. PostgreSQL 18's persistent volume is mounted at `/var/lib/postgresql`.
- Step 3 of the project should add migrations, separate roles, test suites, and more complete environment configuration.
