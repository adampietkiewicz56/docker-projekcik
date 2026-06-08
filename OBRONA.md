# OBRONA — przejście przez projekt w 20 minut

Dokument prowadzi przez **każde** wymaganie z arkusza punktacji. Dla każdego
punktu masz: **gdzie to jest w kodzie**, **co dokładnie robi** i **komendę do
demonstracji na żywo** wraz z oczekiwanym wynikiem.

Przed obroną otwórz **dwa terminale w katalogu projektu** i upewnij się, że:

```powershell
kubectl -n notes-dev get pods
# wszystkie pody w stanie Running / Completed
```

Jeśli klastra nie ma — odpal `.\bootstrap.ps1` (~3 min).

> **Skrót nazw plików:**
> - manifesty: [k8s/base/](k8s/base/) + [k8s/overlays/dev/](k8s/overlays/dev/)
> - aplikacja: [backend/app/](backend/app/) + [frontend/](frontend/)
> - workflow CI/CD: [.github/workflows/ci-cd.yml](.github/workflows/ci-cd.yml)

---

## Część A — Wymagania architektoniczne (80%)

### A1. Komplet zasobów Kubernetes — 12% (4.8 pkt)

> *„Projekt zawiera katalog k8s/ albo Helm/Kustomize. Manifesty obejmują minimum:
> Namespace, Deployment, StatefulSet lub równoważny zasób dla bazy, Service,
> Ingress, ConfigMap, Secret, PVC."*

**Gdzie to jest:**

| Zasób | Plik |
|---|---|
| `Namespace` | [k8s/base/namespace.yaml](k8s/base/namespace.yaml) |
| `ConfigMap` | [k8s/base/configmap.yaml](k8s/base/configmap.yaml) |
| `Secret` | [k8s/base/secret.yaml](k8s/base/secret.yaml) |
| `StatefulSet` + `PVC` (przez `volumeClaimTemplates`) | [k8s/base/postgres-statefulset.yaml](k8s/base/postgres-statefulset.yaml) |
| `Deployment` (4 sztuki: backend, frontend, redis, worker) | [k8s/base/backend.yaml](k8s/base/backend.yaml), [frontend.yaml](k8s/base/frontend.yaml), [redis.yaml](k8s/base/redis.yaml), [worker.yaml](k8s/base/worker.yaml) |
| `Service` (4 sztuki) | jak wyżej + [postgres-statefulset.yaml:1-13](k8s/base/postgres-statefulset.yaml) (headless) |
| `Ingress` | [k8s/base/ingress.yaml](k8s/base/ingress.yaml) |
| `Job` migracji | [k8s/base/migration-job.yaml](k8s/base/migration-job.yaml) |
| `NetworkPolicy` (5×) | [k8s/base/networkpolicy.yaml](k8s/base/networkpolicy.yaml) |
| `PodDisruptionBudget` | [k8s/base/pdb.yaml](k8s/base/pdb.yaml) |
| Kustomize spinający wszystko | [k8s/base/kustomization.yaml](k8s/base/kustomization.yaml) |

**Demo:**

```powershell
kubectl -n notes-dev get all,ingress,cm,secret,pvc,networkpolicy,pdb
```

Pokaż, że są wszystkie typy zasobów. PVC `data-postgres-0` powstał automatycznie
z `volumeClaimTemplates` w StatefulSecie.

---

### A2. Backend ≥ 2 repliki + RollingUpdate — 10% (4.0 pkt)

> *„Frontend/API/worker działają jako Deployment. Backend ma minimum 2 repliki
> i strategię aktualizacji rolling update."*

**Gdzie to jest:** [k8s/base/backend.yaml:25-31](k8s/base/backend.yaml)

```yaml
spec:
  replicas: 2
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0    # bez utraty dostępności podczas aktualizacji
```

Wszystkie 3 komponenty aplikacyjne to Deploymenty:
- [backend.yaml:16](k8s/base/backend.yaml) — backend
- [frontend.yaml](k8s/base/frontend.yaml) — frontend
- [worker.yaml](k8s/base/worker.yaml) — worker

