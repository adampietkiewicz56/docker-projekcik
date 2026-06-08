# CHECKLIST — sprawdzenie projektu w ~20 minut

> Wariant: **kind** (działa też minikube / k3d — patrz sekcja [Alternatywne klastry](#alternatywne-klastry)).
> W całym dokumencie używamy overlay `dev`, który tworzy namespace `notes-dev` i prefiksuje nazwy zasobów `dev-`.

## 0. Wymagania wstępne

- Docker
- `kubectl` (≥ 1.28)
- `kind` (≥ 0.24) — albo `minikube` / `k3d`
- `kustomize` jest wbudowany w `kubectl`

## 1. Utworzenie klastra kind

```bash
kind create cluster --name notes
```

## 2. Ingress controller (nginx)

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.2/deploy/static/provider/kind/deploy.yaml
kubectl wait --namespace ingress-nginx --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller --timeout=180s
```

## 3. Zbudowanie obrazów i załadowanie ich do klastra

> Pomijamy rejestr — używamy `kind load` bezpośrednio z lokalnego Dockera.

```bash
docker build -t notes-backend:dev  ./backend
docker build -t notes-worker:dev   -f ./backend/Dockerfile.worker ./backend
docker build -t notes-frontend:dev ./frontend
kind load docker-image notes-backend:dev notes-worker:dev notes-frontend:dev --name notes
```

## 4. Podmiana referencji obrazów na lokalne

Manifesty bazowe wskazują na `ghcr.io/REPLACE_OWNER/...:latest`. Do lokalnego
testu podmieniamy je na obrazy z `kind load`:

```bash
# Linux / macOS
sed -i 's|ghcr.io/REPLACE_OWNER/notes-backend:latest|notes-backend:dev|g'   k8s/base/*.yaml
sed -i 's|ghcr.io/REPLACE_OWNER/notes-worker:latest|notes-worker:dev|g'     k8s/base/*.yaml
sed -i 's|ghcr.io/REPLACE_OWNER/notes-frontend:latest|notes-frontend:dev|g' k8s/base/*.yaml
```

W PowerShell (Windows):
```powershell
Get-ChildItem k8s/base/*.yaml | ForEach-Object {
  (Get-Content $_) `
    -replace 'ghcr.io/REPLACE_OWNER/notes-backend:latest', 'notes-backend:dev' `
    -replace 'ghcr.io/REPLACE_OWNER/notes-worker:latest', 'notes-worker:dev' `
    -replace 'ghcr.io/REPLACE_OWNER/notes-frontend:latest', 'notes-frontend:dev' |
  Set-Content $_
}
```

## 5. Wdrożenie

```bash
kubectl apply -k k8s/overlays/dev
```

## 6. Lista zasobów Kubernetes

```bash
kubectl -n notes-dev get all,ingress,cm,secret,pvc,networkpolicy,pdb
```

Oczekiwany wynik (skrócony):

```
NAME                                READY   STATUS    RESTARTS   AGE
pod/dev-backend-67dc5d8b5f-h4nj7    1/1     Running   0          1m
pod/dev-backend-67dc5d8b5f-z2vp9    1/1     Running   0          1m
pod/dev-frontend-7c98b89d6f-r9p8m   1/1     Running   0          1m
pod/dev-postgres-0                  1/1     Running   0          1m
pod/dev-redis-7fbf6b9c79-c8tlx      1/1     Running   0          1m
pod/dev-worker-5b96cb8b4-x8q2z      1/1     Running   0          1m

NAME                   TYPE        CLUSTER-IP      PORT(S)
service/dev-backend    ClusterIP   10.96.20.45     8000/TCP
service/dev-frontend   ClusterIP   10.96.140.122   80/TCP
service/dev-postgres   ClusterIP   None            5432/TCP
service/dev-redis      ClusterIP   10.96.200.71    6379/TCP

NAME                            READY   UP-TO-DATE   AVAILABLE
deployment.apps/dev-backend     2/2     2            2
deployment.apps/dev-frontend    1/1     1            1
deployment.apps/dev-redis       1/1     1            1
deployment.apps/dev-worker      1/1     1            1

NAME                            READY
statefulset.apps/dev-postgres   1/1

NAME                       COMPLETIONS   DURATION
job.batch/dev-notes-migrate 1/1           12s

NAME                                       CLASS   HOSTS            PORTS
ingress.networking.k8s.io/dev-notes        nginx   notes.dev.local  80

NAME                          DATA
configmap/dev-notes-config    6

NAME                          TYPE
secret/dev-notes-secret       Opaque

NAME                                                                STATUS   CAPACITY
persistentvolumeclaim/data-dev-postgres-0                            Bound    1Gi

NAME                                                                POD-SELECTOR
networkpolicy.networking.k8s.io/dev-default-deny                    <none>
networkpolicy.networking.k8s.io/dev-allow-postgres-from-backend...  app=postgres
networkpolicy.networking.k8s.io/dev-allow-redis-from-backend-...    app=redis
networkpolicy.networking.k8s.io/dev-allow-backend-from-frontend...  app=backend
networkpolicy.networking.k8s.io/dev-allow-frontend-from-ingress     app=frontend

NAME                                          MIN AVAILABLE
poddisruptionbudget.policy/dev-backend        1
```

## 7. Weryfikacja rolloutu

```bash
kubectl -n notes-dev rollout status statefulset/dev-postgres --timeout=180s
kubectl -n notes-dev rollout status deployment/dev-backend   --timeout=180s
kubectl -n notes-dev rollout status deployment/dev-frontend  --timeout=180s
kubectl -n notes-dev rollout status deployment/dev-redis     --timeout=180s
kubectl -n notes-dev rollout status deployment/dev-worker    --timeout=180s
```

## 8. Weryfikacja API (`/health`, `/ready`, CRUD)

```bash
kubectl -n notes-dev port-forward svc/dev-backend 8000:8000 &

curl -s http://localhost:8000/health
# {"status":"ok"}

curl -s http://localhost:8000/ready
# {"status":"ready"}

curl -s -X POST http://localhost:8000/notes \
  -H 'Content-Type: application/json' \
  -d '{"title":"Pierwsza","content":"hello"}'
# {"id":1,"title":"Pierwsza","content":"hello","created_at":"2026-06-08T..."}

curl -s http://localhost:8000/notes
# [{"id":1,"title":"Pierwsza","content":"hello","created_at":"..."}]
```

## 9. Test trwałości danych (PVC przeżywa restart poda)

```bash
# Dodaj rekord
curl -s -X POST http://localhost:8000/notes \
  -H 'Content-Type: application/json' \
  -d '{"title":"przed-restartem","content":"powinno przetrwać"}'

# Usuń pod bazy
kubectl -n notes-dev delete pod dev-postgres-0
kubectl -n notes-dev rollout status statefulset/dev-postgres --timeout=120s

# Odczytaj rekord po odtworzeniu poda
curl -s http://localhost:8000/notes | jq
# Rekord "przed-restartem" jest nadal widoczny.
```

## 10. Dowód działania workera (Redis pub/sub)

Worker subskrybuje kanał `notes-events`. Po każdej operacji `POST /notes`
backend publikuje wiadomość, którą worker zapisuje do listy `notes-events-log`
w Redis i loguje na stdout.

```bash
# 1) Tworzymy notatkę
curl -s -X POST http://localhost:8000/notes \
  -H 'Content-Type: application/json' \
  -d '{"title":"worker-test","content":"ping"}'

# 2) Logi workera:
kubectl -n notes-dev logs deployment/dev-worker --tail=20
# 2026-06-08 10:21:33 INFO worker subscribed to channel 'notes-events'
# 2026-06-08 10:21:45 INFO processed event: created:42:worker-test

# 3) Sprawdzenie zawartości listy w Redis:
kubectl -n notes-dev exec deploy/dev-redis -- redis-cli LRANGE notes-events-log 0 -1
# 1) "created:42:worker-test"
```

## 11. Metryki Prometheusa

Backend wystawia `/metrics` w formacie OpenMetrics oraz adnotacje
`prometheus.io/scrape: "true"` na Deploymencie i Podach:

```bash
curl -s http://localhost:8000/metrics | grep notes_
# notes_created_total 3.0
# notes_read_total 7.0
# notes_deleted_total 0.0

kubectl -n notes-dev get deploy dev-backend -o jsonpath='{.metadata.annotations}'
# {"prometheus.io/path":"/metrics","prometheus.io/port":"8000","prometheus.io/scrape":"true"}
```

## 12. Test Ingressa (notes.dev.local)

```bash
# Mapowanie hosta:
echo "127.0.0.1 notes.dev.local" | sudo tee -a /etc/hosts

# Port-forward kontrolera Ingress:
kubectl -n ingress-nginx port-forward svc/ingress-nginx-controller 8080:80 &

curl -sH 'Host: notes.dev.local' http://localhost:8080/api/health
# {"status":"ok"}

curl -sH 'Host: notes.dev.local' http://localhost:8080/ | head -n 5
# <!DOCTYPE html><html>...
```

## 13. NetworkPolicy — dowód izolacji

```bash
# Pod testowy w tej samej przestrzeni nazw NIE może się dobić do Postgresa:
kubectl -n notes-dev run nettest --rm -it --image=busybox --restart=Never -- \
  sh -c 'nc -zv dev-postgres 5432 || echo BLOCKED'
# BLOCKED  (oczekiwane — Postgres przyjmuje ruch tylko od backendu i Joba migracji)

# Backend NADAL dochodzi:
kubectl -n notes-dev exec deploy/dev-backend -- \
  python -c "import socket; s=socket.socket(); s.connect(('dev-postgres',5432)); print('OK')"
# OK
```

## 14. PodDisruptionBudget i RollingUpdate

```bash
kubectl -n notes-dev get pdb dev-backend
# NAME          MIN AVAILABLE   ALLOWED DISRUPTIONS
# dev-backend   1               1

# RollingUpdate: restart Deploymentu nie wyłącza zera replik:
kubectl -n notes-dev rollout restart deployment/dev-backend
kubectl -n notes-dev rollout status  deployment/dev-backend
```

## 15. securityContext i non-root

```bash
kubectl -n notes-dev exec deploy/dev-backend -- id
# uid=10001 gid=10001 groups=10001
```

## 16. Dwa środowiska (Kustomize overlays)

```bash
# dev (zastosowane wyżej)
kubectl get ns notes-dev

# prod (3 repliki backendu, PDB minAvailable=2, host notes.prod.local)
kubectl apply -k k8s/overlays/prod
kubectl get ns notes-prod
kubectl -n notes-prod get deploy prod-backend -o jsonpath='{.spec.replicas}'  # 3
```

## 17. Sprzątanie

```bash
kind delete cluster --name notes
```

## Lista zasobów Kubernetes w projekcie

| Plik | Zasoby |
|---|---|
| `k8s/base/namespace.yaml` | `Namespace` |
| `k8s/base/configmap.yaml` | `ConfigMap` (niepoufne dane: hosty, porty, log level) |
| `k8s/base/secret.yaml` | `Secret` (login/hasło do bazy) |
| `k8s/base/postgres-statefulset.yaml` | `StatefulSet` + `Service` (headless) + `PVC` (volumeClaimTemplates) |
| `k8s/base/redis.yaml` | `Deployment` + `Service` |
| `k8s/base/migration-job.yaml` | `Job` z `initContainer` czekającym na Postgresa |
| `k8s/base/backend.yaml` | `Deployment` (2 repliki, RollingUpdate, sondy, limity, securityContext) + `Service` |
| `k8s/base/worker.yaml` | `Deployment` |
| `k8s/base/frontend.yaml` | `Deployment` + `Service` |
| `k8s/base/ingress.yaml` | `Ingress` (`/` → frontend, `/api` → backend) |
| `k8s/base/networkpolicy.yaml` | 5× `NetworkPolicy` (default-deny + reguły) |
| `k8s/base/pdb.yaml` | `PodDisruptionBudget` (backend) |
| `k8s/overlays/dev/`, `k8s/overlays/prod/` | overlays Kustomize (dwa środowiska) |

## Link do ostatniego udanego workflow

> Po pierwszym push na branch `main` uzupełnij ten link adresem do najnowszego
> zielonego runa: **`https://github.com/<owner>/<repo>/actions/runs/<id>`**

## Alternatywne klastry

**minikube:**
```bash
minikube start --addons=ingress
eval $(minikube docker-env)        # buduj obrazy w demonie minikube
docker build -t notes-backend:dev ./backend
docker build -t notes-worker:dev -f ./backend/Dockerfile.worker ./backend
docker build -t notes-frontend:dev ./frontend
kubectl apply -k k8s/overlays/dev
```

**k3d:**
```bash
k3d cluster create notes -p "8080:80@loadbalancer"
docker build -t notes-backend:dev ./backend
k3d image import notes-backend:dev notes-worker:dev notes-frontend:dev -c notes
kubectl apply -k k8s/overlays/dev
```

## Mapowanie wymagań z CSV → artefakty

| Wymaganie (skrót) | Waga | Realizacja |
|---|---|---|
| Katalog `k8s/` z manifestami (Namespace, Deployment, StatefulSet, Service, Ingress, ConfigMap, Secret, PVC) | 12% | `k8s/base/` + Kustomize |
| Backend = Deployment ≥ 2 repliki + RollingUpdate | 10% | `backend.yaml` (`replicas: 2`, `RollingUpdate`) |
| Baza jako StatefulSet z PVC | 12% | `postgres-statefulset.yaml` (`volumeClaimTemplates`) |
| Komunikacja przez Service; baza/cache/worker bez Ingressa | 10% | `Service` ClusterIP, Ingress tylko dla frontend/backend |
| ConfigMap (niepoufne) + Secret (poufne) | 8% | `configmap.yaml`, `secret.yaml` (`envFrom`) |
| Sondy + resources.requests/limits | 10% | `readinessProbe`, `livenessProbe`, `resources` w każdym podzie |
| Non-root + securityContext + initContainer/Job do migracji | 8% | `runAsNonRoot`, `runAsUser: 10001`, `Job` `dev-notes-migrate` + initContainer |
| Workflow: build → test → publish → deploy + rollout check | 10% | `.github/workflows/ci-cd.yml` |
| **Dodatkowe:** NetworkPolicy | 2.5% | `networkpolicy.yaml` |
| **Dodatkowe:** PodDisruptionBudget | 2.5% | `pdb.yaml` |
| **Dodatkowe:** Kustomize + 2 środowiska | 2.5% | `k8s/overlays/dev`, `k8s/overlays/prod` |
| **Dodatkowe:** `/metrics` + adnotacje Prometheusa | 2.5% | endpoint w `app/main.py`, adnotacje na Deploymencie |
| Aplikacja: zasób biznesowy + `/health` lub `/ready` | 10% | `app/main.py` (notes CRUD + `/health` + `/ready`) |
| Dane trwałe (przeżywają restart poda) | 5% | sekcja [9](#9-test-trwałości-danych-pvc-przeżywa-restart-poda) |
| Dodatkowy komponent (Redis + worker) | 5% | sekcja [10](#10-dowód-działania-workera-redis-pubsub) |
