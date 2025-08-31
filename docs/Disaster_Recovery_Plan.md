# Disaster Recovery (DR) Plan — Mini SOC Threat Incident Scenario

**Version:** 1.0

**Purpose:** This Disaster Recovery (DR) Plan provides a complete, actionable set of procedures, scripts and an executable demo plan to recover the Mini SOC (Wazuh Manager + Indexer + Dashboard) from a catastrophic site failure. It covers RPO/RTO targets and justification, backup design (index snapshots, manager state, IaC), clean-room and partial restore procedures, verification checks, off‑site snapshot strategies, and a reproducible demo with step-by-step commands and Ansible playbook snippets.

---

## Executive summary
This DR plan is designed to ensure timely recovery of security operations so that the SOC can resume detection, enrichment and automated response workflows with minimal data loss. Target RPO and RTO are set according to service criticality and business impact. Backups rely on Elasticsearch/OpenSearch snapshots (incremental), archived Wazuh manager state, and IaC / configuration stored in Git. Restoration procedures cover both full clean-room recovery and partial/targeted restores (indices or single nodes).

---

## 1) RPO & RTO targets (recommended) and justification

| Component | RPO (target) | RTO (target) | Justification |
|---|---:|---:|---|
| Wazuh Manager state (rules, decoders, active-response scripts) | 15 minutes | 1 hour | Manager contains detection logic and triggers responses; short RPO ensures minimal lost rule changes or recent alerts; quick RTO minimizes SOC downtime. |
| Indexer (Elasticsearch/OpenSearch) - hot indices | 15 minutes | 2 hours | Hot indices store recent alerts used for triage. RPO 15m ensures recent events are recoverable; RTO 2h allows cluster bring-up and snapshot restore. |
| Dashboard (Wazuh Dashboard/Kibana saved objects) | 24 hours | 4 hours | Dashboards are important for analyst workflows; can be recreated from exported saved objects. |
| Long-term archives (S3/object store snapshots) | Up to 24 hours | N/A (archival) | Cold storage retention is for compliance and forensic retrieval; not required for immediate operations. |

**Notes & tradeoffs**
- Lower RPO requires higher snapshot frequency and storage. We recommend 15‑minute snapshots for production environments with high EPS and 1‑hour snapshots for smaller deployments.
- RTO depends on infrastructure provisioning method. If using pre-provisioned VMs or Kubernetes, RTO is mostly snapshot-restore time; if using on-demand cloud provisioning, RTO must include instance boot time.

---

## 2) Backup strategy

### 2.1 OpenSearch / Elasticsearch snapshots (indexer)
**Repository types**
- **s3** (recommended for production): use AWS S3 (or S3-compatible object store like MinIO) as snapshot repository. Benefits: off-site durability, lifecycle management.
- **fs** (local filesystem): useful for local quick backups (e.g., mounted NAS). Not sufficient for off-site DR by itself.

**Register snapshot repository (S3 example)**
```bash
# Elasticsearch/Opensearch: register S3 repo (example for Elasticsearch with repository-s3 plugin)
curl -s -X PUT "https://es.example.local:9200/_snapshot/prod_s3_repo" \
  -H 'Content-Type: application/json' -u "${ES_ADMIN_USER}:${ES_ADMIN_PASS}" \
  -d '{
    "type": "s3",
    "settings": {
      "bucket": "company-wazuh-snapshots",
      "region": "us-east-1",
      "base_path": "wazuh_snapshots",
      "client": "default"
    }
  }'
```

**Create snapshot (incremental)**
```bash
SNAPSHOT_NAME="snapshot-$(date -u +%Y%m%dT%H%M%SZ)"
curl -s -X PUT "https://es.example.local:9200/_snapshot/prod_s3_repo/${SNAPSHOT_NAME}?wait_for_completion=true" \
  -u "${ES_ADMIN_USER}:${ES_ADMIN_PASS}" -H 'Content-Type: application/json' \
  -d '{"indices":"wazuh-alerts-*","ignore_unavailable":true,"include_global_state":false}'
```

**Schedule & retention**
- **Frequency:** every **15 minutes** for hot indices (production) — adjust to business needs. Snapshots are incremental and fast after first full snapshot.
- **Retention:** keep last **168** 15‑minute snapshots (around 42 hours) OR keep last 180 daily snapshots for 6 months depending on storage cost. Implement lifecycle pruning (script or automation) to delete snapshots older than retention window.