**Demo:**

```powershell
kubectl -n notes-dev get deploy
# backend READY 2/2
kubectl -n notes-dev rollout restart deployment/backend
kubectl -n notes-dev rollout status  deployment/backend
# Widać: jeden pod nowy startuje, jeden stary zostaje aktywny aż nowy jest Ready.
```

---

### A3. Baza jako StatefulSet z PVC — 12% (4.8 pkt)

> *„Baza danych działa jako StatefulSet albo przez jasno uzasadniony zasób
> zapewniający trwałość. Musi używać PersistentVolumeClaim."*

**Gdzie to jest:** [k8s/base/postgres-statefulset.yaml:15-92](k8s/base/postgres-statefulset.yaml)

Kluczowe linijki:
- **linia 16**: `kind: StatefulSet`
- **linia 22**: `serviceName: postgres` (powiązany z headless Service z `clusterIP: None`)
- **linia 85-92**: `volumeClaimTemplates` tworzy PVC dla każdego poda

**Demo:**

```powershell
kubectl -n notes-dev get statefulset
kubectl -n notes-dev get pvc
# data-postgres-0  Bound  ...  1Gi  RWO
kubectl -n notes-dev describe pod postgres-0 | findstr "Volume Claim"
```

---

### A4. Service wewnątrz, Ingress na zewnątrz — 10% (4.0 pkt)

> *„Komunikacja wewnętrzna odbywa się przez Service. Ruch zewnętrzny przechodzi
> przez Ingress. Baza danych, cache i worker nie są wystawione na zewnątrz."*

**Gdzie to jest:**

| Komponent | Typ Service | Wystawiony przez Ingress? |
|---|---|---|
| backend | ClusterIP | tak (`/api/*`) |
| frontend | ClusterIP | tak (`/`) |
| postgres | ClusterIP (`None` — headless) | **nie** |
| redis | ClusterIP | **nie** |
| worker | brak Service'u | **nie** |

Ingress: [k8s/base/ingress.yaml](k8s/base/ingress.yaml) — rozróżnia ścieżki:
- `/api(/|$)(.*)` → `backend:8000` (rewrite na `/$2`)
- `/` → `frontend:80`

**Demo:**

```powershell
kubectl -n notes-dev get svc
# wszystkie TYPE = ClusterIP, brak NodePort/LoadBalancer
kubectl -n notes-dev get ingress
# pokazuje tylko frontend i backend, nie Postgres/Redis

# Dowód: z zewnątrz Postgres jest niedostępny
curl.exe -H "Host: notes.dev.local" http://localhost/postgres   # 404 (nie ma takiej trasy)
```

Pokaż w [ingress.yaml](k8s/base/ingress.yaml), że nie ma reguły dla bazy/cache/workera.

---

### A5. ConfigMap + Secret — 8% (3.2 pkt)

> *„Konfiguracja niepoufna jest w ConfigMap, a dane poufne w Secret. Hasła
> i tokeny nie mogą być zapisane jawnie w kodzie aplikacji."*

**Gdzie to jest:**
- [k8s/base/configmap.yaml](k8s/base/configmap.yaml) — `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `REDIS_HOST`, `REDIS_PORT`, `LOG_LEVEL`
- [k8s/base/secret.yaml](k8s/base/secret.yaml) — `POSTGRES_USER`, `POSTGRES_PASSWORD`

Wszystkie podsy konsumują to przez `envFrom` (przykład: [backend.yaml:76-80](k8s/base/backend.yaml)):

```yaml
envFrom:
  - configMapRef:
      name: notes-config
  - secretRef:
      name: notes-secret
```

W kodzie aplikacji ([app/database.py:7-12](backend/app/database.py)) wszystkie
wartości są **wyłącznie** z `os.environ` — brak hard-coded haseł.

**Demo:**

```powershell
kubectl -n notes-dev get cm notes-config -o yaml
kubectl -n notes-dev get secret notes-secret -o yaml
# Sekret jest zakodowany base64

