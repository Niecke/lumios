# Deploying Lumios

Merges to `main` reach staging, release tags reach production, both through
Flux. Nothing pushes: the cluster pulls, so no GitHub workflow holds cluster
credentials and the k3s API stays unpublished.

```
merge to main
  ├─ promote.yml           retags the tested image digest, commits sha-<short>
  │                        into deploy/flux/staging/helmrelease.yaml
  └─ source-controller     fetches the commit
       ├─ kustomize-ctrl   applies deploy/flux/ — so the committed tag
       │                   actually reaches the HelmRelease objects
       └─ helm-controller  re-renders charts/lumios, upgrades staging

merge the release-please pull request → tag vX.Y.Z
  └─ release.yml           retags sha-<short> as X.Y.Z, X.Y, X, stable,
                           pushes charts/lumios as the OCI chart X.Y.Z,
                           signs both and attests the SBOMs (cosign keyless),
                           commits X.Y.Z into deploy/flux/prod/ — images in
                           helmrelease.yaml, chart in ocirepository.yaml
```

Production and staging share the one k3s node, one HelmRelease each. The private
Talos cluster takes over staging (see "Talos staging (private)"):

| | Namespace | Hosts (`.niecke-it.de`) | Chart from | Image tag written by |
|---|---|---|---|---|
| `deploy/flux/staging/` | `lumios-staging` | `lumios-staging`, `lumios-app-staging`, `lumios-api-staging` | `charts/lumios` on `main` | `promote.yml`, every merge |
| `deploy/flux/prod/` | `lumios` | `lumios`, `lumios-app`, `lumios-api` | `oci://ghcr.io/niecke/lumios/charts/lumios`, pinned to the release | `release.yml`, every `vX.Y.Z` tag |
| `deploy/flux/staging-talos/` | `lumios-staging` on the Talos cluster | same as `staging/` | `charts/lumios` on `main` | the same as `staging/`, via `promote.yml` |

`deploy/flux/base/` holds the shared GitRepository and the Flux Kustomization.
The entry point stays `deploy/flux/kustomization.yaml`, the path that
Kustomization reads.

The kustomize step is not optional. A HelmRelease is a cluster object; editing
its manifest in git changes nothing until something applies it. Without that
controller the images get tagged, the sha lands in git, and the cluster silently
keeps running the previous release.

## What the chart deploys

| Workload | Kind | Notes |
|---|---|---|
| `backend` | Deployment + Service `:8080` | Runs `entrypoint.py` with `RUN_MIGRATIONS=false`: waits for the database, starts Gunicorn, never migrates. 2 replicas in production, 1 in staging. |
| `migrate` | Helm hook Job (`post-install,pre-upgrade`) | The backend image, `entrypoint.py migrate`: runs `flask db upgrade` once per release, waiting up to 2.5 minutes for PostgreSQL first. A failed upgrade is not retried; the Job has `backoffLimit: 0` and a 300 s deadline, and the HelmReleases set `timeout: 10m`. Has its own hook Secret. A failed Job fails the release, and `remediateLastFailure` rolls it back. |
| `worker-default`, `worker-video` | one Deployment each | The backend image, `entrypoint.py worker --queue <name> --concurrency <n>`: background jobs from the Procrastinate queue in PostgreSQL. `default` (4 jobs at once, small) runs short jobs and the stalled-job recovery; `video` (one job at a time, 512Mi limit, `lumios-video` priority class in production) runs the ffmpeg thumbnail extraction. Liveness is `entrypoint.py worker-health` (database and queue schema reachable). Values: `workers.<name>` in `charts/lumios/values.yaml`. |
| `worker-photo` | Deployment, **off** (`workers.photo.enabled: false`) | Prepared for image thumbnails and previews; switched on by the follow-up that moves them. |
| `frontend` | Deployment + Service `:8080` | nginx; proxies `/api/` to the backend Service inside the cluster. |
| `landingpage` | Deployment + Service `:8080` | nginx; `APP_URL` and `BACKEND_URL` are substituted at start. |
| `postgres` | StatefulSet + Service `:5432` | One replica, PVC on `local-path`. |
| `redis` | Deployment + Service `:6379` | Sessions and rate limits. No persistence. |
| `purge-deleted-accounts`, `purge-audit-logs` | one CronJob each | The backend image, daily at 02:00 UTC. Replaces the Cloud Run cleanup job. |
| `backup-database`, `backup-photos` | one CronJob each, **off in staging** | The `backup` image (`backup/`): a daily `pg_dump` and a mirror of the object storage, both shipped to GCS and reported to healthchecks.io. See "Backup and disaster recovery". |
| Ingress | one per host, plus Traefik Middlewares | cert-manager issues one certificate per host. |

