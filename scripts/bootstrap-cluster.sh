#!/usr/bin/env bash
# Phase 1 cluster bootstrap (run once on a machine with kind, helm, kubectl).
set -euo pipefail

kind create cluster --name platform || true
kubectl create namespace demo-app --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace observability --dry-run=client -o yaml | kubectl apply -f -

helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

if helm upgrade --install otel-collector open-telemetry/opentelemetry-collector \
  -n observability --create-namespace \
  -f observability/otel/otel-collector-values.yaml; then
  echo "OTel Collector installed via Helm."
else
  kubectl apply -f observability/otel/otel-collector-rbac.yaml
  kubectl apply -f observability/otel/otel-collector.yaml
  kubectl apply -f observability/otel/otel-collector-deployment.yaml
fi

helm upgrade --install kube-prometheus prometheus-community/kube-prometheus-stack -n observability
helm upgrade --install loki grafana/loki-stack -n observability
helm upgrade --install tempo grafana/tempo -n observability -f observability/tempo-values.yaml

kubectl apply -f observability/prometheus/incidentlens-rules.yaml
kubectl apply -f observability/prometheus/alertmanager-config.yaml
kubectl apply -f apps/demo-app/k8s/demo-app.yaml
kubectl apply -f services/correlator/k8s/

echo "Port-forward Grafana: kubectl port-forward -n observability svc/kube-prometheus-grafana 3000:80"