**Retention script (example)**
```bash
# keep last N snapshots only
REPO=prod_s3_repo
KEEP=168
curl -s -u $ES_ADMIN_USER:$ES_ADMIN_PASS "https://es.example.local:9200/_snapshot/${REPO}/_all" \
  | jq -r '.snapshots[].snapshot' | tac \
  | awk -v k=$KEEP 'NR>k {print}' | xargs -r -n1 -I{} \
  curl -s -X DELETE "https://es.example.local:9200/_snapshot/${REPO}/{}" -u $ES_ADMIN_USER:$ES_ADMIN_PASS
```

**Notes**
- Snapshots are incremental: space used reflects changed segments.
- Ensure snapshot repository credentials are stored in Vault and accessed by automation.


### 2.2 Wazuh Manager critical state (keys/registrations/config)
**Critical data to backup**
- `/var/ossec/etc/ossec.conf` — main configuration.
- `/var/ossec/etc/local_rules.xml`, `local_decoder.xml`, and any custom rule files.
- `/var/ossec/etc/client.keys` — registered agent keys (if using the classic client.keys approach). Note: file location can vary by Wazuh version; verify on your manager.
- `/var/ossec/etc/sslmanager.key` and related certificates used for manager/agent TLS (if present).
- Wazuh API credentials or tokens (if persisted). If API uses external identity or short tokens, ensure bootstrap credentials are stored in Vault.
- `/var/ossec/queue` and archives (optionally) — contains recent events not yet shipped.

**Backup procedure (consistent snapshot)**
1. On active manager, **pause** Wazuh manager processing (or stop manager) to ensure file-system consistency:
   ```bash
   sudo systemctl stop wazuh-manager
   ```
2. Archive critical files and directories:
   ```bash
   TARFILE=wazuh-manager-backup-$(date -u +%Y%m%dT%H%M%SZ).tar.gz
   sudo tar -C / -czf /tmp/${TARFILE} \
       var/ossec/etc var/ossec/queue var/ossec/logs --preserve-permissions
   ```
3. Encrypt and upload backup to object storage (S3):
   ```bash
   gpg --symmetric --cipher-algo AES256 /tmp/${TARFILE}
   aws s3 cp /tmp/${TARFILE}.gpg s3://company-wazuh-backups/wazuh-manager/ --storage-class STANDARD_IA
   ```
4. Start manager:
   ```bash
   sudo systemctl start wazuh-manager
   ```

**Notes**
- If manager run in Kubernetes, take a volume snapshot (CSI snapshot) of the PV containing `/var/ossec`.
- Keep at least 7 recent manager backups in off-site storage.


### 2.3 Config / stack definitions (IaC)
- **Store all IaC in Git** (rules, decoders, Ansible playbooks, Helm charts). The Git repo is the canonical source of truth for stack definitions.
- **Export saved objects** (Kibana / Wazuh Dashboard) regularly via the API and check them into a separate repo or artifact storage.

**Kibana saved objects export example**
```bash
curl -s -X POST "https://kibana.example.local:5601/api/saved_objects/_export" \
  -H "kbn-xsrf: true" -H "Content-Type: application/json" \
  -u ${KIBANA_USER}:${KIBANA_PASS} \
  -d '{"objects":[{"type":"dashboard","id":"<dashboard-id>"}],"includeReferencesDeep":true}' \
  -o /tmp/kibana-saved-objects.ndjson
```

- **IaC backups:** for Kubernetes, ensure Helm charts and values files are versioned; for Docker/Swarm, keep stack compose files and secrets definitions in Vault referenced by Ansible.

---

## 3) Restore procedures

> **Important:** Always validate restores in a separate non‑production environment before performing in production.

### 3.1 Clean-room restore (full site restore)
A clean-room restore assumes the production site is destroyed and we rebuild from scratch in a recovery site or cloud environment.

**High-level steps**
1. **Provision infrastructure** (pre-built images or cloud templates): ES masters & data nodes, Wazuh manager VM(s), Kibana, HAProxy / LB, object storage access, and Vault access.
   - If using Kubernetes, provision the cluster and persistent volumes.
2. **Install and configure Elasticsearch/OpenSearch** using IaC (Ansible/Helm): ensure cluster is healthy and nodes can join.
3. **Register snapshot repository** (S3 or FS) and validate access.
   ```bash
   curl -s -X GET "https://es.recovery:9200/_snapshot/prod_s3_repo" -u $ES_ADMIN_USER:$ES_ADMIN_PASS
   ```
