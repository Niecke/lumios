# lumios

The entrypoint.sh is deprecated since the pyhton distroless container image does not contain any shell. It was replaced by the entrypoint.py.

## TODO

- [x] add logging with json as the default
- [x] add flask-session for server side sessions
- [x] add CSRF Token to all forms
- [x] add unittests
- [x] add multistage build for docker
- [ ] fix github pipeline
- [x] change layout of login to fit the rest of the app
- [ ] adding versioning
- [ ] adding S3 compatible storage as backend

## Local development

podman build -t lumios-backend .

podman run -it --rm --name lumios-backend -v ./app:/app:z -p 8080:8080 lumios-backend

podman-compose up -d --build

### Testing

```
cd backend
# python3 -m venv .venv

source .venv/bin/activate

pip install -r requirements.txt -r requirements-test.txt
```

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