Staging redeploys on two kinds of commit on `main`:

- a chart change under `charts/lumios/` — picked up because the staging
  HelmRelease sets `reconcileStrategy: Revision`
- a new image — `promote.yml` writes `sha-<short>` into the staging HelmRelease

Production redeploys only on `release.yml`'s `Deploy X.Y.Z to production`
commit, which moves the chart and the images together.

## One-time cluster setup

The node itself (Hetzner CAX21, the `lumios-data` volume mounted at
`/mnt/lumios`, k3s started with `--default-local-storage-path
/mnt/lumios/local-path`) comes from the infrastructure repository. k3s brings
Traefik and the `local-path` StorageClass.

cert-manager is installed once by hand, with a ClusterIssuer named `letsencrypt`
(what `ingress.tls.clusterIssuer` defaults to):

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/<version>/cert-manager.yaml
kubectl apply -f - <<'YAML'
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: <operator address>
    privateKeySecretRef:
      name: letsencrypt-account-key
    solvers:
      - http01:
          ingress:
            ingressClassName: traefik
YAML
```

Flux, with only the three controllers this needs. The image automation
controllers are deliberately absent: `promote.yml` already decides which digest
is deployable.

```bash
flux install --components=source-controller,helm-controller,kustomize-controller
kubectl create namespace lumios
```

DNS: records for the three production hosts (and the three staging hosts)
pointing at the node. Cloudflare may proxy them; Let's Encrypt's http-01
challenge still reaches the node through the proxy.

### The credentials Secret

The one thing that is never in git. It carries the same YAML a local
`values-secrets.yaml` would, and Flux merges it underneath the HelmRelease's
inline values.

```bash
cat > /tmp/values.yaml <<EOF
postgres:
  password: $(openssl rand -base64 24)
redis:
  password: $(openssl rand -hex 24)
s3:
  endpointUrl: https://<object storage endpoint>
  accessKey: ...
  secretKey: ...
backend:
  secretKey: $(openssl rand -hex 32)
  jwtSecret: $(openssl rand -hex 32)
  google:
    clientId: ...
    frontendClientId: ...
    clientSecret: ...
  mail:
    brevoApiKey: ...
    adminEmail: ...
# Off-site backups (see "Backup and disaster recovery"); two keys, two checks
backup:
  database:
    gcs:
      accessKey: ...
      secretKey: ...
    healthcheckUrl: https://hc-ping.com/<uuid>
  photos:
    gcs:
      accessKey: ...
      secretKey: ...
    healthcheckUrl: https://hc-ping.com/<uuid>
# Optional, error tracking (see "Error tracking with Sentry")
sentry:
  backendDsn: https://<key>@<org>.ingest.de.sentry.io/<backend-project>
  frontendDsn: https://<key>@<org>.ingest.de.sentry.io/<frontend-project>
EOF

kubectl -n lumios create secret generic lumios-values \
  --from-file=values.yaml=/tmp/values.yaml

shred -u /tmp/values.yaml
```

Put every value in a password manager before deleting the file.
`postgres.password` cannot be rotated by re-running this: Postgres sets it when
it first initialises the volume, and changing it afterwards leaves the backend
with a password the database rejects. Change it with `ALTER USER` first, then
update the Secret.
`redis.password` is Redis's `requirepass` and is sent to the backend in
`REDIS_URL`. Rotating it is an edit of the Secret plus a Flux reconcile, which
restarts Redis and logs everybody out. Generate it with `openssl rand -hex`.

Then point Flux at the repo:

```bash
# -k, not -f: kustomization.yaml is a kustomize build file, not a cluster
# resource, and `apply -f` would try to POST it to the API.
kubectl apply -k deploy/flux/
flux -n lumios get kustomization lumios-flux
flux -n lumios get helmrelease lumios
```

That `kubectl apply` is a bootstrap, run once. From then on the Kustomization
manages everything in `deploy/flux/` — including itself and the GitRepository —
so later changes go through git. Hand-patching the GitRepository's branch stops
sticking; to work off a branch, suspend first:

```bash
flux -n lumios suspend kustomization lumios-flux
kubectl -n lumios patch gitrepository lumios --type=merge \
  -p '{"spec":{"ref":{"branch":"some-branch"}}}'
