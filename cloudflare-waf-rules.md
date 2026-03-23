# Cloudflare WAF Rules for Lumios

Create these under **Security → WAF → Custom rules** for the `niecke-it.de` zone.

---

## Rule 1: Backend path allowlist

Only allow known routes to reach the backend. Block everything else.

**Name:** `Backend path allowlist`

**Expression:**
```
(http.host eq "lumios-api.niecke-it.de" and
not starts_with(http.request.uri.path, "/api/") and
not starts_with(http.request.uri.path, "/auth/") and
not starts_with(http.request.uri.path, "/admin/") and
not starts_with(http.request.uri.path, "/static/") and
not http.request.uri.path eq "/health" and
not http.request.uri.path eq "/login" and
not http.request.uri.path eq "/logout" and
not http.request.uri.path eq "/change_password" and
not http.request.uri.path eq "/")
```

**Action:** Block

---

## Rule 2: Frontend path allowlist

The frontend is a React SPA served by Nginx. All valid paths are either
static assets, the API proxy, or client-side routes (served via index.html fallback).

**Name:** `Frontend path allowlist`

**Expression:**
```
(http.host eq "lumios-app.niecke-it.de" and
not starts_with(http.request.uri.path, "/api/") and
not starts_with(http.request.uri.path, "/assets/") and
not http.request.uri.path eq "/" and
not http.request.uri.path eq "/login" and
not http.request.uri.path eq "/account" and
not starts_with(http.request.uri.path, "/library/") and
not http.request.uri.path eq "/favicon.ico" and
not starts_with(http.request.uri.path, "/favicon") and
not http.request.uri.path eq "/site.webmanifest")
```

**Action:** Block

---

## Rule 3: Landingpage path allowlist

Static site with only a few pages.

**Name:** `Landingpage path allowlist`

**Expression:**
```
(http.host eq "lumios.niecke-it.de" and
not http.request.uri.path eq "/" and
not http.request.uri.path eq "/impressum.html" and
not http.request.uri.path eq "/style.css" and
not http.request.uri.path eq "/favicon.ico" and
not http.request.uri.path eq "/favicon-16x16.png" and
not http.request.uri.path eq "/favicon-32x32.png")
```

**Action:** Block

---

## Rule 4: Block known scanner user agents (all hosts)

**Name:** `Block scanner user agents`

**Expression:**
```
(http.user_agent contains "sqlmap" or
http.user_agent contains "nikto" or
http.user_agent contains "nmap" or
http.user_agent contains "masscan" or
http.user_agent contains "zgrab" or
http.user_agent contains "nuclei" or
http.user_agent contains "dirbuster" or
http.user_agent contains "gobuster" or
http.user_agent contains "wpscan" or
http.user_agent contains "acunetix" or
http.user_agent eq "")
```

**Action:** Block

---

## Notes

- Rules are evaluated in order. Place the allowlist rules (1-3) before the
  user agent rule (4) so that blocked paths are rejected early.
- Monitor **Security → Events** after enabling to check for false positives.
- The empty user agent block (`http.user_agent eq ""`) may catch some
  health check probes. If Cloud Run or GCP health checks use an empty UA,
  switch that condition to **Managed Challenge** instead of Block.