# Dowód że aplikacja używa wartości ze środowiska:
kubectl -n notes-dev exec deploy/backend -- env | findstr "POSTGRES_\|REDIS_"
```

Pokaż też że żadnych haseł nie ma w kodzie:

```powershell
findstr /S /I "password" backend\app\*.py
# Tylko nazwy zmiennych środowiskowych
```

---

### A6. Sondy + limity zasobów — 10% (4.0 pkt)

> *„Główne kontenery mają readinessProbe i livenessProbe oraz ustawione
> resources.requests i resources.limits."*

**Gdzie to jest:** w **każdym** Deploymencie/StatefulSecie. Przykład backendu
([backend.yaml:81-103](k8s/base/backend.yaml)):

```yaml
readinessProbe:
  httpGet: { path: /ready,  port: 8000 }
  initialDelaySeconds: 5
  periodSeconds: 5
livenessProbe:
  httpGet: { path: /health, port: 8000 }
  initialDelaySeconds: 15
  periodSeconds: 10
resources:
  requests: { cpu: "50m",  memory: "128Mi" }
  limits:   { cpu: "500m", memory: "384Mi" }
```

Postgres używa sond exec z `pg_isready` ([postgres-statefulset.yaml:64-73](k8s/base/postgres-statefulset.yaml)),
Redis sond TCP ([redis.yaml:43-50](k8s/base/redis.yaml)), worker sond exec na
połączenie z Redis ([worker.yaml:31-44](k8s/base/worker.yaml)).

**Demo:**

```powershell
kubectl -n notes-dev describe pod -l app.kubernetes.io/name=backend | findstr "Liveness Readiness Limits Requests"
```

Pokaż że **każdy** kontener ma sondy + limity.

---

### A7. Non-root + securityContext + Job migracji — 8% (3.2 pkt)

> *„Kontenery aplikacyjne działają jako non-root i mają podstawowy
> securityContext. Projekt używa initContainer albo Job do migracji bazy."*

**Non-root + securityContext** — przykład [backend.yaml:44-48](k8s/base/backend.yaml):

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
  fsGroup: 10001
```

oraz na poziomie kontenera ([backend.yaml:104-108](k8s/base/backend.yaml)):

```yaml
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
  readOnlyRootFilesystem: true
```

Również w Dockerfile ([backend/Dockerfile:18-22](backend/Dockerfile)):

```dockerfile
RUN groupadd --system app --gid 10001 && useradd --system app --uid 10001 ...
USER 10001:10001
```

**Job migracji** — [k8s/base/migration-job.yaml](k8s/base/migration-job.yaml):
- linia 20-40: **initContainer** `wait-for-postgres` — czeka aż baza odpowie
- linia 41-67: kontener `migrate` — odpala `Base.metadata.create_all()` (SQLAlchemy)

Backend ma ten sam initContainer ([backend.yaml:49-69](k8s/base/backend.yaml)),
więc nawet bez Joba nie wystartuje przed bazą.

**Demo:**

```powershell
# Non-root:
kubectl -n notes-dev exec deploy/backend -- id
# uid=10001 gid=10001

# Job migracji się wykonał:
kubectl -n notes-dev get jobs
# notes-migrate  1/1  Completed
kubectl -n notes-dev logs job/notes-migrate -c migrate
# "schema ensured"
```

---

### A8. Workflow CI/CD — 10% (4.0 pkt)

> *„Repozytorium zawiera workflow, który buduje obraz, uruchamia testy lub
> podstawową walidację, publikuje obraz do rejestru i wykonuje deploy przez
> kubectl, Helm albo Kustomize. Workflow sprawdza rollout po wdrożeniu."*

**Gdzie to jest:** [.github/workflows/ci-cd.yml](.github/workflows/ci-cd.yml) —
trzy joby:

| Job | Linie | Co robi |
|---|---|---|
| `test` | [17-39](.github/workflows/ci-cd.yml) | `pytest` na backendzie (6 testów) |
| `build-and-push` | [41-92](.github/workflows/ci-cd.yml) | Buduje 3 obrazy (backend, worker, frontend), publikuje do `ghcr.io` |
| `deploy-kind` | [94-159](.github/workflows/ci-cd.yml) | Tworzy klaster kind w runnerze, instaluje Ingress, `kubectl apply -k k8s/overlays/dev`, `kubectl rollout status` na każdym komponencie + smoke test API |

Sprawdzenie rolloutu — linie [136-144](.github/workflows/ci-cd.yml):

```bash
kubectl rollout status statefulset/postgres --timeout=180s
kubectl wait --for=condition=complete job/notes-migrate --timeout=180s
kubectl rollout status deployment/backend  --timeout=180s
# itd.
```

Smoke test — linie [146-156](.github/workflows/ci-cd.yml):

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/notes -d '{...}'
curl http://localhost:8000/notes
curl http://localhost:8000/metrics
```

**Demo:** Pokaż plik workflow + (jeśli wypchnęliście do GitHub) link do
zielonego runa w zakładce Actions.

---

## Część B — Rzeczy dodatkowe (10%)

### B1. NetworkPolicy — 2.5% (1.0 pkt)

> *„Projekt definiuje NetworkPolicy, które ograniczają ruch między podami."*

**Gdzie to jest:** [k8s/base/networkpolicy.yaml](k8s/base/networkpolicy.yaml) —
5 polityk:

| Polityka | Reguła |
|---|---|
| `default-deny` (linie 1-7) | Domyślnie żaden pod nie przyjmuje ruchu |
| `allow-postgres-from-backend-and-worker` (linie 9-29) | Postgres przyjmuje tylko od backendu i Joba migracji |
| `allow-redis-from-backend-and-worker` (linie 31-51) | Redis przyjmuje tylko od backendu i workera |
| `allow-backend-from-frontend-and-ingress` (linie 53-71) | Backend przyjmuje od frontendu i z namespace Ingressa |
| `allow-frontend-from-ingress` (linie 73-89) | Frontend przyjmuje tylko z Ingressa |

**Demo:**

```powershell
kubectl -n notes-dev get networkpolicy
# 5 polityk

# Pod testowy NIE dochodzi do Postgresa:
kubectl -n notes-dev run nettest --rm -i --restart=Never --image=busybox -- `
  sh -c "nc -zv postgres 5432 -w 3 || echo BLOCKED"
# BLOCKED

# Backend DALEJ dochodzi:
kubectl -n notes-dev exec deploy/backend -- `
  python -c "import socket; s=socket.socket(); s.connect(('postgres',5432)); print('OK')"
# OK
```

---

### B2. PodDisruptionBudget — 2.5% (1.0 pkt)

> *„Dla backendu dodano PodDisruptionBudget, który chroni minimalną dostępność
> replik podczas aktualizacji lub prac utrzymaniowych klastra."*

**Gdzie to jest:** [k8s/base/pdb.yaml](k8s/base/pdb.yaml)

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: backend
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: backend
```

W overlay prod ([k8s/overlays/prod/kustomization.yaml](k8s/overlays/prod/kustomization.yaml))
patchowany na `minAvailable: 2`.

**Demo:**

```powershell
kubectl -n notes-dev get pdb
# backend  MIN AVAILABLE=1  ALLOWED DISRUPTIONS=1
```

---

### B3. Kustomize + 2 środowiska — 2.5% (1.0 pkt)

> *„Projekt używa Helm albo Kustomize do parametryzacji manifestów i obsługuje
> minimum dwa środowiska."*

**Gdzie to jest:**

```
k8s/
├── base/                    # wspólne manifesty
│   └── kustomization.yaml
└── overlays/
    ├── dev/                 # 2 repliki backendu, host notes.dev.local
    │   └── kustomization.yaml
    └── prod/                # 3 repliki backendu, PDB minAvailable=2, host notes.prod.local
        └── kustomization.yaml
```