# ... and when done
flux -n lumios resume kustomization lumios-flux
```

Until the first release exists, `deploy/flux/prod/` points at chart and image
tag `0.1.0`, which have no package behind them: the production HelmRelease
reports not-ready and nothing runs. That is expected. The first `vX.Y.Z` tag
fills both in. Staging likewise starts on the placeholder tag `sha-0000000`
until the first promotion after this lands.

## Staging setup

Flux creates the `lumios-staging` namespace and the `lumios-staging`
PriorityClass itself. Three things it cannot create, by hand, before or right
after the first merge — the HelmRelease reports not-ready until they exist:

1. **Object storage.** A bucket `lumios-staging`, with a key that cannot reach
   the production bucket.
2. **The credentials Secret**, same shape as production's, all values new:

   ```bash
   kubectl -n lumios-staging create secret generic lumios-values \
     --from-file=values.yaml=/tmp/values.yaml
   ```

3. **Basic auth** for the landing page and the frontend. htpasswd lines under
   the key `users`:

   ```bash
   # htpasswd is in httpd-tools (Fedora) / apache2-utils (Debian)
   PW="$(openssl rand -base64 18)"; echo "staging password: $PW"
   kubectl -n lumios-staging create secret generic lumios-staging-basic-auth \
     --from-literal=users="$(htpasswd -nbB staging "$PW" | head -1)" \
     --dry-run=client -o yaml | kubectl apply -f -
   unset PW
   ```

   The Secret holds only the bcrypt hash, so put the printed password in the
   password manager. Until it exists, Traefik cannot load the middleware and
   drops those routes. The API is deliberately not behind it — neither the API
   host nor `/api/` on the frontend host, which the SPA calls: the API
   authenticates with its own JWT in the same `Authorization` header, which
   basic auth would reject, and the landing page calls it cross-origin.

Staging has its cleanup CronJobs switched off, runs at a negative priority so
the kubelet evicts it before production, and is sized small. It runs the same
images as production; the frontend's Google client id, landing-page links and
app URL are set per environment at runtime (`/config.js`, written from the
container's environment).

## Talos staging (private)

The private Talos cluster takes over the **existing** staging; there is no
second staging. It uses the same hosts (`lumios-staging`, `lumios-app-staging`,
`lumios-api-staging` `.niecke-it.de`) and the same bucket `lumios-staging`. The
database starts empty and the old Postgres volume is discarded.

`deploy/flux/staging-talos/` holds the entry point: the `lumios` namespace for
the Flux source, a GitRepository, the Kustomization `lumios-staging-talos`, and
`../staging` as a resource. `helmrelease-patch.yaml` overrides only what Talos
needs: `ingress.tls.clusterIssuer: letsencrypt-dns01`,
`postgres.storage.storageClass: hcloud-volumes`, `postgres.storage.size: 10Gi`
and an empty `ingress.basicAuth.secretName`. Everything else, the image tags
included, comes from `staging/helmrelease.yaml`, so `promote.yml` reaches both
clusters. It does not use `../base`, whose `sync.yaml` would apply `prod/`.

> **Never** run `kubectl apply -k deploy/flux/` on the Talos cluster: that
> deploys production.

Bootstrap, once, with the Talos kubeconfig:

```bash
kubectl apply -k deploy/flux/staging-talos/
```

After that Flux keeps it in sync with `main`. `deploy/flux/kustomization.yaml`
does not list `staging-talos`, so the k3s cluster never applies it (CI checks).

**Cutover order:**

1. The Talos staging is deployed (bootstrap above, Secrets below).
2. The DNS records are repointed to the private Talos load balancer, in
   Niecke/infrastructure.
3. A follow-up PR drops `staging` from `deploy/flux/kustomization.yaml`. Its
   prune uninstalls the k3s staging.

Until step 2 the k3s staging serves the hosts. Both clusters run their own
database, so DNS alone decides which one gets traffic.

**Hosts.** They come only from `ingress.hosts`. `PUBLIC_BASE_URL`,
`FRONTEND_URL` and `LANDINGPAGE_URL` are derived from them in
`charts/lumios/templates/_helpers.tpl`, and the frontend's `/config.js` URLs in
`charts/lumios/templates/frontend.yaml`. Because hosts and bucket are unchanged,
the bucket CORS rule (see "CORS on the bucket") and the Google OAuth origins and
redirect URIs need no change.

**Secrets by hand**, in `lumios-staging` (Niecke/infrastructure runbook §10):
`lumios-values`, with the existing staging bucket credentials, same command as
"Staging setup" step 2. `lumios-staging-basic-auth` is **not** needed on Talos.

**Keep it private.** The staging is reachable only through the VPN, so Basic
Auth is off. With a public DNS target the landing page and the frontend would
be open: keep the records on the private load balancer.

## Releasing

release-please keeps a `chore(main): release X.Y.Z` pull request open against
`main`. Merging it is the production decision: `promote.yml` retags the images,
release-please tags `vX.Y.Z`, and `release.yml` retags `sha-<short>` as `X.Y.Z`,
packages `charts/lumios` and pushes it to `oci://ghcr.io/niecke/lumios/charts`,
signs everything, and commits `Deploy X.Y.Z to production` into
`deploy/flux/prod/`.

