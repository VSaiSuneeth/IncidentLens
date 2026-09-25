"""Parse repository Kubernetes and observability manifests in CI.

This is intentionally schema-light so it remains usable without a live cluster
or third-party validators. Kubernetes performs the authoritative server-side
validation during deployment.
"""

from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIRS = (
    ROOT / "apps" / "demo-app" / "k8s",
    ROOT / "services" / "correlator" / "k8s",
    ROOT / "observability",
    ROOT / "gitops",
)


def manifest_files() -> list[Path]:
    paths: list[Path] = []
    for directory in MANIFEST_DIRS:
        paths.extend(path for path in directory.rglob("*.yaml") if "values" not in path.name)
        paths.extend(path for path in directory.rglob("*.yml") if "values" not in path.name)
    return sorted(set(paths))


def main() -> int:
    failures: list[str] = []
    checked = 0
    for path in manifest_files():
        try:
            documents = [document for document in yaml.safe_load_all(path.read_text()) if document]
        except yaml.YAMLError as exc:
            failures.append(f"{path.relative_to(ROOT)}: {exc}")
            continue
        for document in documents:
            checked += 1
            if not isinstance(document, dict) or "apiVersion" not in document or "kind" not in document:
                failures.append(f"{path.relative_to(ROOT)}: manifest lacks apiVersion or kind")

    if failures:
        print("Manifest validation failed:", *failures, sep="\n")
        return 1
    print(f"Validated {checked} Kubernetes/observability manifest documents.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