4. **Restore indices from snapshot** (do hot indices first):
   ```bash
   # restore the wazuh-alerts-2025.08.25 index example
   curl -s -X POST "https://es.recovery:9200/_snapshot/prod_s3_repo/${SNAPNAME}/_restore?wait_for_completion=true" \
     -H 'Content-Type: application/json' -u $ES_ADMIN_USER:$ES_ADMIN_PASS \
     -d '{"indices":"wazuh-alerts-*","include_global_state":false}'
   ```
5. **Verify ES cluster health** (`green`) and indices restored.
6. **Restore Wazuh manager state**:
   - Download backup tarball from object storage.
   - Stop Wazuh manager service (if running), extract tarball to `/var/ossec`, ensure ownership `root:ossec` (or correct user), and set permissions.
   - Start Wazuh manager service.
   ```bash
   sudo systemctl stop wazuh-manager
   sudo tar -C / -xzf /tmp/wazuh-manager-backup.tar.gz
   sudo chown -R root:ossec /var/ossec
   sudo systemctl start wazuh-manager
   ```
7. **Restore Kibana / Wazuh Dashboard saved objects** using the saved object import API.
8. **Reconnect agents**: if `client.keys` were restored, agents should reconnect automatically. If not, perform agent re-registration using `manage_agents` or automation.
9. **Smoke test**: generate a test event (SSH brute force) and validate rule 100020 fires, alert stored in restored index, and Slack notification/active response executes.

**Validation checks (clean-room)**
- ES cluster: `GET /_cluster/health` -> `status: green`.
- Indices: `GET /_cat/indices?v` -> expected `wazuh-alerts-*` indices exist.
- Kibana: load main dashboard and confirm saved objects present.
- Wazuh manager: `systemctl status wazuh-manager` and check `ossec.log` for `Started` messages.
- Agents: `curl -s -u user:pass https://manager:55000/agents` -> agent list present.


### 3.2 Partial restore (single index or node)
#### Restore single index from snapshot
```bash
curl -s -X POST "https://es.recovery:9200/_snapshot/prod_s3_repo/${SNAPNAME}/_restore?wait_for_completion=true" \
  -H 'Content-Type: application/json' -u $ES_ADMIN_USER:$ES_ADMIN_PASS -d '{
    "indices":"wazuh-alerts-2025.08.25",
    "include_global_state":false,
    "rename_pattern":"(.*)",
    "rename_replacement":"restored_$1"
  }'
```
- This restores a single index as `restored_wazuh-alerts-2025.08.25` so it does not clash with existing indices.

#### Restore a single node (data node) recovery
- If a data node fails, re-provision node with the same ES configuration and allow shard allocation to rebalance. If local data lost, perform the steps:
  1. Provision replacement node.
  2. Ensure ES settings allow shard allocation.
  3. Start node and monitor `GET _cluster/health` until cluster returns to green.


## 4) Verification: post-restore integrity checks
1. **Cluster health**: `GET /_cluster/health` -> status must be `green`.
2. **Index count / document checks**: `GET /_cat/indices?v` and `GET /wazuh-alerts-*/_count` for sample index counts.
3. **Search historical alert**: `curl -XGET 'https://es:9200/wazuh-alerts-*/_search?q=rule.id:100020&size=5'` to fetch sample alerts.
4. **Dashboard/Saved objects**: Load key dashboards and ensure visualizations render and saved objects import success logs show no conflicts.
5. **Wazuh manager process & logs**: ensure `systemctl status` is running and `tail /var/ossec/logs/ossec.log` shows healthy connections and module starts.
6. **Agent connectivity**: Wazuh API `GET /agents` to ensure agents are connected. Test a sample event from an agent and verify it reaches the restored index.

---

## 5) Off-site / remote snapshot storage and endpoint switching
**Approach**
- Configure two snapshot repositories: `prod_s3_repo` (primary) and `prod_remote_repo` (off-site). Both can point to different S3 buckets or the same bucket in a different region.
- Write snapshots to both repos (or create snapshot, then copy / archive to remote). Alternatively, rely on cross-region replication in the object store.

**Register remote repo example (MinIO / alternate S3 endpoint)**
```bash
curl -s -X PUT "https://es.example.local:9200/_snapshot/prod_remote_repo" -H 'Content-Type: application/json' -u ${ES_ADMIN_USER}:${ES_ADMIN_PASS} -d '{
  "type": "s3",
  "settings": {
    "bucket": "company-wazuh-remote",
    "endpoint": "https://minio-remote.example.com",
    "protocol": "https",
    "access_key": "<VAULT_RETRIEVED_ACCESS_KEY>",
    "secret_key": "<VAULT_RETRIEVED_SECRET_KEY>"
  }
}'
```