**Before the release that first ships the backup:** add the `backup.*` keys
(`backup.database.gcs`, `backup.photos.gcs`, the healthcheck URLs) and
`s3.endpointUrl` to `lumios-values` and roll the Secret out first, see "Backup
and disaster recovery". The chart requires them while `backup.enabled` is true,
so without them the production HelmRelease fails and the app release with it.
`deploy/flux/prod/helmrelease.yaml` has no `backup.image.tag` until then;
`release.yml` adds it with the other tags.

### Rolling back

```bash
# flips production's images and chart back to the previous release
git revert <Deploy X.Y.Z to production commit>   # through a pull request
```

Or edit the three image tags in `deploy/flux/prod/helmrelease.yaml` and the
chart tag in `deploy/flux/prod/ocirepository.yaml` directly — keep all four on
the same release — then:

```bash
flux -n lumios reconcile helmrelease lumios --with-source
```

To freeze the cluster where it stands: `flux -n lumios suspend helmrelease lumios`.

> [!WARNING]
> Migrations run in the `migrate` hook Job before an upgrade touches the backend,
> and do not roll back with the image.
> Every Alembic migration has to work with release N−1: add and backfill in one
> release, stop writing the old column in the next, drop it in a third.

## Operating it

```bash
flux -n lumios get helmrelease lumios                         # what is deployed, and whether it reconciled
flux -n lumios reconcile helmrelease lumios --with-source     # don't wait for the interval
flux -n lumios events --for HelmRelease/lumios                # why an upgrade failed
helm -n lumios history lumios                                 # rollback targets
kubectl -n lumios logs deploy/lumios-backend                  # JSON lines
kubectl -n lumios logs job/lumios-migrate                     # the last release's migration run
kubectl -n lumios logs deploy/lumios-worker-video             # a pipeline's worker (worker-default, worker-photo)
kubectl -n lumios exec deploy/lumios-worker-default -- /usr/bin/python3 -m procrastinate --app=worker.worker_app shell   # list/retry/cancel jobs
```

Jobs live in PostgreSQL (`procrastinate_jobs`), so a restarted backend or worker
loses none. A job that fails is retried with backoff; after its last attempt it
stays in status `failed` (the dead letter) and, for a video, the video is marked
`failed`. A job whose worker died is retried by the recovery task of the
`default` worker within about 5 minutes. To run a failed job again, retry it from
the shell above (`retry <job id>`). Postgres is the queue: a Postgres restart
pauses the workers, nothing is lost.

To confirm that the pods really run the new build, open `/admin/system` as an
admin: it shows the version, commit and build time of the backend, frontend and
landing page, warns when their commits differ (a half-done rollout), and checks
PostgreSQL, Redis and the bucket. Without a login, `GET /version` on the backend
returns the same `commit`, `version` and `built_at` as JSON (the frontend and
landing page serve `/version.json`).

```bash
curl -s https://<backend-host>/version
```

A failed upgrade is retried three times and then rolled back
(`remediateLastFailure`), so a bad merge leaves the previous release running
rather than a half-applied one.

If an upgrade times out mid-flight, Helm can be left claiming an operation is
still running. `helm -n lumios list -a` shows `pending-upgrade` when that has
happened; `helm -n lumios rollback lumios` clears it, then reconcile.

`flux resume` and `flux reconcile` block while watching. Ctrl-C only stops the
watching — pass `--wait=false` to skip it.

### Rotating a secret

Edit the values in the Secret and reconcile; the backend's credentials checksum
rolls its pods.

```bash
kubectl -n lumios get secret lumios-values \
  -o jsonpath='{.data.values\.yaml}' | base64 -d > /tmp/values.yaml
$EDITOR /tmp/values.yaml
kubectl -n lumios create secret generic lumios-values \
  --from-file=values.yaml=/tmp/values.yaml --dry-run=client -o yaml \
  | kubectl apply -f -
shred -u /tmp/values.yaml
flux -n lumios reconcile helmrelease lumios
```

Rotating `backend.jwtSecret` signs every photographer out; `backend.secretKey`
invalidates sessions and CSRF tokens.

### Video uploads

Two plain chart values control them, set in the HelmRelease `values` of each
environment (`deploy/flux/<env>/helmrelease.yaml`), not in the `lumios-values`
Secret, because neither is a secret:

| Value | Default | Becomes |
|---|---|---|
| `backend.videoUploadsEnabled` | `false` | `VIDEO_UPLOADS_ENABLED` |
| `backend.maxVideoFileSize` | `209715200` (200 MB, in bytes) | `MAX_VIDEO_FILE_SIZE` |

