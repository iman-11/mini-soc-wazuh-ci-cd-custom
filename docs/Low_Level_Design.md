# Low‑Level Design (LLD) — Mini SOC

**Document version:** 1.0

**Author:** Technical Architect

**Audience:** Platform engineers, DevOps, SREs, and implementers

**Purpose:** Provide detailed inventories, exact service manifests, storage mapping, network design, CI/CD job definitions, secrets & certificates procedures, and runbooks required to deploy and operate the Mini SOC Part 1 stack in a reproducible, secure, and scalable manner.

---

## 1. Inventories

**Example inventory (production‑like)**

| Role | Hostname | Example IP | Labels | Ports |
|---|---:|---:|---|---:|
| LB | lb-01 | 10.0.0.10 | role=lb | 1514/TCP, 5601/TCP, 80/443 |
| Wazuh Manager (active) | wazuh-mgr-01 | 10.0.10.11 | role=manager,zone=primary | 1514/TCP, 1515/TCP, 55000/TCP |
| Wazuh Manager (passive) | wazuh-mgr-02 | 10.0.10.12 | role=manager,zone=secondary | 1514/TCP, 1515/TCP |
| ES master-1 | es-master-01 | 10.0.20.11 | role=es-master | 9200/TCP,9300/TCP |
| ES master-2 | es-master-02 | 10.0.20.12 | role=es-master | 9200/TCP,9300/TCP |
| ES master-3 | es-master-03 | 10.0.20.13 | role=es-master | 9200/TCP,9300/TCP |
| ES data-1 | es-data-01 | 10.0.20.21 | role=es-data | 9200/TCP,9300/TCP |
| ES data-2 | es-data-02 | 10.0.20.22 | role=es-data | 9200/TCP,9300/TCP |
| Kibana | kibana-01 | 10.0.30.11 | role=kibana | 5601/TCP |
| CI Runner / Ansible | ci-01 | 10.0.40.11 | role=ci | SSH, HTTPS |
| Vault | vault-01 | 10.0.50.11 | role=vault | 8200/TCP |

> Use your organization's IP plan and labels. These are example addresses for architecture planning.

---

## 2. Service specifications (manifests)
Below are production-ready snippets for Kubernetes (Helm) or Docker Swarm. Adapt to your platform.

### a) Wazuh Manager — Deployment (Kubernetes)
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: wazuh-manager
  labels:
    app: wazuh-manager
spec:
  replicas: 2
  selector:
    matchLabels:
      app: wazuh-manager
  template:
    metadata:
      labels:
        app: wazuh-manager
    spec:
      containers:
      - name: wazuh-manager
        image: wazuh/wazuh:5.1.0
        env:
        - name: MANAGER_CLUSTER
          value: "true"
        ports:
        - containerPort: 1514
          name: agent-comm
        - containerPort: 55000
          name: api
        resources:
          requests:
            cpu: "2000m"
            memory: "4Gi"
          limits:
            cpu: "4000m"
            memory: "8Gi"
        readinessProbe:
          tcpSocket:
            port: 1514
          initialDelaySeconds: 30
          periodSeconds: 10
        livenessProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - "/var/ossec/bin/ossec-control status"
          initialDelaySeconds: 60
          periodSeconds: 30
        volumeMounts:
        - name: wazuh-data
          mountPath: /var/ossec
      volumes:
      - name: wazuh-data
        persistentVolumeClaim:
          claimName: wazuh-data-pvc