**How to switch endpoints during DR**
- In DR, register the remote repo on the recovery cluster and restore snapshots from `prod_remote_repo` instead of primary. The restore steps remain identical.

**Simulated off-site in tests**
- Use a local MinIO server to emulate remote object storage and register it as `prod_remote_repo`. Snapshots will then be restored from that endpoint during the demo.

---

## 6) DR demo — reproducible steps and artifacts
> The demo shows a complete workflow: create snapshots and exports, simulate site failure by stopping/removing production services, spin up recovery environment with Ansible, restore indices and manager state, validate that the dashboard and historical alerts are visible again.

### 6.1 Files provided / scripts (place in repo `scripts/`)

**`scripts/snapshot-es.sh`**
```bash
#!/usr/bin/env bash
set -euo pipefail
ES_HOST=${1:-https://es.example.local:9200}
REPO=${2:-prod_s3_repo}
USER=${ES_USER:-admin}
PASS=${ES_PASS:-changeme}
SNAPNAME="snapshot-$(date -u +%Y%m%dT%H%M%SZ)"

curl -s -u $USER:$PASS -X PUT "$ES_HOST/_snapshot/$REPO/$SNAPNAME?wait_for_completion=true" \
  -H 'Content-Type: application/json' \
  -d '{"indices":"wazuh-alerts-*","include_global_state":false}'

echo "Created snapshot: $SNAPNAME"
```

**`scripts/backup-wazuh-manager.sh`**
```bash
#!/usr/bin/env bash
set -euo pipefail
OUT_DIR=${1:-/tmp}
TSTAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUTFILE=${OUT_DIR}/wazuh-manager-backup-${TSTAMP}.tar.gz

sudo systemctl stop wazuh-manager || true
sudo tar -C / -czf ${OUTFILE} var/ossec/etc var/ossec/queue var/ossec/logs --preserve-permissions
# Optional: encrypt
#gpg --symmetric --cipher-algo AES256 ${OUTFILE}

# Upload to S3 (requires AWS CLI configured)
aws s3 cp ${OUTFILE} s3://company-wazuh-backups/wazuh-manager/

sudo systemctl start wazuh-manager || true

echo "Wazuh manager backup uploaded: ${OUTFILE}"
```

**`scripts/restore-es-from-snapshot.sh`**
```bash
#!/usr/bin/env bash
set -euo pipefail
ES_HOST=${1:-https://es.recovery:9200}
REPO=${2:-prod_s3_repo}
SNAPNAME=${3}
USER=${ES_USER:-admin}
PASS=${ES_PASS:-changeme}

curl -s -u $USER:$PASS -X POST "$ES_HOST/_snapshot/$REPO/$SNAPNAME/_restore?wait_for_completion=true" \
  -H 'Content-Type: application/json' -d '{"indices":"wazuh-alerts-*","include_global_state":false}'

echo "Restore requested for snapshot: $SNAPNAME"
```

**`scripts/restore-wazuh-manager.sh`**
```bash
#!/usr/bin/env bash
set -euo pipefail
S3_PATH=${1}
TMP_DIR=/tmp/wazuh-dr
mkdir -p $TMP_DIR
aws s3 cp ${S3_PATH} ${TMP_DIR}/
FILE=$(basename ${S3_PATH})

sudo systemctl stop wazuh-manager || true
sudo tar -C / -xzf ${TMP_DIR}/${FILE}
sudo chown -R root:ossec /var/ossec || true
sudo systemctl start wazuh-manager

echo "Wazuh manager restored from ${S3_PATH}"
```

### 6.2 Ansible playbook (abridged) — `playbooks/dr-restore.yml`
```yaml
- name: DR restore - Elasticsearch + Wazuh Manager
  hosts: recovery
  become: true
  vars:
    es_host: "https://{{ inventory_hostname }}:9200"
    es_repo: prod_s3_repo
    snapshot_name: "{{ lookup('env','DR_SNAPSHOT') }}"
    wazuh_backup_s3: "s3://company-wazuh-backups/wazuh-manager/wazuh-manager-backup-20250826T020000Z.tar.gz"
  tasks:
    - name: Ensure ES is installed (placeholder role)
      include_role:
        name: es-install

    - name: Wait for ES cluster to be reachable
      uri:
        url: "{{ es_host }}/_cluster/health"
        method: GET
        status_code: 200
        user: "{{ es_admin_user }}"
        password: "{{ es_admin_pass }}"
      register: es_health
      until: es_health.status == 200
      retries: 10
      delay: 15

    - name: Restore indices from snapshot
      shell: |
        /usr/local/bin/restore-es-from-snapshot.sh {{ es_host }} {{ es_repo }} {{ snapshot_name }}

    - name: Restore Wazuh manager backup
      shell: |
        /usr/local/bin/restore-wazuh-manager.sh {{ wazuh_backup_s3 }}

    - name: Import Kibana saved objects (if present)
      uri:
        url: "https://kibana.recovery:5601/api/saved_objects/_import"
        method: POST
        user: "{{ kibana_user }}"
        password: "{{ kibana_pass }}"
        status_code: 200
        headers:
          kbn-xsrf: "true"
        body: "@/tmp/kibana-saved-objects.ndjson"
        body_format: raw
```