The backend and all worker Deployments get both through `lumios.backendEnv`.
With the flag off every video route answers 501 and the frontend hides the
video UI. Staging and production both set it to `true` (production from chart 0.5.0).

Unlike the Secret keys, which only roll the pods through the credentials
checksum, a plain env value sits in the Deployment's pod template: changing it
rolls the backend and the worker pods on the next reconcile.

#### CORS on the bucket

The browser PUTs the video straight to a presigned URL on
`S3_PUBLIC_ENDPOINT_URL`, so the bucket needs a CORS rule that allows `PUT` and
the `Content-Type` header from the frontend origin. Without it the browser's
preflight fails and no upload starts. It is a bucket setting at the storage
provider: nothing in the cluster, this repository or Terraform configures it.

Check the current Hetzner Object Storage documentation for CORS support before
relying on this. The S3 API route works with any S3 tool; the Hetzner Console
has no CORS settings, so apply it with the bucket's access key:

```bash
cat > cors.json <<'EOF2'
{
  "CORSRules": [{
    "AllowedOrigins": ["https://lumios-app.niecke-it.de"],
    "AllowedMethods": ["PUT"],
    "AllowedHeaders": ["Content-Type"],
    "MaxAgeSeconds": 3600
  }]
}
EOF2
# Staging bucket lumios-staging: use https://lumios-app-staging.niecke-it.de
aws s3api put-bucket-cors --bucket lumios \
  --endpoint-url https://<region>.your-objectstorage.com \
  --cors-configuration file://cors.json
```

A change can take up to 15 minutes to reach the whole storage cluster. Test the
preflight (expect `200`/`204` with `access-control-allow-origin` in the answer):

```bash
curl -si -X OPTIONS "https://<region>.your-objectstorage.com/lumios/cors-test" \
  -H "Origin: https://lumios-app.niecke-it.de" \
  -H "Access-Control-Request-Method: PUT" \
  -H "Access-Control-Request-Headers: content-type" | head -20
```

#### Switching it on in production

Done: production has video uploads on from release 0.5.0. The steps were:

1. Merge the video bug fixes of #533 (done).
2. Release a chart that contains these values, release-please PR (done, 0.5.0).
3. Apply the CORS rule to the `lumios` bucket and check it with the preflight
   (done).
4. In staging (CORS on `lumios-staging` first), upload a real video, including a
   large one, and wait for status `ready` (done).