[overlays/dev/kustomization.yaml](k8s/overlays/dev/kustomization.yaml):
- `namespace: notes-dev`
- `images:` mapowanie ghcr.io → lokalne tagi (do działania na kind)
- patch: backend `replicas: 2`, host `notes.dev.local`

[overlays/prod/kustomization.yaml](k8s/overlays/prod/kustomization.yaml):
- `namespace: notes-prod`
- patch: backend `replicas: 3`, większe limity zasobów, PDB `minAvailable: 2`, host `notes.prod.local`

**Demo:**

```powershell
kubectl kustomize k8s/overlays/dev  | findstr "replicas: \|minAvailable: \|host:"
# replicas: 2 / minAvailable: 1 / host: notes.dev.local
kubectl kustomize k8s/overlays/prod | findstr "replicas: \|minAvailable: \|host:"
# replicas: 3 / minAvailable: 2 / host: notes.prod.local
```

---

### B4. Metryki Prometheus — 2.5% (1.0 pkt)

> *„Aplikacja udostępnia /metrics, adnotacje dla Prometheusa albo inną prostą
> formę obserwowalności."*

**Gdzie to jest:**

- Endpoint `/metrics`: [backend/app/main.py:67-69](backend/app/main.py)
  ```python
  @app.get("/metrics")
  def metrics() -> Response:
      return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
  ```
- Liczniki: [backend/app/main.py:26-28](backend/app/main.py) — `notes_created_total`, `notes_deleted_total`, `notes_read_total`
- Adnotacje Prometheusa: [k8s/base/backend.yaml:21-24](k8s/base/backend.yaml) i [39-42](k8s/base/backend.yaml):
  ```yaml
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "8000"
    prometheus.io/path: "/metrics"
  ```

**Demo:**

```powershell
curl.exe -sH "Host: notes.dev.local" http://localhost/api/metrics | Select-String notes_
# notes_created_total 2.0
# notes_read_total 5.0

kubectl -n notes-dev get deploy backend -o jsonpath='{.metadata.annotations}'
# {"prometheus.io/path":"/metrics","prometheus.io/port":"8000","prometheus.io/scrape":"true"}
```

---

## Część C — Wymagania specyficzne (20%)

### C1. Aplikacja z zasobem biznesowym + /health / /ready — 10% (4.0 pkt)

> *„Aplikacja ma jeden główny zasób biznesowy i obsługuje co najmniej dodanie
> danych, odczyt danych oraz endpoint /health lub /ready."*

**Zasób biznesowy:** `note` (notatka) — pola `id`, `title`, `content`, `created_at`.

**Gdzie to jest:**
- Model bazodanowy: [backend/app/models.py](backend/app/models.py)
- Endpointy: [backend/app/main.py](backend/app/main.py):
  - `GET /health`  ([linia 52-54](backend/app/main.py)) — zawsze 200, używany przez livenessProbe
  - `GET /ready`   ([linia 57-64](backend/app/main.py)) — sprawdza Postgres + Redis, używany przez readinessProbe
  - `GET /notes`   ([linia 72-75](backend/app/main.py)) — lista wszystkich
  - `GET /notes/{id}` ([linia 78-84](backend/app/main.py)) — pobranie jednej
  - `POST /notes`  ([linia 87-98](backend/app/main.py)) — dodanie
  - `DELETE /notes/{id}` ([linia 101-113](backend/app/main.py)) — usunięcie

**Demo (zachowaj id zwrócone przez POST do następnej sekcji!):**

```powershell
$h = "Host: notes.dev.local"

# /health i /ready:
curl.exe -sH $h http://localhost/api/health
# {"status":"ok"}
curl.exe -sH $h http://localhost/api/ready
# {"status":"ready"}

# Dodanie notatki (z pliku, żeby nie walczyć z escapowaniem JSON-a w PS):
'{"title":"obrona","content":"projekt akademicki"}' | Out-File -Encoding ascii note.json
curl.exe -sH $h -H "Content-Type: application/json" --data-binary "@note.json" `
  http://localhost/api/notes