> This playbook is intentionally condensed — in production you should break into roles (`es-install`, `wazuh-restore`, `kibana-restore`) and include idempotency and retries.


### 6.3 Demo steps (runnable)

**Preparation (pre-demo)**
1. Ensure you have access to the snapshot repository and S3 backups.
2. Export and commit IaC, saved objects and Ansible playbooks to the DR Git repo.
3. Place helper scripts (above) on the Ansible control node in `/usr/local/bin/` and mark executable.

**Demo**
1. **Take fresh snapshots and backups**
   - `scripts/snapshot-es.sh https://es.example.local:9200 prod_s3_repo`
   - `scripts/backup-wazuh-manager.sh /tmp`

2. **Simulate site failure**
   - On production nodes: `sudo systemctl stop wazuh-manager` and `sudo systemctl stop elasticsearch` OR scale down Kubernetes namespace: `kubectl delete namespace wazuh` (in demo/dev only).
   - Optionally remove pods/volumes to emulate data loss.

3. **Recreate cluster via Ansible**
   - On control node: `ansible-playbook -i inventory/recovery playbooks/dr-restore.yml -e DR_SNAPSHOT=snapshot-20250826T020000Z`
   - Monitor playbook output and capture key milestones (ES reachable, indices restore complete).

4. **Restore Wazuh manager state**
   - Playbook runs `restore-wazuh-manager.sh` which restores `/var/ossec` and starts the service.
   - Capture `systemctl status wazuh-manager` showing `active (running)`.

5. **Validate restored data & dashboards**
   - ES cluster health: `curl -s -u user:pass https://es.recovery:9200/_cluster/health | jq .` -> expect `green` or `yellow` (initial).
   - Search a sample historical alert: `curl -s -u user:pass "https://es.recovery:9200/wazuh-alerts-*/_search?q=rule.id:100020&size=1" | jq .` -> shows at least one historical alert.
   - Open Kibana/Wazuh Dashboard and load an alert dashboard — notice charts populated with restored historical data.

6. **Show automated response runs** (optional)
   - From an agent, inject simulated SSH brute-force test and confirm that alert is generated and active response triggers (attacker IP blocked). Capture Slack message and `ufw status`.

---

## 7) Post-restore runbook & operational notes
- **First 60 minutes post-restore**
  - Monitor ES cluster health and shard allocation.
  - Ensure manager logs show healthy queue processing and no repeated errors.
  - Validate that alerts are being generated (run smoke tests) and integrated notifications (Slack) are functional.

- **Escalation**
  - If cluster remains red after 30 minutes: escalate to platform SRE and consider adding temporary data nodes or restoring a smaller set of indices first (priority: wazuh-alerts-*).
  - If agent reconnections fail: validate `client.keys` and check NAT/firewall rules between agents and managers.

- **Security considerations**
  - Rotate any restored secrets that may have been compromised during outage.
  - Validate ACLs and Vault access – do not restore production credentials to public demonstration environments.

---

## 8) Appendix: useful API commands
- List snapshots:
  ```bash
  curl -s -u $ES_ADMIN_USER:$ES_ADMIN_PASS "https://es.example.local:9200/_snapshot/prod_s3_repo/_all" | jq .
  ```
- Delete a snapshot:
  ```bash
  curl -s -u $ES_ADMIN_USER:$ES_ADMIN_PASS -X DELETE "https://es.example.local:9200/_snapshot/prod_s3_repo/snapshot-20250826T020000Z"
  ```
- Check ES cluster health:
  ```bash
  curl -s -u $ES_ADMIN_USER:$ES_ADMIN_PASS "https://es.example.local:9200/_cluster/health?pretty"
  ```
- Wazuh API get agents (example):
  ```bash
  curl -s -u <api_user>:<api_pass> "https://wazuh-manager:55000/agents" | jq .
  ```
