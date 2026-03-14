# lumios

## Local development

```
podman-compose up -d --build --force-recreate
```

### Testing

```
cd backend
# python3 -m venv .venv

source .venv/bin/activate

pip install -r requirements.txt -r requirements-test.txt
```

Without coverage
```
POSTGRES_PASSWORD=test SECRET_KEY=test-secret-key-at-least-32-chars-long! \
DEBUG=true PASSWORD_HASHER_TIME_COST=1 PASSWORD_HASHER_MEMORY_COST=8 PASSWORD_HASHER_PARALLELISM=1 \
python -m pytest
```

With coverage
```
POSTGRES_PASSWORD=test SECRET_KEY=test-secret-key-at-least-32-chars-long! \
DEBUG=true PASSWORD_HASHER_TIME_COST=1 PASSWORD_HASHER_MEMORY_COST=8 PASSWORD_HASHER_PARALLELISM=1 \
python -m pytest --cov=app --cov-report=term-missing --cov-report=html
```

## Database setup

```
podman-compose up -d 

chmod o+w ~/git/lumios/app/migrations/versions/

podman exec -e FLASK_APP="main:create_app()" lumios-app /usr/bin/python3 -m flask db migrate -m "initial"

chmod o-w ~/git/lumios/app/migrations/versions/
```