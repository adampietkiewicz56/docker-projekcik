# bootstrap.ps1 — uruchamia caly projekt od zera na lokalnym kind.
# Uzycie:  .\bootstrap.ps1
# Wymaga:  Docker Desktop dziala, kubectl w PATH, kind w PATH (lub w $HOME\bin)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:Path += ";$env:USERPROFILE\bin"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# 1) Klaster kind ----------------------------------------------------------
Step "1/6  Sprawdzam klaster kind 'notes'"
$clusters = & kind get clusters 2>$null
if ($clusters -notcontains 'notes') {
    Step "    Tworze klaster (config: kind-config.yaml)"
    kind create cluster --name notes --config kind-config.yaml
} else {
    Write-Host "    Klaster 'notes' juz istnieje, pomijam tworzenie."
}
kubectl config use-context kind-notes | Out-Null

# 2) Ingress controller ----------------------------------------------------
Step "2/6  Instaluje ingress-nginx"
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.2/deploy/static/provider/kind/deploy.yaml | Out-Null
kubectl wait --namespace ingress-nginx --for=condition=ready pod `
    --selector=app.kubernetes.io/component=controller --timeout=180s

# 3) Build 3 obrazow -------------------------------------------------------
Step "3/6  Buduje obrazy Docker"
docker build -t notes-backend:dev  ./backend
docker build -t notes-worker:dev   -f ./backend/Dockerfile.worker ./backend
docker build -t notes-frontend:dev ./frontend

# 4) Load do klastra -------------------------------------------------------
Step "4/6  Laduje obrazy do kind"
kind load docker-image notes-backend:dev notes-worker:dev notes-frontend:dev --name notes

# 5) Deploy ----------------------------------------------------------------
Step "5/6  Deploy overlay dev"
kubectl apply -k k8s/overlays/dev

# 6) Wait for rollout ------------------------------------------------------
Step "6/6  Czekam na gotowosc komponentow"
kubectl -n notes-dev rollout status statefulset/postgres --timeout=180s
kubectl -n notes-dev wait --for=condition=complete job/notes-migrate --timeout=180s
kubectl -n notes-dev rollout status deployment/redis    --timeout=120s
kubectl -n notes-dev rollout status deployment/backend  --timeout=180s
kubectl -n notes-dev rollout status deployment/worker   --timeout=120s
kubectl -n notes-dev rollout status deployment/frontend --timeout=120s

# Smoke test ---------------------------------------------------------------
Step "Smoke test API przez Ingress"
$h = @{Host = "notes.dev.local"}
$health = curl.exe -sH "Host: notes.dev.local" http://localhost/api/health
Write-Host "    /api/health -> $health"
Write-Host ""
Write-Host "GOTOWE!" -ForegroundColor Green
Write-Host "  Aplikacja:   http://notes.dev.local/   (dodaj do C:\Windows\System32\drivers\etc\hosts: '127.0.0.1 notes.dev.local')"
Write-Host "  Lub przez curl: curl -H 'Host: notes.dev.local' http://localhost/api/notes"
Write-Host "  Status:      kubectl -n notes-dev get all"
Write-Host "  Wylacz:      kind delete cluster --name notes"
