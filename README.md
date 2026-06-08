# Notes — wieloserwisowa aplikacja na Kubernetes

Projekt akademicki demonstrujący wdrożenie wieloserwisowej aplikacji w klastrze
Kubernetes wraz z pipeline CI/CD w GitHub Actions.

## Architektura

```
        ┌──────────────┐         ┌──────────────┐
        │   Browser    │         │  GitHub      │
        └──────┬───────┘         │  Actions     │
               │                 └──────┬───────┘
   notes.local │                        │ build + push
               ▼                        ▼
        ┌──────────────┐            ┌─────────┐
        │  Ingress     │            │  GHCR   │
        │  (nginx)     │            └────┬────┘
        └──────┬───────┘                 │ pull
        /      │      /api               ▼
┌──────────────┐   ┌──────────────┐  ┌────────────────┐
│  frontend    │   │  backend     │◄─│ migration Job  │
│  (nginx)     │   │  (FastAPI)   │  └────────────────┘
└──────────────┘   └─────┬────────┘
                         │
                ┌────────┴────────┐
                ▼                 ▼
        ┌─────────────┐     ┌─────────────┐         ┌──────────┐
        │  Postgres   │     │   Redis     │◄────────│  worker  │
        │ StatefulSet │     │ Deployment  │  subscribe (pub/sub)
        │  + PVC      │     └─────────────┘         └──────────┘
        └─────────────┘
```

Komponenty:

| Komponent | Typ zasobu | Repliki | Obraz |
|---|---|---|---|
| frontend | `Deployment` | 1 | `ghcr.io/<owner>/notes-frontend` |
| backend  | `Deployment` (RollingUpdate) | 2+ | `ghcr.io/<owner>/notes-backend` |
| worker   | `Deployment` | 1 | `ghcr.io/<owner>/notes-worker` |
| postgres | `StatefulSet` + `PVC` | 1 | `postgres:16-alpine` |
| redis    | `Deployment` | 1 | `redis:7-alpine` |
| migracja | `Job` (z `initContainer` na Postgresa) | — | obraz backendu |

Zasób biznesowy: **note** (`id`, `title`, `content`, `created_at`).
Zewnętrznie dostępne są **wyłącznie** frontend i backend (przez Ingress).
Postgres, Redis i worker mają usługi `ClusterIP` i nie są wystawione na zewnątrz.

## Struktura katalogów

```
.
├── backend/                  # FastAPI + worker + testy
├── frontend/                 # statyczny HTML/JS + nginx
├── k8s/
│   ├── base/                 # manifesty bazowe (Kustomize)
│   └── overlays/{dev,prod}/  # parametryzacja środowisk
└── .github/workflows/ci-cd.yml
```

Szczegółowa instrukcja uruchomienia i lista zasobów: [CHECKLIST.md](CHECKLIST.md).

## Lokalne uruchomienie (skrót)

Najprościej — jeden skrypt robiący wszystko (klaster, Ingress, build, load, deploy, smoke test):

```powershell
.\bootstrap.ps1
```

Albo ręcznie:

```bash
# 1. Klaster kind (z etykietą ingress-ready + mapowaniem portów) + Ingress
kind create cluster --name notes --config kind-config.yaml
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.2/deploy/static/provider/kind/deploy.yaml
kubectl wait --namespace ingress-nginx --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller --timeout=180s

# 2. Build i load obrazów do klastra
docker build -t notes-backend:dev  ./backend
docker build -t notes-worker:dev   -f ./backend/Dockerfile.worker ./backend
docker build -t notes-frontend:dev ./frontend
kind load docker-image notes-backend:dev notes-worker:dev notes-frontend:dev --name notes

# 3. Wdrożenie — overlay "local" podmienia obrazy ghcr.io na lokalne tagi :dev
kubectl apply -k k8s/overlays/local

# 4. Weryfikacja
kubectl -n notes-dev get all
kubectl -n notes-dev rollout status deploy/backend
```

> **Overlay `local` vs `dev`/`prod`:** `local` używa obrazów zbudowanych lokalnie
> (`notes-*:dev`, wgranych przez `kind load`). Środowiska `dev` i `prod` używają
> obrazów z rejestru `ghcr.io` — i to ich używa pipeline CI/CD.

Pełna lista komend, przykładowe wyniki i test trwałości danych: [CHECKLIST.md](CHECKLIST.md).

## CI/CD

`.github/workflows/ci-cd.yml`:

1. **test** — uruchamia `pytest` na backendzie.
2. **build-and-push** — buduje 3 obrazy (backend, worker, frontend) i publikuje do `ghcr.io`.
3. **deploy-kind** — tworzy klaster kind w runnerze, instaluje Ingress, aplikuje overlay `dev`, czeka na rollout wszystkich deploymentów i statefulsetu, wykonuje smoke-test API (`/health`, `/ready`, `POST /notes`, `GET /notes`, `/metrics`).

Link do ostatniego udanego workflow: zobacz [CHECKLIST.md](CHECKLIST.md#link-do-ostatniego-udanego-workflow).
