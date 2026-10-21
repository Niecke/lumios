{{- define "lumios.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "lumios.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "lumios.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{ include "lumios.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "lumios.selectorLabels" -}}
app.kubernetes.io/name: {{ include "lumios.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "lumios.postgresHost" -}}
{{- printf "%s-postgres" (include "lumios.fullname" .) -}}
{{- end -}}

{{- define "lumios.redisHost" -}}
{{- printf "%s-redis" (include "lumios.fullname" .) -}}
{{- end -}}

{{/*
Full image reference for one of the application images. The tag has no default:
an unset tag fails the render instead of silently pulling whatever a floating
tag happens to point at. Call with (list "backend" .Values.backend.image).
*/}}
{{- define "lumios.image" -}}
{{- $name := index . 0 -}}
{{- $image := index . 1 -}}
{{- $tag := required (printf "%s.image.tag is required — set it to a promoted tag such as sha-<short>" $name) $image.tag -}}
{{- printf "%s:%s" $image.repository $tag -}}
{{- end -}}

{{/*
Environment shared by the backend Deployment and the cleanup CronJobs, which run
the same image against the same database. Credentials come from the backend
Secret via envFrom (including REDIS_URL, which embeds the Redis password), so
they are not repeated here.
*/}}
{{- define "lumios.backendEnv" -}}
- name: POSTGRES_HOST
  value: {{ include "lumios.postgresHost" . | quote }}
- name: POSTGRES_PORT
  value: "5432"
- name: POSTGRES_USER
  value: {{ .Values.postgres.username | quote }}
- name: POSTGRES_DB
  value: {{ .Values.postgres.database | quote }}
- name: PUBLIC_BASE_URL
  value: {{ printf "https://%s" .Values.ingress.hosts.backend | quote }}
- name: FRONTEND_URL
  value: {{ printf "https://%s" .Values.ingress.hosts.frontend | quote }}
- name: LANDINGPAGE_URL
  value: {{ printf "https://%s" .Values.ingress.hosts.landingpage | quote }}
- name: S3_ENDPOINT_URL
  value: {{ .Values.s3.endpointUrl | quote }}
- name: S3_PUBLIC_ENDPOINT_URL
  value: {{ default .Values.s3.endpointUrl .Values.s3.publicEndpointUrl | quote }}
- name: S3_BUCKET
  value: {{ .Values.s3.bucket | quote }}
- name: MAIL_SENDER_EMAIL
  value: {{ .Values.backend.mail.senderEmail | quote }}
- name: MAIL_SENDER_NAME
  value: {{ .Values.backend.mail.senderName | quote }}
{{- with .Values.backend.mail.adminEmail }}
- name: ADMIN_EMAIL
  value: {{ . | quote }}
{{- end }}
- name: BREVO_WAITLIST_LIST_ID
  value: {{ .Values.backend.mail.waitlistListId | quote }}
{{- with .Values.backend.google.clientId }}
- name: GOOGLE_CLIENT_ID
  value: {{ . | quote }}
{{- end }}
{{- with .Values.backend.google.frontendClientId }}
- name: GOOGLE_FRONTEND_CLIENT_ID
  value: {{ . | quote }}
{{- end }}
- name: MAX_USERS
  value: {{ .Values.backend.maxUsers | quote }}
- name: CURRENT_AGB_VERSION
  value: {{ .Values.backend.agbVersion | quote }}
- name: JWT_EXPIRY_SECONDS
  value: {{ .Values.backend.jwtExpirySeconds | quote }}
- name: GUNICORN_WORKERS
  value: {{ .Values.backend.gunicornWorkers | quote }}
{{- end -}}
