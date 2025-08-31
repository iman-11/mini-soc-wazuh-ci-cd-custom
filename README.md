# Mini SOC — Wazuh

A production-grade, reproducible reference implementation for **Wazuh as a Mini SOC**.
It deploys the **Wazuh stack** (Indexer, Manager, Dashboard) onto **Docker Swarm**, fronted by **Traefik** with HTTPS, and wired into a full **CI/CD** pipeline with **Trivy** scanning and **Selenium/API tests**.

> Works on self-hosted GitHub runners and locally. Secrets are handled via **Swarm Secrets** and **Ansible Vault**.

---

## Architecture Overview

**Pipeline**
1. **Build** container images (optional override of upstream)
2. **Scan** with **Trivy** — fail on HIGH/CRITICAL
3. **Test** with Selenium (UI) and API health probe
4. **Deploy** via **Ansible** to **Docker Swarm** (only on `main` after checks pass)
5. **TLS** via Traefik (Let’s Encrypt or self-signed for labs)

**Runtime**
- **Docker Swarm** (manager + workers)
- **Wazuh**: indexer, manager, dashboard
- **Traefik**: reverse-proxy + ACME
- **Persistent volumes** for indexer/manager data

---

## Quickstart (Local Demo)

> Requires: Docker (20+), Docker Compose v2, Python 3.10+, Chrome + Chromedriver (or use containers), Make.

```bash
# 1) Clone
git clone 
cd mini-soc-wazuh-swarm

# 2) (Optional) Build local images (you can skip to use upstream)
make build

# 3) Start ephemeral test env (Compose) for Selenium/API smoke tests
make up-test

# 4) Run tests
make test

# 5) Stop test env
make down-test
```

> The test env binds **https://localhost** via Traefik with a **self-signed** cert. Selenium is configured to ignore TLS errors in CI.

---

## CI/CD (GitHub Actions)

Pipeline stages:
- **lint**: yamllint + ansible-lint (bonus quality gates)
- **build-scan**: Build images (optional) + Trivy scan (fail on HIGH/CRITICAL)
- **test**: Spin up ephemeral env, run Selenium + API probe, collect artifacts
- **deploy**: Run **Ansible** to deploy to Swarm (only on `main`)

Runner prerequisites (self-hosted):
- Docker & Compose
- Python 3.10+
- Ansible 2.16+
- Trivy 0.50+
- Google Chrome + chromedriver (or Playwright alternative)
- `ansible-vault` password available on runner (file path or env var)

See: `.github/workflows/ci.yml`

---

## Deployment to Docker Swarm (Ansible)

1. Create/adjust inventory:
   - `ansible/inventories/prod/hosts.ini` — set your Swarm manager/worker IPs
   - `ansible/group_vars/prod.yml` — set domain, email, TLS mode (letsencrypt/selfsigned)

2. Prepare secrets:
   - Create Wazuh admin password secret in Swarm:
     ```bash
     echo -n 'StrongP@ssw0rd!' | docker secret create wazuh_admin_password -
     ```
   - (Optional) Ansible Vault for vars:
     ```bash
     ansible-vault encrypt ansible/group_vars/prod.yml
     ```

3. Bootstrap Swarm and deploy:
   ```bash
   ansible-playbook -i ansible/inventories/prod ansible/playbooks/deploy.yml
   ```

4. Access the dashboard:
   - URL: `https://<your-domain-or-ip>` (Traefik routes to Wazuh dashboard)
   - Default user: `admin` (or value you configured)
   - Password: stored in Swarm secret `wazuh_admin_password`

Rollback:
```bash
ansible-playbook -i ansible/inventories/prod ansible/playbooks/rollback.yml
```
Teardown:
```bash
ansible-playbook -i ansible/inventories/prod ansible/playbooks/teardown.yml
```

---

## Secrets & TLS

- Use:
  - GitHub Secrets → injected to jobs
  - **Ansible Vault** for inventories/group_vars
  - **Swarm Secrets** for runtime (e.g., `wazuh_admin_password`)
- TLS:
  - **Let’s Encrypt** if you have a resolvable domain pointing to Traefik
  - **Self-signed** for labs — trust chain documented in `security/tls/selfsigned/`

Rotation:
- Rotate Wazuh admin password every 90 days (new secret + rolling update)
- Traefik auto-renews Let’s Encrypt certs

---

## Repo Layout

```
.
├── .github/workflows/ci.yml
├── Makefile
├── README.md
├── ansible/
│   ├── ansible.cfg
│   ├── inventories/
│   │   └── prod/
│   │       ├── hosts.ini
│   │       └── group_vars/
│   │           └── prod.yml
│   ├── playbooks/
│   │   └── roles/
│   │   │   ├── swarm/
│   │   │   │   └── tasks/main.yml
│   │   │   ├── network/
│   │   │   │   └── tasks/main.yml
│   │   │   ├── secrets/
│   │   │   │   └── tasks/main.yml
│   │   │   └── stack/
│   │   │       └── tasks/main.yml
│   │   ├── deploy.yml
│   │   ├── rollback.yml
│   │   └── teardown.yml
├── docker/
│   ├── manager/Dockerfile
│   └── dashboard/Dockerfile
├── stack/
│   └── wazuh-stack.yml
├── security/
│   ├── traefik/
│   │   ├── traefik.yml
│   │   └── dynamic.yml
│   └── tls/
│       └── selfsigned/README.md
├── tests/
│   ├── selenium/
│   │   └── test_dashboard.py
│   └── api/
│       └── test_api_health.py
└── trivy/
    └── config.yaml
```

---

## How to Run CI Locally

Use `act` (optional) or run the Make targets:
```bash
make lint
make scan
make test
```

---

## Assumptions

- DNS `wazuh.local` or public domain points to Traefik host
- Ingress TCP/443 reachable from your workstation
- Runner has permissions to run Docker and SSH to Swarm manager(s)
