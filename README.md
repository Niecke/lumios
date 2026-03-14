# lumios

## Frontend

## Backend

### Local development

```
podman-compose up -d --build --force-recreate
```

#### Testing

```
cd backend
# python3 -m venv .venv

source .venv/bin/activate

pip install -r requirements.txt -r requirements-test.txt
```

Without coverage
```
python -m pytest
```

With coverage
```
python -m pytest --cov=app --cov-report=term-missing --cov-report=html
```

### Database setup

```
podman-compose up -d 

chmod o+w ~/git/lumios/app/migrations/versions/

podman exec -e FLASK_APP="main:create_app()" lumios-app /usr/bin/python3 -m flask db migrate -m "initial"

chmod o-w ~/git/lumios/app/migrations/versions/
```