# {"id":3,"title":"obrona","content":"projekt akademicki","created_at":"..."}

# Odczyt:
curl.exe -sH $h http://localhost/api/notes
# [{...}, {...}, {"id":3,...}]
```

---

### C2. Trwałość danych po restarcie poda — 5% (2.0 pkt)

> *„Dane aplikacji są zapisywane w bazie danych działającej w Kubernetes
> i pozostają dostępne po restarcie poda bazy."*

**Skąd trwałość:** PVC z [postgres-statefulset.yaml:85-92](k8s/base/postgres-statefulset.yaml)
— `1Gi` montowany na `/var/lib/postgresql/data`. PVC przeżywa usunięcie poda.

**Demo (kluczowy moment obrony):**

```powershell
$h = "Host: notes.dev.local"

# 1. Dodaj notatkę-kontrolkę
'{"title":"przed-restartem","content":"czy przezyje?"}' | Out-File -Encoding ascii note.json
curl.exe -sH $h -H "Content-Type: application/json" --data-binary "@note.json" `
  http://localhost/api/notes
# Zapamiętaj id, np. 4

# 2. Pokaż listę PRZED:
curl.exe -sH $h http://localhost/api/notes
# Notatka "przed-restartem" jest w liście

# 3. ZABIJ POD BAZY:
kubectl -n notes-dev delete pod postgres-0

# 4. Poczekaj aż wstanie (StatefulSet odtwarza pod, PVC zostaje):
kubectl -n notes-dev rollout status statefulset/postgres --timeout=120s

# 5. ODCZYTAJ — notatka nadal istnieje:
curl.exe -sH $h http://localhost/api/notes
# Lista zawiera "przed-restartem" — DANE PRZEŻYŁY restart poda.
```

Możesz też pokazać, że PVC żyje niezależnie od poda:

```powershell
kubectl -n notes-dev get pvc
# data-postgres-0  Bound  ...  1Gi
```

---

### C3. Dodatkowy komponent — Redis + worker — 5% (2.0 pkt)

> *„Projekt zawiera dodatkowy komponent architektury, np. Redis, RabbitMQ albo
> worker. Musi być prosty dowód działania w CHECKLIST.md."*

**W projekcie są DWA dodatkowe komponenty:** Redis (broker pub/sub) oraz worker
(subskrybent).

**Gdzie to jest:**
- Redis: [k8s/base/redis.yaml](k8s/base/redis.yaml)
- Worker (kod): [backend/app/worker.py](backend/app/worker.py)
- Worker (Dockerfile): [backend/Dockerfile.worker](backend/Dockerfile.worker)
- Worker (deployment): [k8s/base/worker.yaml](k8s/base/worker.yaml)

**Co robią:**
1. Backend po każdym `POST /notes` publikuje wiadomość `created:{id}:{title}` na
   kanał `notes-events` w Redis ([app/main.py:95](backend/app/main.py))
2. Worker subskrybuje ten kanał ([app/worker.py:24-25](backend/app/worker.py))
3. Worker zapisuje każde zdarzenie do listy `notes-events-log` w Redis i loguje
   na stdout ([app/worker.py:30-34](backend/app/worker.py))

**Demo (dowód działania):**

```powershell
$h = "Host: notes.dev.local"

# 1. Pokaż że worker działa i subskrybuje:
kubectl -n notes-dev logs deployment/worker --tail=5
# "worker subscribed to channel 'notes-events'"

# 2. Dodaj notatkę:
'{"title":"trigger","content":"test workera"}' | Out-File -Encoding ascii note.json
curl.exe -sH $h -H "Content-Type: application/json" --data-binary "@note.json" `
  http://localhost/api/notes

