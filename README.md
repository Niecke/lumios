# lumios

## Reminders

What happens when the Storage deletes the files automatically. The metadata will still be there. This might not be the perfect solution.

## Landingpage

For local dev
```
cd ./landingpage && python3 -m http.server 5500
```

## Frontend

Development

```
cd frontend

npm install

npm run dev
```

## Backend

### Local development

```
podman-compose up -d --build --force-recreate
```

#### Testing

The tests need a PostgreSQL server (they create and use the `lumios_test` database). Start a throwaway one on tmpfs first:

```
./scripts/test-db.sh start    # or: podman compose --profile test up -d postgres-test
# port 5432 taken? POSTGRES_TEST_PORT=55432 ./scripts/test-db.sh start, then run pytest with POSTGRES_PORT=55432
./scripts/test-db.sh stop     # when done
```

```
cd backend

uv sync --group test
```

Without coverage
```
uv run python -m pytest
```

With coverage
```
uv run python -m pytest --cov=app --cov-report=term-missing --cov-report=html
```

### Database setup

Migrations run automatically on container startup (`flask db upgrade` in
`backend/entrypoint.py`), so a fresh `podman-compose up -d` creates the schema.
To generate a new migration after changing `backend/app/models.py`, follow the
migration commands in [`CLAUDE.md`](CLAUDE.md#commands); never write migration
files by hand.

## Deployment

Merges to `main` deploy to staging and release tags deploy to production through
Flux GitOps on k3s. See [`deploy/README.md`](deploy/README.md) for the full flow.
The remaining GCP infrastructure is described in `terraform/`.

## Development workflow

Development is trunk-based: branch from `main`, open the pull request against
`main`. The `dev` branch is retired. PR titles must be conventional commits, as
they drive the release-please release PR. See [`CLAUDE.md`](CLAUDE.md) for details.
