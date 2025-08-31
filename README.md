# Mini-SOC Wazuh CI/CD

This project delivers a **Mini-SOC (Security Operations Center)** built on the **Wazuh stack**, integrated with a complete **CI/CD** pipeline and deployed on a **Docker Swarm** cluster.

The goal is to provide a secure, automated, and reproducible SOC environment following modern DevSecOps practices.

---

## 🎯 Project Goals
- Deploy a full **Wazuh stack** (Indexer, Manager, Dashboard).  
- Automate provisioning and deployment with **Ansible**.  
- Implement a **GitHub Actions CI/CD pipeline** with:  
  - Docker image builds.  
  - Vulnerability scanning using **Trivy**.  
  - Automated tests with **Selenium** (UI) and **API probe**.  
  - Conditional deployment to Docker Swarm.  
- Secure access with **Traefik** (reverse proxy + TLS certificates).    

---

## Architecture Overview

### 🔄 CI/CD Pipeline
1. **Build**: build Docker images (optional override).  
2. **Scan**: run **Trivy** scans (fail on HIGH/CRITICAL vulnerabilities).  
3. **Test**: execute Selenium UI tests and API health checks.  
4. **Deploy**: run **Ansible playbooks** to deploy to Docker Swarm (on `main` only after checks pass).  
5. **TLS**: managed by Traefik (Let’s Encrypt or self-signed for testing).  

### ⚙️ Runtime Environment
- **Docker Swarm** (manager + workers)
- **Wazuh**: indexer, manager, dashboard
- **Traefik**: reverse-proxy + ACME
- **Persistent volumes** for indexer/manager data

---

## Quickstart (Local Demo)

### Requirements  
- Docker v20+ and Docker Compose v2  
- Python 3.10+  
- Google Chrome + Chromedriver (or containerized version)  
- Make (optional on Windows) 

### Steps
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

## CI/CD with GitHub Actions

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

## 🔒 Secrets & TLS Management

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
