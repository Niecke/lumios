# lumios

## Reminders

The disk of the VM could be changed, but needs to be done manually otherwise terraform deletes the disk and recreates it without data.

What happens when the Storage deletes the files automatically. The metadata will still be there. This might not be the perfect solution.

Right now all photos go through the backend service this is not efficient. Should be redesigned later.

If the project grows and we want more control over deployments, we can evolve to pin the image SHA in a Terraform variable (e.g. `terraform.tfvars`), have CI auto-commit the new SHA to that file and open a PR, then merge the PR to trigger deployment via Terraform.

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

podman exec -e FLASK_APP="main:create_app()" lumios-backend /usr/bin/python3 -m flask db migrate -m "initial"

chmod o-w ~/git/lumios/app/migrations/versions/
```

## GCP

### Setup

```
# Service Account
gcloud iam service-accounts create terraform \
  --display-name="Terraform"

# Create the pool
gcloud iam workload-identity-pools create "github" \
  --location="global" \
  --display-name="GitHub Actions"

# Create the provider
gcloud iam workload-identity-pools providers create-oidc "github" \
  --location="global" \
  --workload-identity-pool="github" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="attribute.repository=='Niecke/lumios'"

# Bind a service account to the pool
gcloud iam service-accounts add-iam-policy-binding "terraform@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github/attribute.repository/Niecke/lumios"

gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:terraform@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:terraform@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/compute.admin"

gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:terraform@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/storage.admin"

gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:terraform@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/serviceusage.serviceUsageAdmin"

gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:terraform@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.admin"

gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:terraform@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/secretmanager.admin"

gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:terraform@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountAdmin"

gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:terraform@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"

gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:terraform@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/resourcemanager.projectIamAdmin"

# Cloud Run
gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:terraform@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/run.admin"

gcloud services enable iamcredentials.googleapis.com

gcloud services enable cloudresourcemanager.googleapis.com
```