# 3. Worker odebrał event:
kubectl -n notes-dev logs deployment/worker --tail=5
# "processed event: created:X:trigger"

# 4. Lista zdarzeń w Redis:
kubectl -n notes-dev exec deploy/redis -- redis-cli LRANGE notes-events-log 0 -1
# 1) "created:X:trigger"
# 2) "created:Y:..."
# ...
```

---

## Podsumowanie punktacji

| Część | Wymaganie | Waga | Pliki |
|---|---|---|---|
| A1 | Komplet zasobów | 12% | [k8s/base/](k8s/base/) |
| A2 | Backend 2 repliki + RU | 10% | [backend.yaml:25-31](k8s/base/backend.yaml) |
| A3 | StatefulSet + PVC | 12% | [postgres-statefulset.yaml](k8s/base/postgres-statefulset.yaml) |
| A4 | Service + Ingress | 10% | [ingress.yaml](k8s/base/ingress.yaml) |
| A5 | ConfigMap + Secret | 8% | [configmap.yaml](k8s/base/configmap.yaml), [secret.yaml](k8s/base/secret.yaml) |
| A6 | Sondy + limity | 10% | wszystkie deploymenty |
| A7 | Non-root + Job migracji | 8% | [migration-job.yaml](k8s/base/migration-job.yaml) |
| A8 | CI/CD workflow | 10% | [.github/workflows/ci-cd.yml](.github/workflows/ci-cd.yml) |
| B1 | NetworkPolicy | 2.5% | [networkpolicy.yaml](k8s/base/networkpolicy.yaml) |
| B2 | PodDisruptionBudget | 2.5% | [pdb.yaml](k8s/base/pdb.yaml) |
| B3 | Kustomize + 2 środowiska | 2.5% | [k8s/overlays/](k8s/overlays/) |
| B4 | Metryki Prometheus | 2.5% | [app/main.py:67](backend/app/main.py), [backend.yaml:21-24](k8s/base/backend.yaml) |
| C1 | Zasób biznesowy + /health | 10% | [app/main.py](backend/app/main.py) |
| C2 | Trwałość danych | 5% | PVC w StatefulSet |
| C3 | Redis + worker | 5% | [worker.py](backend/app/worker.py), [worker.yaml](k8s/base/worker.yaml) |
| | **RAZEM** | **100%** | |

---

## Awaryjne — jeśli coś nie działa podczas obrony

**Klaster nie odpowiada:**
```powershell
kubectl cluster-info --context kind-notes
# Jeśli błąd: docker ps | findstr notes-control-plane (sprawdź czy działa)
```

**Pody w stanie `Pending`/`CrashLoop`:**
```powershell
kubectl -n notes-dev describe pod <nazwa> | Select-Object -Last 30
kubectl -n notes-dev logs <nazwa> --previous   # logi poprzedniego crash-a
```

**Zacznij od zera (~3 min):**
```powershell
kind delete cluster --name notes
.\bootstrap.ps1
```

**Wszystkie potrzebne demo-komendy w jednym pliku** — gdyby trzeba było szybko
pokazać kilka rzeczy:

```powershell
# Pełen przegląd zasobów:
kubectl -n notes-dev get all,ingress,cm,secret,pvc,networkpolicy,pdb

# 2 repliki backendu, sondy, limity:
kubectl -n notes-dev describe deploy backend | Select-String "Replicas|Strategy|Liveness|Readiness|Limits|Requests"

# Non-root:
kubectl -n notes-dev exec deploy/backend -- id

# Test API:
curl.exe -sH "Host: notes.dev.local" http://localhost/api/health
curl.exe -sH "Host: notes.dev.local" http://localhost/api/notes

# Metryki:
curl.exe -sH "Host: notes.dev.local" http://localhost/api/metrics | findstr notes_

# Worker:
kubectl -n notes-dev logs deployment/worker --tail=10
kubectl -n notes-dev exec deploy/redis -- redis-cli LRANGE notes-events-log 0 -1
```
