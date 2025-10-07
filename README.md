## Cloudflare Access + Kubernetes TokenReview Webhook

This repository contains a minimal authentication webhook for Kubernetes that validates Cloudflare Access JSON Web Tokens (JWTs) and responds with a standard TokenReview. It enables non-interactive authentication for tools like kubectl, Lens, and CI/CD pipelines without client certificates, and can be combined with Cloudflare Tunnel to keep your Kubernetes API private.

Replace placeholders like `<your-team>` and `kubeapi.example.com` with your own values.

### What this is
- A small FastAPI service that:
  - Downloads Cloudflare’s JWKS and verifies Access JWTs (issuer, audience, signature, expiry).
  - Maps token claims (e.g., email) to Kubernetes identities for RBAC.
  - Implements Kubernetes TokenReview v1 at the root path `/`.
- Containerized and publishable to GHCR via the provided GitHub Actions workflow.

### When to use it
- You want non-interactive Kubernetes access for humans and CI using Cloudflare Access Service Tokens.
- You want to keep your Kubernetes API behind Cloudflare (optionally via a Cloudflare Tunnel) with no public exposure and no client certs.
- You prefer RBAC authorization inside Kubernetes based on identities derived from Cloudflare claims.

---

## Prerequisites

- Cloudflare account with Zero Trust enabled and a domain onboarded to Cloudflare.
- A Cloudflare Access application protecting your Kubernetes API hostname (for example, `https://kubeapi.example.com`).
- Optionally, a Cloudflare Tunnel routing the external hostname to your in-cluster Kubernetes API (TCP).
- A Kubernetes cluster where you can configure the API server to use a webhook token authenticator.
- kubectl (and optionally Lens) installed on client machines or CI runners.

---

## Runtime configuration

The webhook uses environment variables to validate Cloudflare Access JWTs:

- `CF_TEAM_DOMAIN`: The team domain (issuer) for Cloudflare Access, e.g. `https://<your-team>.cloudflareaccess.com`.
- `CF_APP_AUD`: The Cloudflare Access application Audience (`aud`) value.

The server listens on port `8080` by default (see `Dockerfile` and `main.py`).

---

## Deploy the webhook to Kubernetes

Example Service and Deployment (replace placeholders accordingly):

```yaml
apiVersion: v1
kind: Service
metadata:
  name: cf-access-authn
  namespace: default
spec:
  selector:
    app: cf-access-authn
  ports:
    - name: http
      port: 8080
      targetPort: 8080
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cf-access-authn
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: cf-access-authn
  template:
    metadata:
      labels:
        app: cf-access-authn
    spec:
      containers:
        - name: webhook
          image: ghcr.io/<OWNER>/<REPO>:<TAG>
          env:
            - name: CF_TEAM_DOMAIN
              value: "https://<your-team>.cloudflareaccess.com"
            - name: CF_APP_AUD
              value: "<your-access-app-audience>"
          ports:
            - containerPort: 8080
```

---

## Configure Kubernetes API server to use the webhook

Create a webhook kubeconfig (the API server will call this URL to validate bearer tokens). If you deploy the service above in the same cluster, you can use a ClusterIP service with HTTP for simplicity, or add TLS as desired.

Example kubeconfig file used by the API server (e.g., `/etc/kubernetes/cloudflare-authn.kubeconfig` or for k3s `/var/lib/rancher/k3s/server/cloudflare-authn.kubeconfig`):

```yaml
apiVersion: v1
kind: Config
clusters:
- name: cf-access-authn
  cluster:
    server: http://cf-access-authn.default.svc.cluster.local:8080
    insecure-skip-tls-verify: true
users:
- name: cf-access-authn
  user:
    token: "not-used-for-http"
contexts:
- context:
    cluster: cf-access-authn
    user: cf-access-authn
  name: cf-access-authn
current-context: cf-access-authn
```

Enable webhook token authentication on your API server:

- k3s (edit `/etc/rancher/k3s/config.yaml`):

