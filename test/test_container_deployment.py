from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_dockerfile_uses_pinned_python_and_non_root_runtime():
    dockerfile = read("Dockerfile")

    assert re.search(r"^FROM python:3\.12\.\d+-alpine\d+\.\d+$", dockerfile, re.MULTILINE)
    assert "pip install --no-cache-dir --require-hashes --requirement requirements.lock" in dockerfile
    assert re.search(r"^USER (?!root$)\S+$", dockerfile, re.MULTILINE)
    assert "MAINTAINER" not in dockerfile
    assert not re.search(r"^ADD\s", dockerfile, re.MULTILINE)
    assert "requirements-dev.txt" not in dockerfile


def test_dockerfile_copies_only_runtime_files_and_has_offline_healthcheck():
    dockerfile = read("Dockerfile")

    copied_sources = re.findall(r"^COPY\s+(?:--\S+\s+)*(\S+)", dockerfile, re.MULTILINE)
    assert set(copied_sources) == {
        "requirements.lock",
        "bot.py",
        "ASFConnector.py",
        "logger.py",
        "IPCProtocol/",
    }
    assert "HEALTHCHECK" in dockerfile
    assert "/proc/1/cmdline" in dockerfile
    assert "api.telegram.org" not in dockerfile
    assert "ASF_IPC_PASSWORD" not in dockerfile


def test_runtime_lock_is_fully_pinned_and_hashed_without_test_dependencies():
    lock = read("requirements.lock")
    requirement_lines = [
        line for line in lock.splitlines()
        if line and not line.startswith(("#", " ", "--"))
    ]

    assert requirement_lines
    assert all("==" in line for line in requirement_lines)
    assert lock.count("--hash=sha256:") >= len(requirement_lines)
    assert "pytelegrambotapi==4.36.1" in lock.lower()
    assert "requests==2.34.2" in lock.lower()
    assert "pytest" not in lock.lower()


def test_dockerignore_excludes_development_and_secret_material():
    ignored = set(read(".dockerignore").splitlines())

    assert {
        ".git", ".worktrees", ".venv", "__pycache__", ".pytest_cache",
        "test", "docs", ".env", "*.env", "secrets", "secrets/",
        "*.secret", "*.key", "credentials.json", "*credentials*.json",
        "*.pem", "*.p12", "*.pfx", ".netrc", "id_rsa", "id_ed25519",
    } <= ignored


def test_readme_contains_complete_compose_configuration():
    readme = read("README.md")

    assert not (ROOT / ("compose" + ".example.yml")).exists()
    assert "image: ghcr.io/zieglar/asfbot:latest" in readme
    assert "TELEGRAM_ALLOWED_USER_ID: ${TELEGRAM_ALLOWED_USER_ID" in readme
    assert "TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN" in readme
    assert "ASF_IPC_HOST: asf" in readme
    assert 'ASF_IPC_PORT: "1242"' in readme
    assert "ASF_IPC_PASSWORD: ${ASF_IPC_PASSWORD" in readme
    assert "ASF_IPC_CONNECT_TIMEOUT: ${ASF_IPC_CONNECT_TIMEOUT:-3.05}" in readme
    assert "ASF_IPC_READ_TIMEOUT: ${ASF_IPC_READ_TIMEOUT:-15}" in readme
    assert "restart: unless-stopped" in readme
    assert "depends_on:" in readme
    assert "justarchi/archisteamfarm:6.3.9.6" in readme
    assert "1242:1242" not in readme


def test_readme_documents_current_operation_and_migration():
    readme = read("README.md")

    for command in ("/help", "/ping", "/status", "/pause", "/resume", "/start", "/stop", "/redeem"):
        assert command in readme
    for setting in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_ID",
        "ASF_IPC_HOST",
        "ASF_IPC_PORT",
        "ASF_IPC_PASSWORD",
        "ASF_IPC_CONNECT_TIMEOUT",
        "ASF_IPC_READ_TIMEOUT",
    ):
        assert setting in readme
    assert "3.05" in readme
    assert "15" in readme
    assert "TELEGRAM_USER_ALIAS" in readme
    assert "ARM64" in readme
    assert "Mac" + " mini" not in readme
    assert "~/" + "Code/" not in readme
    assert "docker build" in readme
    assert "uv pip compile" in readme
    assert "6.3.9.6" in readme
    assert "ghcr.io/zieglar/asfbot" in readme
    assert "zieglar/asfbot" in readme
    assert "linux/amd64" in readme
    assert "linux/arm64" in readme
    assert "docker compose pull asfbot" in readme


def test_registry_workflow_publishes_secure_multi_arch_images():
    workflow = read(".github/workflows/docker.yml")

    assert "ghcr.io/${{ github.repository_owner }}/asfbot" in workflow
    assert "zieglar/asfbot" in workflow
    assert "linux/amd64,linux/arm64" in workflow
    assert "linux/arm/v7" not in workflow
    assert "secrets.DOCKERHUB_USERNAME" in workflow
    assert "secrets.DOCKERHUB_TOKEN" in workflow
    assert "secrets.DOCKER_PASSWORD" not in workflow
    assert "push: ${{ github.event_name != 'pull_request' }}" in workflow
    assert "type=raw,value=latest,enable={{is_default_branch}}" in workflow
    assert "type=semver,pattern={{version}}" in workflow
    assert "cache-from: type=gha" in workflow
    assert "cache-to: type=gha,mode=max" in workflow
    assert "provenance: mode=max" in workflow
    assert "sbom: true" in workflow
    assert "@v2" not in workflow
    assert "@v3" not in workflow


def test_repeatable_container_gate_checks_compose_build_user_and_healthcheck():
    gate = read("scripts/verify-container.sh")

    assert "compose" + ".example.yml" not in gate
    assert "docker build" in gate
    assert "docker image inspect" in gate
    assert "Config.User" in gate
    assert "Config.Healthcheck" in gate
