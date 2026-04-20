"""
AXON Integration Tests
========================
Opt-in tests that exercise AXON handlers / providers against REAL
external systems (AWS, Kubernetes, Docker, Terraform, Vault, etc.).

Each test module is gated by an environment variable so that the
default `pytest` run skips them entirely.  CI pipelines with real
credentials can enable per-provider suites by exporting the flags
documented in README.md.

Gating conventions (env var ⇒ suite enabled):
    AXON_IT_DRY_RUN            — always-on smoke harness (no external IO)
    AXON_IT_DOCKER             — real Docker daemon
    AXON_IT_TERRAFORM          — real `terraform` binary in PATH
    AXON_IT_AWS                — real AWS credentials (profile / env)
    AXON_IT_KUBERNETES         — real kubeconfig / in-cluster SA
    AXON_IT_VAULT              — VAULT_ADDR + VAULT_TOKEN set
    AXON_IT_AZURE_KEYVAULT     — AZURE_KEYVAULT_URL + identity resolvable
    AXON_IT_PQ                 — liboqs-python installed
    AXON_IT_FHE                — tenseal installed

Run a targeted suite (e.g. Docker):
    AXON_IT_DOCKER=1 pytest tests/integration/test_integration_docker.py
"""
