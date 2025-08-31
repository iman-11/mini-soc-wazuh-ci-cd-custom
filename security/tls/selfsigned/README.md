# Self-signed TLS (Local Testing)

For local demos, Traefik serves a default self-signed certificate when the resolver is set to `selfsigned`.
Your browser and Selenium may show warnings; our CI config adds `--ignore-certificate-errors`.

To switch to Let's Encrypt in production:
1. Set a real DNS (A/AAAA) for your host (e.g., `siem.example.com` -> public IP)
2. Set `tls_mode=letsencrypt` and `acme_email` in `ansible/inventories/prod/group_vars/prod.yml`
3. Redeploy; Traefik will fetch and renew certificates automatically