```yaml
kube-apiserver-arg:
  - "authentication-token-webhook-config-file=/var/lib/rancher/k3s/server/cloudflare-authn.kubeconfig"
  - "authorization-mode=Node,RBAC"
```

Then restart k3s (e.g., `sudo systemctl restart k3s`). For kubeadm or other distributions, set `--authentication-token-webhook-config-file` on the kube-apiserver accordingly.

---

## Optional: Cloudflare Tunnel for the Kubernetes API

To keep your Kubernetes API private while still accessible via a friendly hostname, route it through a Cloudflare Tunnel as a TCP service. The edge terminates TLS for your public hostname (e.g., `kubeapi.example.com`), while the tunnel forwards to the in-cluster API (`kubernetes.default.svc.cluster.local:443`).

Key docs:
- Tunnels on Kubernetes: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/environments/kubernetes/
- Origin configuration, TCP services: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/configure-tunnels/origin-configuration/#tcp

---

## Client access (non-interactive)

Use Cloudflare Access Service Tokens to obtain short-lived Access JWTs for kubectl, Lens, and CI.

Auth helper script example (uses `cloudflared access token`):

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${CF_ACCESS_CLIENT_ID:?missing CF_ACCESS_CLIENT_ID}"
: "${CF_ACCESS_CLIENT_SECRET:?missing CF_ACCESS_CLIENT_SECRET}"
: "${CLOUDFLARE_APP_URL:?missing CLOUDFLARE_APP_URL}"

TOKEN="$(cloudflared access token --app="${CLOUDFLARE_APP_URL}")"
printf '{ "apiVersion": "client.authentication.k8s.io/v1", "kind": "ExecCredential", "status": { "token": "%s" } }\n' "${TOKEN}"
```

Kubeconfig snippet using an exec credential plugin:

```yaml
apiVersion: v1
kind: Config
clusters:
- cluster:
    server: https://kubeapi.example.com
  name: cloudflare-protected
users:
- name: cloudflare-user
  user:
    exec:
      apiVersion: client.authentication.k8s.io/v1
      command: /usr/local/bin/cloudflare-k8s-auth.sh
      env:
        - name: CF_ACCESS_CLIENT_ID
          value: "<service_token_client_id>"
        - name: CF_ACCESS_CLIENT_SECRET
          value: "<service_token_client_secret>"
        - name: CLOUDFLARE_APP_URL
          value: "https://kubeapi.example.com"
      interactiveMode: Never
contexts:
- context:
    cluster: cloudflare-protected
    user: cloudflare-user
  name: cf-context
current-context: cf-context
```

---

## Security considerations

- Treat Cloudflare Service Token credentials as secrets; rotate regularly.
- Prefer short token lifetimes and least-privilege RBAC.
- Keep the webhook internal (ClusterIP), add rate limits/logging as needed.
- Use TLS for the webhook if your security posture requires it.

---

## References

- Tutorial: kubectl with Cloudflare Access (client-go plugin)
  - https://developers.cloudflare.com/cloudflare-one/tutorials/tunnel-kubectl/
- Cloudflare Access Service Tokens
  - https://developers.cloudflare.com/cloudflare-one/identity/service-tokens/
- Validate Access JWTs (issuer/audience/JWKS)
  - https://developers.cloudflare.com/cloudflare-one/identity/authorization-cookie/validate-jwt/
- Cloudflared downloads
  - https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
- Cloudflare Tunnel origin configuration (TCP)
  - https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/configure-tunnels/origin-configuration/#tcp
- Tunnels on Kubernetes (environment guidance)
  - https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/environments/kubernetes/
- Kubernetes webhook token authentication
  - https://kubernetes.io/docs/reference/access-authn-authz/authentication/#webhook-token-authentication
- TokenReview v1 API schema
  - https://kubernetes.io/docs/reference/kubernetes-api/authorization-resources/token-review-v1/
- client-go exec credential plugins
  - https://kubernetes.io/docs/reference/access-authn-authz/authentication/#configuration
- k3s server configuration
  - https://docs.k3s.io/reference/server-config
