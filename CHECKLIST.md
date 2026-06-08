# CHECKLIST — sprawdzenie projektu w ~20 minut

> Wariant: **kind** (działa też minikube / k3d — patrz sekcja [Alternatywne klastry](#alternatywne-klastry)).
> Lokalnie używamy overlay `local`, który tworzy namespace `notes-dev` i podmienia
> obrazy z rejestru na lokalne tagi `:dev` (zbudowane przez `docker build` + `kind load`).
> Środowiska `dev` i `prod` używają obrazów z rejestru `ghcr.io` — i to ich używa pipeline CI/CD.
> **Wszystko poniżej można odtworzyć jedną komendą: `.\bootstrap.ps1`** (Windows/PowerShell).

## 0. Wymagania wstępne

- Docker
- `kubectl` (≥ 1.28)
- `kind` (≥ 0.24) — albo `minikube` / `k3d`
- `kustomize` jest wbudowany w `kubectl`

## 1. Utworzenie klastra kind

Klaster tworzymy z plikiem [kind-config.yaml](kind-config.yaml), który nadaje
nodowi etykietę `ingress-ready=true` (wymaga jej kontroler Ingress) oraz mapuje
porty 80/443 na hosta (Ingress dostępny bezpośrednio na `localhost`):

```bash
kind create cluster --name notes --config kind-config.yaml
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

## 4. Wdrożenie (overlay `local`)

Overlay `local` automatycznie podmienia referencje `ghcr.io/REPLACE_OWNER/...`
na lokalne obrazy `notes-*:dev` (przez sekcję `images:` Kustomize), więc nie ma
potrzeby ręcznej edycji manifestów:

```bash
kubectl apply -k k8s/overlays/local
```

## 5. Lista zasobów Kubernetes

```bash
kubectl -n notes-dev get all,ingress,cm,secret,pvc,networkpolicy,pdb
```

Oczekiwany wynik (skrócony):

```
NAME                           READY   STATUS      RESTARTS   AGE
pod/backend-644fb59649-kcwzt   1/1     Running     0          94s
pod/backend-644fb59649-svc76   1/1     Running     0          94s
pod/frontend-5ffd9c55f-f5lvk   1/1     Running     0          94s
pod/notes-migrate-6nx27        0/1     Completed   0          94s
pod/postgres-0                 1/1     Running     0          94s
pod/redis-68d7b56cd4-pqkqt     1/1     Running     0          94s
pod/worker-5856d97bdd-h6wzh    1/1     Running     0          94s

NAME               TYPE        CLUSTER-IP      PORT(S)    AGE
service/backend    ClusterIP   10.96.52.81     8000/TCP   94s
service/frontend   ClusterIP   10.96.248.65    80/TCP     94s
service/postgres   ClusterIP   None            5432/TCP   94s
service/redis      ClusterIP   10.96.149.152   6379/TCP   94s

NAME                       READY   UP-TO-DATE   AVAILABLE
deployment.apps/backend    2/2     2            2
deployment.apps/frontend   1/1     1            1
deployment.apps/redis      1/1     1            1
deployment.apps/worker     1/1     1            1

NAME                        READY
statefulset.apps/postgres   1/1

NAME                      COMPLETIONS   DURATION
job.batch/notes-migrate   1/1           12s

NAME                              CLASS   HOSTS             PORTS
ingress.networking.k8s.io/notes   nginx   notes.dev.local   80

NAME                       DATA
configmap/notes-config     6

NAME                    TYPE
secret/notes-secret     Opaque

NAME                                              STATUS   CAPACITY
persistentvolumeclaim/data-postgres-0             Bound    1Gi

NAME                                                            POD-SELECTOR
networkpolicy.networking.k8s.io/default-deny                    <none>
networkpolicy.networking.k8s.io/allow-postgres-from-backend...  app...=postgres
networkpolicy.networking.k8s.io/allow-redis-from-backend-...    app...=redis
networkpolicy.networking.k8s.io/allow-backend-from-frontend...  app...=backend
networkpolicy.networking.k8s.io/allow-frontend-from-ingress     app...=frontend

NAME                                     MIN AVAILABLE   ALLOWED DISRUPTIONS
poddisruptionbudget.policy/backend       1               1
```

## 6. Weryfikacja rolloutu

```bash
kubectl -n notes-dev rollout status statefulset/postgres --timeout=180s
kubectl -n notes-dev wait --for=condition=complete job/notes-migrate --timeout=180s
kubectl -n notes-dev rollout status deployment/backend   --timeout=180s
kubectl -n notes-dev rollout status deployment/frontend  --timeout=180s
kubectl -n notes-dev rollout status deployment/redis     --timeout=180s
kubectl -n notes-dev rollout status deployment/worker    --timeout=180s
```

## 7. Weryfikacja API (`/health`, `/ready`, CRUD) przez Ingress

Dzięki mapowaniu portów w `kind-config.yaml` Ingress jest dostępny wprost na
`localhost` (nagłówek `Host` kieruje ruch do reguły Ingressa):

```bash
curl -sH 'Host: notes.dev.local' http://localhost/api/health
# {"status":"ok"}

curl -sH 'Host: notes.dev.local' http://localhost/api/ready
# {"status":"ready"}

curl -sH 'Host: notes.dev.local' -X POST http://localhost/api/notes \
  -H 'Content-Type: application/json' \
  -d '{"title":"Pierwsza","content":"hello"}'
# {"id":1,"title":"Pierwsza","content":"hello","created_at":"2026-06-08T..."}

curl -sH 'Host: notes.dev.local' http://localhost/api/notes
# [{"id":1,"title":"Pierwsza","content":"hello","created_at":"..."}]
```

> **PowerShell (Windows):** użyj `curl.exe` (nie aliasu `curl`) i przekaż JSON
> z pliku, by ominąć escapowanie:
> ```powershell
> '{"title":"Pierwsza","content":"hello"}' | Out-File -Encoding ascii note.json
> curl.exe -sH "Host: notes.dev.local" -H "Content-Type: application/json" `
>   --data-binary "@note.json" http://localhost/api/notes
> ```

## 8. Test trwałości danych (PVC przeżywa restart poda)

```bash
# Dodaj rekord
curl -sH 'Host: notes.dev.local' -X POST http://localhost/api/notes \
  -H 'Content-Type: application/json' \
  -d '{"title":"przed-restartem","content":"powinno przetrwac"}'

# Usuń pod bazy
kubectl -n notes-dev delete pod postgres-0
kubectl -n notes-dev rollout status statefulset/postgres --timeout=120s

# Odczytaj rekord po odtworzeniu poda — rekord nadal istnieje
curl -sH 'Host: notes.dev.local' http://localhost/api/notes
# Rekord "przed-restartem" jest nadal widoczny — dane przetrwaly restart poda.
```

## 9. Dowód działania workera (Redis pub/sub)

Worker subskrybuje kanał `notes-events`. Po każdej operacji `POST /notes`
backend publikuje wiadomość, którą worker zapisuje do listy `notes-events-log`
w Redis i loguje na stdout.

```bash
# 1) Tworzymy notatkę
curl -sH 'Host: notes.dev.local' -X POST http://localhost/api/notes \
  -H 'Content-Type: application/json' \
  -d '{"title":"worker-test","content":"ping"}'

# 2) Logi workera:
kubectl -n notes-dev logs deployment/worker --tail=20
# 2026-06-08 15:00:00 INFO worker subscribed to channel 'notes-events'
# 2026-06-08 15:03:51 INFO processed event: created:3:worker-test

# 3) Sprawdzenie zawartości listy w Redis:
kubectl -n notes-dev exec deploy/redis -- redis-cli LRANGE notes-events-log 0 -1
# 1) "created:3:worker-test"
```

## 10. Metryki Prometheusa

Backend wystawia `/metrics` w formacie OpenMetrics oraz adnotacje
`prometheus.io/scrape: "true"` na Deploymencie i Podach:

```bash
curl -sH 'Host: notes.dev.local' http://localhost/api/metrics | grep notes_
# notes_created_total 3.0
# notes_read_total 7.0
# notes_deleted_total 0.0

kubectl -n notes-dev get deploy backend -o jsonpath='{.metadata.annotations}'
# {"prometheus.io/path":"/metrics","prometheus.io/port":"8000","prometheus.io/scrape":"true"}
```

## 11. Frontend (przez Ingress)

```bash
# Mapowanie hosta (raz), by otworzyc w przegladarce:
#   Linux/macOS:  echo "127.0.0.1 notes.dev.local" | sudo tee -a /etc/hosts
#   Windows:      dopisz "127.0.0.1 notes.dev.local" do C:\Windows\System32\drivers\etc\hosts (jako Admin)

curl -sH 'Host: notes.dev.local' http://localhost/ | head -n 5
# <!DOCTYPE html><html lang="pl">...
```

Po dopisaniu do `hosts` aplikacja działa w przeglądarce pod `http://notes.dev.local/`.

## 12. NetworkPolicy — dowód izolacji

```bash
# Pod testowy w tej samej przestrzeni nazw NIE moze sie dobic do Postgresa:
kubectl -n notes-dev run nettest --rm -it --image=busybox --restart=Never -- \
  sh -c 'nc -zv postgres 5432 -w 3 || echo BLOCKED'
# BLOCKED  (oczekiwane — Postgres przyjmuje ruch tylko od backendu i Joba migracji)

# Backend NADAL dochodzi:
kubectl -n notes-dev exec deploy/backend -- \
  python -c "import socket; s=socket.socket(); s.connect(('postgres',5432)); print('OK')"
# OK
```

## 13. PodDisruptionBudget i RollingUpdate

```bash
kubectl -n notes-dev get pdb backend
# NAME      MIN AVAILABLE   ALLOWED DISRUPTIONS
# backend   1               1

# RollingUpdate: restart Deploymentu nie wylacza zera replik:
kubectl -n notes-dev rollout restart deployment/backend
kubectl -n notes-dev rollout status  deployment/backend
```

## 14. securityContext i non-root

```bash
kubectl -n notes-dev exec deploy/backend -- id
# uid=10001 gid=10001 groups=10001
```

## 15. Dwa środowiska (Kustomize overlays)

```bash
# dev — porownanie wartosci (bez wdrazania, obrazy z rejestru ghcr.io):
kubectl kustomize k8s/overlays/dev  | grep -E 'replicas:|minAvailable:|host:'
# replicas: 2 / minAvailable: 1 / host: notes.dev.local

# prod — 3 repliki backendu, PDB minAvailable=2, host notes.prod.local:
kubectl kustomize k8s/overlays/prod | grep -E 'replicas:|minAvailable:|host:'
# replicas: 3 / minAvailable: 2 / host: notes.prod.local
```

> Środowiska `dev`/`prod` używają obrazów z rejestru (`ghcr.io/<owner>/...:TAG`),
> dlatego pełne wdrożenie `prod` na lokalnym kind wymagałoby najpierw publikacji
> obrazów (robi to pipeline CI/CD). Do lokalnej demonstracji wystarczy `local`.

## 16. Sprzątanie

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
| `k8s/overlays/local/` | overlay lokalny (obrazy `:dev` z `kind load`) |
| `k8s/overlays/dev/`, `k8s/overlays/prod/` | overlays Kustomize (dwa środowiska, obrazy z rejestru) |

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
kubectl apply -k k8s/overlays/local
```

**k3d:**
```bash
k3d cluster create notes -p "80:80@loadbalancer"
docker build -t notes-backend:dev ./backend
docker build -t notes-worker:dev -f ./backend/Dockerfile.worker ./backend
docker build -t notes-frontend:dev ./frontend
k3d image import notes-backend:dev notes-worker:dev notes-frontend:dev -c notes
kubectl apply -k k8s/overlays/local
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
| Non-root + securityContext + initContainer/Job do migracji | 8% | `runAsNonRoot`, `runAsUser: 10001`, `Job` `notes-migrate` + initContainer |
| Workflow: build → test → publish → deploy + rollout check | 10% | `.github/workflows/ci-cd.yml` |
| **Dodatkowe:** NetworkPolicy | 2.5% | `networkpolicy.yaml` |
| **Dodatkowe:** PodDisruptionBudget | 2.5% | `pdb.yaml` |
| **Dodatkowe:** Kustomize + 2 środowiska | 2.5% | `k8s/overlays/dev`, `k8s/overlays/prod` |
| **Dodatkowe:** `/metrics` + adnotacje Prometheusa | 2.5% | endpoint w `app/main.py`, adnotacje na Deploymencie |
| Aplikacja: zasób biznesowy + `/health` lub `/ready` | 10% | `app/main.py` (notes CRUD + `/health` + `/ready`) |
| Dane trwałe (przeżywają restart poda) | 5% | sekcja [8](#8-test-trwałości-danych-pvc-przeżywa-restart-poda) |
| Dodatkowy komponent (Redis + worker) | 5% | sekcja [9](#9-dowód-działania-workera-redis-pubsub) |