5. `backend.videoUploadsEnabled: true` is set in
   `deploy/flux/prod/helmrelease.yaml` (#575). After the reconcile the pods
   roll; confirm `video_uploads_enabled: true` in the public library response.

To switch it off again, set the value back to `false` through a PR (all video
routes answer 501, the frontend hides the video UI) or revert the merge commit.

### Error tracking with Sentry

Unhandled backend exceptions, failed Brevo calls, failed cleanup CronJobs and
frontend crashes are reported to Sentry. It is off while the DSNs are empty
(local dev, CI), and the app then makes no network calls for it.

**Setup.** Create an organisation in the EU region (`de.sentry.io`) and two
projects, a Flask one and a React one. Put their DSNs in the `lumios-values`
Secret of each namespace (`sentry.backendDsn`, `sentry.frontendDsn`, see
above) and reconcile. `sentry.environment` defaults to the namespace, so events
arrive as `lumios` or `lumios-staging`; the release is `lumios-backend@<tag>`
and `lumios-frontend@<tag>`. The frontend DSN is public by design (it ships in
`/config.js`); the backend DSN lives in the backend Secret. Traces are off
(`sentry.tracesSampleRate: 0.0`), so only errors count against the free quota.
The frontend CSP allows `*.ingest.sentry.io` and `*.ingest.de.sentry.io`.

**Alert.** In Sentry, Alerts → Create Alert → Issues, condition "A new issue is
created", action "Send a notification" by email. Do it per project.

**Verify on staging.** Backend, a one-off event from inside the running pod
(the scrubber is not applied here, the event carries no request data):

```bash
kubectl -n lumios-staging exec deploy/lumios-backend -- /usr/bin/python3 -c \
  'import os, sentry_sdk; sentry_sdk.init(dsn=os.environ["SENTRY_DSN"], environment=os.environ["SENTRY_ENVIRONMENT"], release=os.environ["SENTRY_RELEASE"]); sentry_sdk.capture_exception(RuntimeError("Sentry test")); sentry_sdk.flush(timeout=5)'
```

Frontend: open the staging app and run `sendSentryTestEvent()` in the browser
console. The hook only exists when `SENTRY_ENVIRONMENT` is set and is not the
production namespace `lumios`, so it is never exposed in production.
`/admin/system` shows whether the backend DSN is configured.

**What is sent, and why this is acceptable.** Sentry SaaS in the EU region
was chosen over self-hosting GlitchTip: nothing to run, back up or patch on the
single node, and the SDK is the same, so moving to GlitchTip later is a DSN
change. Privacy measures (all in code, applied before an event leaves the
process):

- `send_default_pii` is off: no user, cookie or IP collection by the SDK.
- `Authorization`, `Cookie`, `X-Forwarded-For` and `X-Real-IP` headers and the
  cookies are redacted; request bodies are dropped entirely, so no passwords
  and no image or video content.
- JWTs, email addresses and UUIDs (share links) in URLs, query strings,
  messages, exception texts and breadcrumbs are replaced with
  `[REDACTED_JWT]`, `[REDACTED_EMAIL]` and `[REDACTED_UUID]`.
- A failed mail is reported with the Brevo status code only, never the
  recipient.
- Logged errors are not forwarded automatically (they stay breadcrumbs); only
  explicit reports and unhandled exceptions are events.

Remaining personal data is limited to stack traces and request paths. Before
go-live, conclude the Sentry data processing agreement (EU data residency) and
list Sentry as a processor in the privacy policy, as for Brevo and Cloudflare.

### Running a maintenance command now

```bash
kubectl -n lumios create job purge-now --from=cronjob/lumios-purge-audit-logs
kubectl -n lumios logs job/purge-now
kubectl -n lumios delete job purge-now
```

### Backup and disaster recovery

All state is in two places: the Postgres volume under `/mnt/lumios/local-path`
on the Hetzner `lumios-data` volume, and the object-storage bucket with the
photos and videos. Everything else is in git, or in the `lumios-values` Secret,
which is in the password manager. Both are backed up off-site, to buckets at
Google Cloud Storage, by two CronJobs of the `backup` image (`backup/`). Neither
runs in staging (`backup.enabled: false`): its data is disposable.

| CronJob | Schedule | What it writes |
|---|---|---|
| `lumios-backup-database` | daily 03:00 Europe/Berlin | `lumios-postgres-<TS>.tar` (UTC timestamp) with one file, `dump.sql.br`: `pg_dump` as plain SQL, brotli-compressed |
| `lumios-backup-photos` | daily 04:00 Europe/Berlin | a mirror of the object-storage bucket (`rclone`, streamed from bucket to bucket, no local scratch disk) |

Each has its own Secret and its own HMAC key, so one leaked key does not reach
both buckets. The buckets, service accounts and keys are defined in the
`Niecke/infrastructure` repository (issue 107 there), not here.

Add the keys to `lumios-values`, then roll it out as in "Rotating a secret":

```yaml
backup:
  database:
    gcs:
      accessKey: ...    # HMAC key of the database backup service account
      secretKey: ...
    healthcheckUrl: https://hc-ping.com/<uuid>
  photos:
    gcs:
      accessKey: ...    # a different key
      secretKey: ...
    healthcheckUrl: https://hc-ping.com/<uuid>
```

The photo job reads the live bucket with `s3.accessKey` / `s3.secretKey`, the
backend's own key. A read-only key for that bucket is enough and would be the
better choice.

#### Alerting

Each job pings its own check at healthchecks.io: `/start` when it begins, the
plain URL on success, `/fail` when it breaks. Create two checks with a period of
one day and a grace time of a few hours. The alarm is the *missing* ping, so a
job that never starts, a down node or a deleted CronJob is caught as well. The
ping URLs are secrets (anyone holding one can turn the check green) and live
only in `lumios-values`. Without `healthcheckUrl` the jobs run, log a warning
and raise no alarm.

#### Retention

| What | Kept | Enforced by |
|---|---|---|
| Database archives | 14 days | lifecycle rule on the bucket |
| Photos and videos | the current state, plus what was deleted or overwritten for up to 30 days | depends on `backup.photos.mode`, below |

The database key may add and read archives but not delete or overwrite them
(`objectCreator` + `objectViewer`; archive names carry a timestamp and never
collide). A leaked key cannot destroy existing archives. What it cannot do is
protect against a bad archive: if the database was already damaged, the dump is
too, which is what the 14 days are for.

`backup.photos.mode` decides how deletes in the object storage reach the backup:

| Mode | Behaviour | What the key needs |
|---|---|---|
| `backup-dir` (default) | `rclone sync` into `current/`; objects it would delete or overwrite are moved to `deleted/<date>/`. A lifecycle rule on `deleted/` (30 days) empties it. | Create, read **and delete** on the bucket: the move is a copy plus a delete. A leaked key can therefore remove `current/` and `deleted/`. |
| `mirror` | `rclone sync` into `current/`, nothing kept aside. For a bucket that versions its objects and expires the old versions itself. | Create, read and delete; deleting a version needs the same right. |
| `copy` | `rclone copy`: adds and updates, never deletes. | Create and read only, so a leaked key cannot destroy anything. Deleted photos then stay in the backup indefinitely. |

Both sync modes stop with an error when one run would delete more than
`backup.photos.maxDelete` objects (default 500, `0` turns it off). A wrong or
unlistable source bucket looks empty to rclone and would otherwise move the whole
of `current/` aside and still report success; now the job fails and pings `/fail`.
Raise the value for a run that legitimately removes more, such as a large
account purge.

Which mode fits depends on what the bucket offers; the permission model is
decided in the infrastructure repository. Set the mode in `backup.photos.mode`.

**Deleted photos stay in the backup.** A photo that is deleted, or purged with
its account by `purge-deleted-accounts`, remains in `deleted/<date>/` for up to
the retention period (30 days in `backup-dir` mode) and in database archives for
14 days; in `copy` mode it is never removed. The privacy policy (issue 517)
has to say so.

#### Running a backup now

```bash
kubectl -n lumios create job backup-db-now --from=cronjob/lumios-backup-database
kubectl -n lumios logs -f job/backup-db-now
kubectl -n lumios delete job backup-db-now
```

`lumios-backup-photos` works the same way. A run that finishes shows the
archive name and size (`rclone lsl`) at the end of the log.

#### Restoring the database

The restore was tried against a throwaway PostgreSQL 18: dump, archive upload,
download, `brotli -d`, restore into a database that still held stale data, then
a check of the `alembic_version` and row counts. Repeat it from time to time.

1. Fetch the archive. Any machine with `rclone` and the *read* side of the
   database key works; pick the newest (or the wanted) `lumios-postgres-<TS>.tar`:

   ```bash
   export RCLONE_CONFIG_GCS_TYPE=s3 RCLONE_CONFIG_GCS_PROVIDER=GCS \
     RCLONE_CONFIG_GCS_ENDPOINT=https://storage.googleapis.com \
     RCLONE_CONFIG_GCS_ACCESS_KEY_ID=... RCLONE_CONFIG_GCS_SECRET_ACCESS_KEY=...
   rclone lsl gcs:niecke-it-lumios-backups
   rclone copy gcs:niecke-it-lumios-backups/lumios-postgres-<TS>.tar .
   tar -xf lumios-postgres-<TS>.tar        # -> dump.sql.br
   brotli -d dump.sql.br                   # -> dump.sql
   ```

2. Get a running, empty or stale Postgres 18: on a rebuilt cluster wait for
   `lumios-postgres-0` to be ready (see "Rebuilding after losing the node"); on
   the existing one, stop the writers first so nothing is written during the
   restore:

   ```bash
   kubectl -n lumios scale deploy/lumios-backend deploy/lumios-worker-default \
     deploy/lumios-worker-video --replicas=0
   ```

3. Drop the old schema and restore in one transaction. The dump has no owner and
   no grants, so it restores as the user running `psql`; `ON_ERROR_STOP` with
   `--single-transaction` leaves the database untouched if anything fails:

   ```bash
   kubectl -n lumios exec -i lumios-postgres-0 -- \
     psql -U lumios -d lumios -v ON_ERROR_STOP=1 \
     -c 'DROP SCHEMA public CASCADE' -c 'CREATE SCHEMA public'
   kubectl -n lumios exec -i lumios-postgres-0 -- \
     psql -U lumios -d lumios --single-transaction -v ON_ERROR_STOP=1 < dump.sql
   ```

4. Check it: the migration revision matches the release you are running and the
   tables have rows.

   ```bash
   kubectl -n lumios exec lumios-postgres-0 -- psql -U lumios -d lumios \
     -c 'SELECT version_num FROM alembic_version' \
     -c 'SELECT count(*) FROM users' -c 'SELECT count(*) FROM libraries'
   ```

5. Scale the backend and workers back up (Flux does it on its next reconcile, or
   `kubectl -n lumios scale ... --replicas=<n>`).

An archive from before a migration restores an older schema than the running
release expects; the next release's migrate Job upgrades it, or run
`entrypoint.py migrate` by hand.

#### Restoring photos

The mirror is in `current/` of the photo backup bucket (`backup.photos.gcs.bucket`,
`niecke-it-lumios-photo-backups` by default) in every mode. Copy it back with
the *read* side of the photo key; in `backup-dir` mode a file overwritten or
deleted by mistake is in `deleted/<date>/`:

```bash
export RCLONE_CONFIG_GCS_TYPE=s3 RCLONE_CONFIG_GCS_PROVIDER=GCS \
  RCLONE_CONFIG_GCS_ENDPOINT=https://storage.googleapis.com \
  RCLONE_CONFIG_GCS_ACCESS_KEY_ID=... RCLONE_CONFIG_GCS_SECRET_ACCESS_KEY=...
export RCLONE_CONFIG_LIVE_TYPE=s3 RCLONE_CONFIG_LIVE_PROVIDER=Other \
  RCLONE_CONFIG_LIVE_ENDPOINT=https://<object storage endpoint> \
  RCLONE_CONFIG_LIVE_ACCESS_KEY_ID=... RCLONE_CONFIG_LIVE_SECRET_ACCESS_KEY=...
rclone copy gcs:niecke-it-lumios-photo-backups/current live:lumios
```

#### Rebuilding after losing the node

1. Recreate the node from the infrastructure repository; cloud-init mounts the
   volume at `/mnt/lumios` and starts k3s with the same
   `--default-local-storage-path`.
2. Install cert-manager and Flux and create the `lumios` namespace, as in "One-time
   cluster setup".
3. Recreate `lumios-values` from the password manager.
4. `kubectl apply -k deploy/flux/`. The new cluster has no record of the old
   PVC, so k3s provisions a fresh directory for `lumios-postgres-0`. To reuse
   the data still on the volume, pre-create a PersistentVolume pointing at the
   old directory before this step; otherwise restore the database as above.
5. If the object-storage bucket is gone too, restore the photos.

## Repository settings this depends on

`promote.yml` and `release.yml` push their `Deploy …` commits to `main` over SSH
with the `DEPLOY_KEY` secret — a write deploy key on this repository, which the
branch ruleset allows. Without it the job fails at the push step, images are
tagged but the deployed sha never moves.

The chart package `lumios/charts/lumios` on GHCR must be **public**: the
production `OCIRepository` pulls it anonymously, like the kubelet pulls the
images. GHCR creates a package private on its first push, and there is no API to
change that — after the first release, set it under the package's settings,
*Change visibility*. Until then the `OCIRepository` reports an authentication
error and production stays on the release it already runs. The three image
packages need the same.

The tag that starts `release.yml` must come from `RELEASE_PLEASE_TOKEN`, not
`GITHUB_TOKEN` — GitHub starts no workflows for a tag pushed with the latter.

`DEPLOY_KEY` and `RELEASE_PLEASE_TOKEN` are secrets of the GitHub Environment
`release`, not repository secrets. The `release-please`, `promote` and `release`
jobs set `environment: release`, and the environment only admits runs from
`main` and `v*` tags, so a workflow run from any other branch is rejected
before it can read them. A repository admin sets it up once:

```bash
# Environment limited to the branch/tag policies below
gh api -X PUT repos/Niecke/lumios/environments/release \
  -F 'deployment_branch_policy[protected_branches]=false' \
  -F 'deployment_branch_policy[custom_branch_policies]=true'
gh api -X POST repos/Niecke/lumios/environments/release/deployment-branch-policies \
  -f name=main -f type=branch
gh api -X POST repos/Niecke/lumios/environments/release/deployment-branch-policies \
  -f name='v*' -f type=tag

# Move the secrets: set them in the environment first, then drop the
# repository-level copies (until then the jobs fall back to those)
gh secret set DEPLOY_KEY --env release --repo Niecke/lumios < deploy_key
gh secret set RELEASE_PLEASE_TOKEN --env release --repo Niecke/lumios
gh secret delete DEPLOY_KEY --repo Niecke/lumios
gh secret delete RELEASE_PLEASE_TOKEN --repo Niecke/lumios
```

Pushes to the legacy `release/**` branches that `promote.yml` and
`release-please.yml` still list as triggers are rejected by the environment.

## Local install, without Flux

For a k3d cluster, or to test the chart before merging:

```bash
helm upgrade --install lumios ./charts/lumios \
  -n lumios --create-namespace \
  -f values-secrets.yaml \
  --set ingress.hosts.landingpage=lumios.localtest.me \
  --set ingress.hosts.frontend=app.lumios.localtest.me \
  --set ingress.hosts.backend=api.lumios.localtest.me \
  --set ingress.tls.enabled=false \
  --set backend.image.tag=sha-<short> \
  --set frontend.image.tag=sha-<short> \
  --set landingpage.image.tag=sha-<short>
```

The chart has no default image tag, so leaving these out fails the render.
`values-secrets.yaml` holds credentials: keep it out of git.
