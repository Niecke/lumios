# Changelog

## [0.3.0](https://github.com/Niecke/lumios/compare/v0.2.0...v0.3.0) (2026-10-25)


### Features

* add failed login protection via Redis cache lockout ([#490](https://github.com/Niecke/lumios/issues/490)) ([670ebec](https://github.com/Niecke/lumios/commit/670ebecdc93b5852d624ba7c56b30edc4e66baa5))
* **admin:** add system page with build info and health checks ([#458](https://github.com/Niecke/lumios/issues/458)) ([696aa51](https://github.com/Niecke/lumios/commit/696aa518a3d872a3deb75c296f2b649735412389))
* **deploy:** run frontend and landingpage nginx without root ([#498](https://github.com/Niecke/lumios/issues/498)) ([99cff64](https://github.com/Niecke/lumios/commit/99cff64031bd5a9bd14e238ed23dbea43ca547f9))
* **deploy:** run migrations in a one-time Job and scale backend to 2 replicas ([#504](https://github.com/Niecke/lumios/issues/504)) ([1f7f42b](https://github.com/Niecke/lumios/commit/1f7f42b4a560d7db34a501afba5c4febee11aa21))
* resend activation mail and activate pending accounts from the admin UI ([#503](https://github.com/Niecke/lumios/issues/503)) ([2c21161](https://github.com/Niecke/lumios/commit/2c21161dd8d86a1e677d9417f28e5ec6cdb20af9))


### Bug Fixes

* **backend:** remove legacy max library and photo user columns ([#204](https://github.com/Niecke/lumios/issues/204)) ([#486](https://github.com/Niecke/lumios/issues/486)) ([0f9c13f](https://github.com/Niecke/lumios/commit/0f9c13fc45b984cdebdd397bfc295e6b1bebcaea))
* **deps:** group OpenTelemetry packages and exempt digest updates from age gate ([#457](https://github.com/Niecke/lumios/issues/457)) ([177b6b7](https://github.com/Niecke/lumios/commit/177b6b7fbefb0ee63aa231c8b1a535cdc3409ee2))
* **deps:** update dependency authlib to v1.9.1 ([a213bb9](https://github.com/Niecke/lumios/commit/a213bb950be963fbb59fa0fec745a7bc6edfb772))
* **deps:** update dependency authlib to v1.9.1 ([61c294e](https://github.com/Niecke/lumios/commit/61c294e99d1e2fd5b9531c11a047edefed33c1a4))
* **deps:** update dependency boto3 to v1.43.117 ([#471](https://github.com/Niecke/lumios/issues/471)) ([d24b855](https://github.com/Niecke/lumios/commit/d24b85504a0ad7deef7d1fd4c71ca323351fb0a8))
* **deps:** update dependency boto3 to v1.43.118 ([#501](https://github.com/Niecke/lumios/issues/501)) ([69c7625](https://github.com/Niecke/lumios/commit/69c76259e61b1e7d023b8a24b7738c2aaeba7d5b))
* **deps:** update dependency cryptography to v50.0.2 ([8c3db3a](https://github.com/Niecke/lumios/commit/8c3db3aea78528c07b12ce58a74912c7cd259b84))
* **deps:** update dependency cryptography to v50.0.2 ([f67e8bf](https://github.com/Niecke/lumios/commit/f67e8bf95f7a8976c2b7886eb423841ace44f605))
* **deps:** update dependency google-cloud-tasks to v2.26.0 ([#483](https://github.com/Niecke/lumios/issues/483)) ([b4c75bf](https://github.com/Niecke/lumios/commit/b4c75bf2cb6d12650439e3809a87e2ad95e86aa6))
* **deps:** update dependency pillow to v13 [security] ([19a33f9](https://github.com/Niecke/lumios/commit/19a33f975b27dc4bcf9946a86ff953e76229c26e))
* **deps:** update dependency pillow to v13 [security] ([e538082](https://github.com/Niecke/lumios/commit/e53808275a553c322ada0bf168d3e5bc859518f4))
* **deps:** update dependency psycopg to v3.3.6 ([#472](https://github.com/Niecke/lumios/issues/472)) ([47eb56f](https://github.com/Niecke/lumios/commit/47eb56ffe90ed0b9cc56e1018e0c9a7d8a3cfc34))
* **deps:** update dependency pyjwt to v2.15.0 [security] ([4b07976](https://github.com/Niecke/lumios/commit/4b07976a99c67de8ee797ccd2615de3e8b812af8))
* **deps:** update dependency pyjwt to v2.15.0 [security] ([934de1e](https://github.com/Niecke/lumios/commit/934de1ef03a73e22a4e3f2aadf014e5e2a7ad560))
* **deps:** update dependency pyjwt to v2.15.1 ([#473](https://github.com/Niecke/lumios/issues/473)) ([d66765c](https://github.com/Niecke/lumios/commit/d66765c54dc7490cc2fb93f089c70519f7f83df4))
* **deps:** update dependency python-dotenv to v1.2.4 ([#474](https://github.com/Niecke/lumios/issues/474)) ([89c12d1](https://github.com/Niecke/lumios/commit/89c12d19bf54f7b80ccec35152cc99ebac09605e))
* **deps:** update dependency vite to v8.2.4 [security] ([3c3512a](https://github.com/Niecke/lumios/commit/3c3512a10d5e32b55a7a2f1b63542d40552edf19))
* **deps:** update dependency vite to v8.2.4 [security] ([5f90d0a](https://github.com/Niecke/lumios/commit/5f90d0ae3f40aa37df0170b127cff67861958e60))
* sanitize Content-Disposition filenames with RFC 5987 encoding ([#491](https://github.com/Niecke/lumios/issues/491)) ([9463591](https://github.com/Niecke/lumios/commit/946359105742bca34665aaa68937945a8a959773))
* set file timestamps in library zip downloads ([#485](https://github.com/Niecke/lumios/issues/485)) ([ff408e7](https://github.com/Niecke/lumios/commit/ff408e7a61a45c75787668ad300a510d6a0f9659))

## [0.2.0](https://github.com/Niecke/lumios/compare/v0.1.0...v0.2.0) (2026-10-23)


### Features

* add use-original-as-preview toggle, library name editing, back … ([603e3b0](https://github.com/Niecke/lumios/commit/603e3b06845ac09ad220bbde57eb9269eb4cc5cf))
* add use-original-as-preview toggle, library name editing, back navigation ([e9260f9](https://github.com/Niecke/lumios/commit/e9260f9b52f3aadddab86938aa777244bc8a1cab)), closes [#80](https://github.com/Niecke/lumios/issues/80)
* add user self-service account deactivation ([11cf90a](https://github.com/Niecke/lumios/commit/11cf90aa8ac072517f0e994ae9677513b9959731))
* build multi-arch linux/amd64 and linux/arm64 container images ([3d5e61b](https://github.com/Niecke/lumios/commit/3d5e61b2a3d38f8e7697f74f0e00698d3f1c356a))
* **deploy:** add Flux manifests for staging and prod ([05313a7](https://github.com/Niecke/lumios/commit/05313a7a2ad3d4fd8a7f70c6087410e0786af967))
* **deploy:** add Helm chart and Flux GitOps deployment for single-node k3s ([7aa3124](https://github.com/Niecke/lumios/commit/7aa31246a0126cb642ab3762b953c5bd4280be5a))
* **deploy:** add Helm chart for single-node k3s ([66652a2](https://github.com/Niecke/lumios/commit/66652a2144f0cac9cbbdfafa0a72171c21185884))
* replace MinIO with Versity Gateway in local dev and CI ([d4df47c](https://github.com/Niecke/lumios/commit/d4df47c2afb9b55d55d2a812b1279b2e799a1ab6))
* replace MinIO with Versity Gateway in local dev and CI ([f1c1b1d](https://github.com/Niecke/lumios/commit/f1c1b1dbf15a8d820cc89fa1c5c300200d1990a1))
* support multi-arch linux/amd64 and linux/arm64 container builds ([f1f9049](https://github.com/Niecke/lumios/commit/f1f9049c61af662a6740e6464b22e9929c9ccc26))
* switch release management to release-please and automated GHCR promotion ([fdcbcf7](https://github.com/Niecke/lumios/commit/fdcbcf7b080449cbde763baacea7a55a1572ca36))


### Bug Fixes

* 171 ([0c561d3](https://github.com/Niecke/lumios/commit/0c561d3f31d1d21cb1208f1af86f0184657f5957))
* **deploy:** keep frontend /api/ out of basic auth ([049e614](https://github.com/Niecke/lumios/commit/049e614d01abae2da4d0f71ad73181b3244f0eb4))
* **deploy:** require a Redis password ([9c7fc6b](https://github.com/Niecke/lumios/commit/9c7fc6b69cecbe50bdecdd487f6503f7b5773247))
* **deploy:** runtime configuration for frontend google client id and landing url ([737c7d2](https://github.com/Niecke/lumios/commit/737c7d23847e5e7d25d93eb8594e4241b92f5663))
* **deploy:** set frontend runtime config in chart and compose ([8a5c5f2](https://github.com/Niecke/lumios/commit/8a5c5f24ff57bf5860f437eeb83d539ea9b7deb2))
* **e2e:** update share_link test to use renamed `total` field ([e98b18e](https://github.com/Niecke/lumios/commit/e98b18ec1f4ae98d9f197917f0060e012ea0410c))
* **e2e:** update share_link test to use renamed `total` field ([7b91ecf](https://github.com/Niecke/lumios/commit/7b91ecfb8c5101ae0804d79d01f6a6aac1cf31fa))
* **frontend:** clear expired auth token on 401 to prevent login redirect loop ([bb009fd](https://github.com/Niecke/lumios/commit/bb009fdc01aa7a6d82522858936e13e08af6f06a))
* **frontend:** clear expired auth token on 401 to prevent login redirect loop ([3b61086](https://github.com/Niecke/lumios/commit/3b61086e0b71e2fd013571bb07212e9549635aa1))
* **frontend:** read google client id and landing url from runtime config ([000e3e0](https://github.com/Niecke/lumios/commit/000e3e04533a716f0b398e79aae4574a3d47c68d))
* make storage tests self-contained and order-independent ([b908d25](https://github.com/Niecke/lumios/commit/b908d25f7c99cc02a73ac17461e449f870ea3578))
* tag CI images with full head SHA and release only from main ([265511f](https://github.com/Niecke/lumios/commit/265511f84a05dd51357afc1aed4979b3b3cc8ece))
* tighten backend-tests triggers, promote input handling and CI change filter ([d412abf](https://github.com/Niecke/lumios/commit/d412abf06c55f0d3bf0fd565b5791b1d17d5c253))
* unify upload quota check across image and video endpoints ([1c0d6ca](https://github.com/Niecke/lumios/commit/1c0d6ca281e0f44d5aca15e433107e0140bdc121))
* unify upload quota check across image and video endpoints ([45e1cc5](https://github.com/Niecke/lumios/commit/45e1cc56d220134707190bdd2103ac094818b42f))
