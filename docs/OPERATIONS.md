# Operations and Codespaces

## Automated startup

The dev container installs Docker support and executes `.devcontainer/setup.sh`. Docker Compose builds and health-checks PostgreSQL, Redis, API, worker and frontend. Subsequent Codespace starts run `docker compose up -d`.

Once every Compose health check passes, startup prints the correct forwarded URLs and attempts to open the frontend. Print the URLs again at any time with:

```bash
bash .devcontainer/show-url.sh
```

## Health and logs

```bash
docker compose ps
curl http://localhost:8000/api/health
curl http://localhost:3000/healthz
docker compose logs --tail=100 api worker
```

## Rebuild after source changes

```bash
docker compose up --build --detach --wait
```

## Reset demonstration storage

Prefer the application’s deterministic reset button for normal demonstrations. To completely remove local PostgreSQL and Redis volumes:

```bash
docker compose down --volumes
docker compose up --build --detach --wait
```

This removes only Docker volumes declared by this project.
