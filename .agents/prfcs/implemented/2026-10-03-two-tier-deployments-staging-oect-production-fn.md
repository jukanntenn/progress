# PRFC: Two deployment tiers — oect as staging, fn as production

Status: implemented

English | [中文](2026-10-03-two-tier-deployments-staging-oect-production-fn.zh.md)

## Problem

The inventory named `fn`'s group `test` (dogfooding) and reserved a `prod` group for a production host that never came up. In reality `fn`'s dogfooding deployment became the stable, long-running, data-carrying service — the group names lied about which machine mattered, and shipping every locally developed build straight to it made each unvalidated change a production change. Meanwhile there was no fast validation target that could safely break. The placeholder `prod` slot pointed at `oect` (192.168.5.50, arm64), the machine that also hosts the internal registry.

## Decision

**Two named tiers: `staging` = `oect` for fast iteration and acceptance of freshly built images; `prod` = `fn` for the stable service, updated only after the change passes acceptance on staging.** Promotion happens in names and defaults, never by touching the running deployment.

**`fn` is promoted in place, verbatim.** Its host_vars and environment values move unchanged into the `prod` group, so the rendered `docker-compose.yml` and `config.toml` are byte-equivalent to what `fn` runs today; the rename requires and performs no re-deploy.

**Vault labels stay `progress-test` / `progress-prod`.** The placeholder prod vault was hash-compared (no plaintext exposure) against the live test vault and holds the same nine secrets, so the `prod` group keeps the progress-prod-encrypted file and `staging` inherits the progress-test-encrypted file — no re-encryption, no keyring change. `progress-test` is the staging vault-id; the label is historical.

**The playbook defaults to `target=staging` and fails loud on unfilled config.** A pre-task refuses to deploy any host whose `home`, `host_port`, or `health_url` is empty or the `__FILL_ME__` sentinel (staging ships with these placeholders for the operator to fill); an empty `cron` is allowed and means an idle scheduler with manual runs — the right default for acceptance.

## Alternatives considered

**Migrate `fn` to a fresh production host and keep `fn` as dogfooding.** It lost: moving a stable, data-carrying deployment is pure risk with no product value; `fn` already fills the production role in everything but name.

**Keep the group names and add `staging` as a third group.** It lost: "test" hosting the production service is exactly the trap this change removes — names must tell the truth, or the next reader deploys to the wrong tier.

**Re-encrypt the vaults and rename the avpm vault-id to `progress-staging`.** It lost: label aesthetics only; it would touch the keyring and rewrite live secret files for zero functional gain, since both encrypted sets decrypt to identical values.

## Consequences

`ansible-playbook devops/ansible/main.yml` deploys to `oect`; `fn` updates only via an explicit `-e target=prod` after staging acceptance — the gate is procedural, not technical. Both tiers pull the rolling `:main` tag, so builds must keep publishing multi-platform (`oect` is arm64, `fn` pulls the amd64 variant; `docker/build.py --push --all-platforms`), and pushing a newer `:main` for another staging cycle does not affect the running `fn` container until prod is deployed again. Staging carries `__FILL_ME__` placeholders (`host_port`, `health_url` in `group_vars/staging/env.yml`; `home` in `host_vars/oect.yml`) that must be filled before its first deploy. The per-variable vault blocks are managed with `scripts/vault.py` (`set`/`get`/`list`/`check`/`remove`), which hard-codes the env→vault-id map and empties `ANSIBLE_VAULT_IDENTITY_LIST` before decrypting, so `check` validates every variable under exactly its own identity and a misfiled secret fails loudly instead of slipping through the identity-list fallback. `docs/deployment.md`, `docs/observability-deploy.md`, `AGENTS.md`, and the shipping skill state the new default target.
