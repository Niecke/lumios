# Repository rulesets

GitHub rulesets kept as code. `apply.sh` creates or updates them (by name); it needs a `gh`
login with admin rights on the repo.

| File | Protects | Why |
|---|---|---|
| `release-tags.json` | tags `v*` | `release.yml` signs and publishes whatever a `v*` tag points at. Only repository admins (or release-please running with an admin's `RELEASE_PLEASE_TOKEN`) may create, move or delete them. |
| `release-branches.json` | branches `release/**` | `promote.yml` runs on pushes to these. Same restriction. |

Release-please must run with `RELEASE_PLEASE_TOKEN` (a token of an admin). With the default
`GITHUB_TOKEN` it cannot create the tag and the release fails.

Check the result: `gh api repos/Niecke/lumios/rulesets --jq '.[] | {id, name, enforcement}'`.
The `main` and `dev` rulesets are not managed here.