```

### b) Elasticsearch Master StatefulSet (abridged)
(See HLD for full example. Use dedicated storage class with SSD-backed PVs.)

---

## 3. Environment variables & resource limits
**Wazuh Manager container env vars (recommended):**
- `WAZUH_MANAGER_CLUSTER=true`
- `WAZUH_API_USER` and `WAZUH_API_PASSWORD` – injected via Vault agent or K8s secret.
- `WAZUH_LOG_LEVEL`=INFO

**Resource limits:**
- Manager: requests `2 CPU`, `4GB` memory; limits `4 CPU`, `8GB` memory (adjust per load testing).
- ES data nodes: requests `8 CPU`, `16GB`; limits `16 CPU`, `64GB`.

---

## 4. Storage mapping & backup schedule
**Mount points & volumes:**
- Wazuh Manager data: `/var/ossec` -> PVC (K8s) or LVM volume. Snapshot weekly and before upgrades.
- ES data: `/usr/share/elasticsearch/data` -> high‑performance NVMe PVs.
- Kibana/state: `/usr/share/kibana/data` -> small PVC.

**Backup schedule:**
- ES snapshots: every 15 minutes (hot) to S3 repo for critical indices (`wazuh-alerts-*`); daily full snapshot at 02:00.
- Manager backups: daily tarball of `/var/ossec/etc` and queue directories; retain 7 backups on S3.
- Saved objects export: daily export of Kibana/Wazuh Dashboard saved objects to Git or object store.

---

## 5. Network design & firewall rules
**Overlay networks:**
- `wazuh-net` overlay for internal traffic.
- Subnets: agents (10.1.0.0/16), infra (10.2.0.0/16), storage (10.3.0.0/16).

**LB listeners & firewall**
- HAProxy:
  - Listener: `0.0.0.0:1514` -> managers (agent traffic)
  - Listener: `0.0.0.0:5601` -> Kibana
- Firewall rules (manager zone):
  - Allow 1514/TCP from agent CIDR.
  - Allow 1515/TCP from agent CIDR (enrollment).
  - Allow 9200/TCP between manager and ES.
  - Allow 55000/TCP from dashboard/CI to manager API.

---

## 6. CI/CD pipeline (detailed)
**Purpose:** validate and deploy decoders, rules, integration scripts and manifests.

**Stages & steps:**
1. **Lint & unit tests**
   - YAML lint, shellcheck for scripts.
   - `ossec-logtest` unit tests for new rules (simulate sample logs and assert alert ids).
2. **Build**
   - Build any custom images (if containers used). Tag with SHA.
3. **Security Scan**
   - Use Trivy to scan images for CVEs.
   - Run SAST scanners for scripts.
4. **Integration Tests**
   - Deploy to ephemeral test environment (docker-compose or kind cluster).
   - Run E2E smoke tests: inject logs, assert rule 100020 fires.
5. **Publish**
   - Push artifacts/images to internal registry.
6. **Staging Deploy**
   - Run Ansible playbook to update staging managers. Run `ossec-logtest` to validate.
7. **Acceptance**
   - Manual verification by SOC; if passes, proceed.
8. **Production Deploy**
   - Ansible apply to production inventory with change control.

**Gates:**
- PR must pass lint and tests.
- Trivy high severity vulnerabilities block promotion.
- Manual SOC approval required for production deploy.

**Example CI job (GitLab snippet)**
```yaml
stages:
  - lint
  - test
  - scan
  - deploy

lint:
  script:
    - yamllint .
    - shellcheck scripts/*.sh

trivy:
  script:
    - trivy image $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA

deploy_staging:
  stage: deploy
  script:
    - ansible-playbook -i inventories/staging playbooks/deploy.yml
  when: manual
```

---

## 7. Secrets & Certificates
**Vault structure (recommended):**
- `secret/data/wazuh/manager/api` -> Wazuh API credentials
- `secret/data/wazuh/slack/webhook` -> Slack webhook URL
- `secret/data/es/credentials` -> ES admin credentials

**Access & rotation:**
- Vault policies per role (e.g., `wazuh-manager-role` with read access to only its secrets).
- Rotate webhooks quarterly and DB credentials monthly via automation.

**Certificates:**
- Use Vault PKI for issuing short‑lived certs for manager<->agent and manager<->indexer TLS.
- Use cert‑manager in K8s for auto-renewal.

---

## 8. Runbooks
### Bootstrap (fresh deployment)
1. Provision infra (nodes, storage, LB).
2. Install Vault and generate PKI root/intermediate.
3. Deploy Elasticsearch masters and verify cluster health.
4. Deploy Wazuh managers and register sample agent.
5. Deploy Kibana and import saved objects.
6. Run E2E test (simulate SSH brute force) and validate alert flow and active response.

### Day‑2 Operations
**Scale out**
- Add ES data node via Helm/Ansible; ensure PV attached; monitor shard reallocation.

**Scale in**
- Move indices away from node (shard allocation), then remove node safely.

**Common failures**
- **Agent not connecting:** check LB & firewall, manager logs (`ossec.log`), and certificate validity.
- **ES cluster red:** examine unassigned shards, disk pressure, and master node health.
- **Active response fails:** verify script permissions, executable path, and `active-responses.log`.

---

## 9. Component / Service Diagram (LLD)
```
+------------+        +--------+        +------------------+
| Wazuh Agent| -----> |  LB    | -----> | Wazuh Manager(s) |
+------------+        +--------+        +------------------+
                                              |     |
                                              v     v
                                          ES Data  Kibana
                                          Nodes     Dashboard
```
