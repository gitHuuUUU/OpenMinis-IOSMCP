#!/usr/bin/env python3
"""Install and verify the pinned REA CLI in the Minis Alpine guest.

The script deliberately separates npm/package/MCP availability from REA's
analysis-engine readiness. Missing commercial or optional engines are reported
by `doctor`; they are never installed or represented as ready here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
import re
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

REA_VERSION = "6.4.0"
PREFIX = Path("/opt/minis-rea")
WRAPPER = Path("/usr/local/bin/rea")
SKILLS_ROOT = Path("/var/minis/skills")
REA_SKILL_SOURCE = Path("skills/reverse-engineer-anything")
REA_SKILL_DEST = SKILLS_ROOT / "rea-reverse-engineer-anything"
MCP_PROTOCOL_VERSION = "2025-06-18"
LOG_PATH = Path(os.environ.get("MINIS_REA_LOG_PATH", "/var/log/minis-rea-install.log"))
MCP_TIMEOUT_SECONDS = 120
DOCTOR_TIMEOUT_SECONDS = 60
DEEP_DOCTOR_TIMEOUT_SECONDS = 180
NPM_TIMEOUT_SECONDS = 900
DOCTOR_CACHE_TTL_SECONDS = 300
CLI_VERSION_TIMEOUT_MAX_SECONDS = 270
MANAGED_WRAPPER_MARKER = "# minis-managed-rea-wrapper-v1"
STAGE_MARKER = ".minis-rea-stage.json"


class InstallError(RuntimeError):
    pass


def _logger() -> logging.Logger:
    logger = logging.getLogger("minis-rea-install")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        os.chmod(LOG_PATH, 0o600)
    except OSError:
        handler = logging.FileHandler("/tmp/minis-rea-install.log", encoding="utf-8")
        os.chmod("/tmp/minis-rea-install.log", 0o600)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


LOG = _logger()


def _run(args: list[str], *, timeout: int, cwd: Path | None = None,
         check: bool = True, log_output: bool = True) -> subprocess.CompletedProcess[str]:
    LOG.info("run: %s", " ".join(args))
    try:
        result = subprocess.run(
            args, cwd=str(cwd) if cwd else None, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        LOG.error("command timed out after %ss: %s", timeout, args[0])
        raise InstallError(f"{args[0]} timed out after {timeout}s") from exc
    if log_output and result.stdout:
        LOG.info("stdout(%s): %s", args[0], result.stdout[-4000:].strip())
    if log_output and result.stderr:
        LOG.info("stderr(%s): %s", args[0], result.stderr[-4000:].strip())
    if check and result.returncode != 0:
        raise InstallError(f"{args[0]} exited {result.returncode}; see {LOG_PATH}")
    return result


def _node_and_npm() -> tuple[str, str, str]:
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        raise InstallError("Node.js and npm must be installed in the Alpine guest")
    version = _run([node, "--version"], timeout=10).stdout.strip().lstrip("v")
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", version)
    if not match:
        raise InstallError(f"Cannot parse Node.js version: {version!r}")
    major, minor = int(match.group(1)), int(match.group(2))
    if not _node_version_supported(major, minor):
        raise InstallError(f"REA 6.4.0 requires Node ^22.19, ^24.11, or >=26; found {version}")
    return node, npm, version


def _node_version_supported(major: int, minor: int) -> bool:
    return (major == 22 and minor >= 19) or (major == 24 and minor >= 11) or major >= 26


def _paths(prefix: Path) -> tuple[Path, Path]:
    package = prefix / "node_modules" / "rea-agents"
    entry = package / "scripts" / "rea.mjs"
    return package, entry


def _version(node: str, entry: Path, *, timeout: int | None = None) -> str:
    result = _run([node, str(entry), "--version"],
                  timeout=timeout or _adaptive_cli_timeout(entry), cwd=entry.parent.parent)
    text = (result.stdout + "\n" + result.stderr).strip()
    match = re.search(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)", text)
    if not match:
        raise InstallError("REA --version returned no parseable version")
    return match.group(1)


def _adaptive_cli_timeout(entry: Path) -> int:
    """Give cold ARM guest starts more time; scale with the shipped CLI bundle."""
    arch = platform.machine().lower()
    base = 180 if arch in {"aarch64", "arm64", "armv8l"} else 120
    try:
        bundle = entry.parent.parent / "dist"
        byte_count = sum(p.stat().st_size for p in bundle.rglob("*") if p.is_file())
    except OSError:
        byte_count = 0
    scaled = base + int((byte_count / (1024 * 1024)) * 3)
    return min(CLI_VERSION_TIMEOUT_MAX_SECONDS, max(base, scaled))


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, separators=(",", ":"), ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        _fsync_dir(path.parent)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _managed_regular_file(path: Path, root: Path) -> bool:
    try:
        root_real = root.resolve(strict=True)
        path_stat = path.lstat()
        path_real = path.resolve(strict=True)
        path_real.relative_to(root_real)
        return not path.is_symlink() and path_stat.st_mode & 0o170000 == 0o100000
    except (OSError, ValueError):
        return False


def _sha256_file(path: Path, root: Path) -> str:
    if not _managed_regular_file(path, root):
        raise InstallError(f"Managed verification input is missing, linked, or outside package root: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_fingerprint(root: Path, entry: Path, node_version: str) -> dict[str, str]:
    return {
        "nodeVersion": node_version,
        "entrySha256": _sha256_file(entry, root),
        "packageLockSha256": _sha256_file(root / "package-lock.json", root),
    }


def _doctor_cache_path(entry: Path) -> Path:
    return entry.parents[3] / ".minis-rea-doctor-cache.json"


def _read_doctor_cache(path: Path, fingerprint: dict[str, str], deep: bool) -> dict[str, Any] | None:
    try:
        if path.is_symlink() or not _managed_regular_file(path, path.parent):
            return None
        cache = json.loads(path.read_text(encoding="utf-8"))
        if cache.get("reaVersion") != REA_VERSION:
            return None
        if any(cache.get(key) != value for key, value in fingerprint.items()):
            return None
        if cache.get("deep") is not deep:
            return None
        if time.time() - float(cache.get("checkedAt", 0)) > DOCTOR_CACHE_TTL_SECONDS:
            return None
        doctor = cache.get("doctor")
        return doctor if isinstance(doctor, dict) else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _validation_cache_path(root: Path) -> Path:
    return root / ".minis-rea-validation-cache.json"


def _read_validation_cache(root: Path, entry: Path,
                           fingerprint: dict[str, str]) -> dict[str, Any] | None:
    path = _validation_cache_path(root)
    try:
        if path.is_symlink() or not _managed_regular_file(path, root):
            return None
        cache = json.loads(path.read_text(encoding="utf-8"))
        if cache.get("reaVersion") != REA_VERSION:
            return None
        if any(cache.get(key) != value for key, value in fingerprint.items()):
            return None
        if time.time() - float(cache.get("verifiedAt", 0)) > DOCTOR_CACHE_TTL_SECONDS:
            return None
        mcp = cache.get("mcp")
        if not isinstance(mcp, dict) or mcp.get("initialize") is not True or mcp.get("toolsList") is not True:
            return None
        return cache
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _write_validation_cache(root: Path, fingerprint: dict[str, str],
                            mcp: dict[str, Any], doctor: dict[str, Any]) -> dict[str, Any]:
    verified_at = time.time()
    cache = {
        "reaVersion": REA_VERSION,
        **fingerprint,
        "verifiedAt": verified_at,
        "mcp": mcp,
        "doctor": {k: v for k, v in doctor.items() if k != "cached"},
    }
    _atomic_json(_validation_cache_path(root), cache)
    return {
        "live": True,
        "cached": False,
        "verifiedAt": verified_at,
        **fingerprint,
    }


def _doctor(node: str, entry: Path, *, deep: bool = False,
            use_cache: bool = True) -> dict[str, Any]:
    node_version = _run([node, "--version"], timeout=10).stdout.strip().lstrip("v")
    cache_path = _doctor_cache_path(entry)
    package_root = entry.parents[3]
    try:
        fingerprint = _package_fingerprint(package_root, entry, node_version)
    except InstallError:
        fingerprint = {"nodeVersion": node_version}
    if use_cache:
        cached = _read_doctor_cache(cache_path, fingerprint, deep)
        if cached is not None:
            return {**cached, "cached": True}
    command = [node, str(entry), "doctor", "--format", "json"]
    if deep:
        command.append("--full-output")
    try:
        result = _run(command,
                      timeout=DEEP_DOCTOR_TIMEOUT_SECONDS if deep else DOCTOR_TIMEOUT_SECONDS,
                      cwd=entry.parent.parent, check=False, log_output=False)
    except InstallError as exc:
        return {
            "completed": False,
            "healthy": False,
            "environmentHealthy": False,
            "backendStatus": "incomplete_or_unavailable",
            "error": str(exc),
            "cached": False,
        }
    try:
        envelope = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        LOG.warning("REA doctor returned invalid JSON: %s", exc)
        return {"completed": False, "healthy": False, "environmentHealthy": False,
                "backendStatus": "incomplete_or_unavailable", "cached": False}
    if not isinstance(envelope, dict):
        return {"completed": False, "healthy": False, "environmentHealthy": False,
                "backendStatus": "incomplete_or_unavailable", "cached": False}
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else envelope
    if not isinstance(data, dict):
        return {"completed": False, "healthy": False, "environmentHealthy": False,
                "backendStatus": "incomplete_or_unavailable", "cached": False}
    healthy = data.get("healthy") is True
    environment_healthy = data.get("environment_healthy") is True
    # Provider details can contain machine-specific paths/configuration. Keep
    # the public result to status/counts; the full diagnostic is in the log.
    summary = {
        "completed": True,
        "exitCode": result.returncode,
        "healthy": healthy,
        "environmentHealthy": environment_healthy,
        "scopeCheckCount": len(data.get("scope_checks", [])) if isinstance(data.get("scope_checks"), list) else None,
        "providerInspectionCount": len(data.get("providerInspections", [])) if isinstance(data.get("providerInspections"), list) else None,
        "backendStatus": "ready" if healthy else "incomplete_or_unavailable",
        "cached": False,
    }
    try:
        _atomic_json(cache_path, {
            "reaVersion": REA_VERSION,
            **fingerprint,
            "deep": deep,
            "checkedAt": time.time(),
            "doctor": {k: v for k, v in summary.items() if k != "cached"},
        })
    except OSError as exc:
        LOG.warning("could not persist doctor cache: %s", exc)
    return summary


def _send_json(proc: subprocess.Popen[str], value: dict[str, Any]) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(value, separators=(",", ":")) + "\n")
    proc.stdin.flush()


def _start_stdout_reader(proc: subprocess.Popen[str]) -> queue.Queue[str | None]:
    if proc.stdout is None:
        raise InstallError("MCP child stdout is unavailable")
    lines: queue.Queue[str | None] = queue.Queue()

    def read_lines() -> None:
        try:
            for line in proc.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    threading.Thread(target=read_lines, name="rea-mcp-probe-reader", daemon=True).start()
    return lines


def _read_json_id(proc: subprocess.Popen[str], lines: queue.Queue[str | None],
                  wanted_id: int, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None and lines.empty():
            raise InstallError(f"REA MCP child exited before response (code {proc.returncode})")
        try:
            line = lines.get(timeout=min(0.25, max(0.01, deadline - time.monotonic())))
        except queue.Empty:
            continue
        if line is None:
            raise InstallError(f"REA MCP child closed stdout before response id {wanted_id}")
        LOG.info("MCP probe received stdout line bytes=%d", len(line))
        if len(line) > 16 * 1024 * 1024:
            raise InstallError("REA MCP response exceeded 16 MiB")
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            # Stdout must remain protocol-clean; ignore only non-JSON
            # diagnostic lines while waiting for the requested response.
            LOG.warning("ignored non-JSON line from MCP probe (len=%d, error=%s)", len(line), exc.msg)
            continue
        if isinstance(message, dict) and message.get("id") == wanted_id:
            return message
        if isinstance(message, dict):
            LOG.info("MCP probe ignored message id=%s while waiting for id=%d", message.get("id"), wanted_id)
    raise InstallError(f"REA MCP did not answer request id {wanted_id} within {timeout}s")


def _mcp_probe(node: str, entry: Path, timeout: int = MCP_TIMEOUT_SECONDS) -> dict[str, Any]:
    stderr_path = Path(tempfile.gettempdir()) / "minis-rea-mcp-probe.log"
    with open(stderr_path, "a", encoding="utf-8") as stderr:
        os.chmod(stderr_path, 0o600)
        proc = subprocess.Popen(
            [node, str(entry), "--mcp"], cwd=str(entry.parent.parent),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        try:
            _send_json(proc, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "minis-rea-install-probe", "version": "1.0.0"},
                },
            })
            lines = _start_stdout_reader(proc)
            initialized = _read_json_id(proc, lines, 1, timeout)
            if initialized.get("error") or not isinstance(initialized.get("result"), dict):
                raise InstallError("REA MCP initialize failed")
            negotiated = initialized["result"].get("protocolVersion")
            if not isinstance(negotiated, str) or not negotiated:
                raise InstallError("REA MCP initialize omitted protocolVersion")
            _send_json(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            _send_json(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            LOG.info("MCP probe sent tools/list request")
            listed = _read_json_id(proc, lines, 2, timeout)
            if listed.get("error") or not isinstance(listed.get("result"), dict):
                raise InstallError("REA MCP tools/list failed")
            tools = listed["result"].get("tools")
            if not isinstance(tools, list):
                raise InstallError("REA MCP tools/list omitted tools array")
            return {"initialize": True, "toolsList": True, "toolCount": len(tools), "protocolVersion": negotiated}
        finally:
            if proc.stdin:
                proc.stdin.close()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)


def _package_lock_is_compatible(prefix: Path) -> bool:
    try:
        if prefix.is_symlink() or not prefix.is_dir():
            return False
        package_json_path = prefix / "package.json"
        lock_path = prefix / "package-lock.json"
        if not _managed_regular_file(package_json_path, prefix) or not _managed_regular_file(lock_path, prefix):
            return False
        package_json = json.loads((prefix / "package.json").read_text(encoding="utf-8"))
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        declared = package_json.get("dependencies", {}).get("rea-agents")
        locked_root = lock.get("packages", {}).get("", {}).get("dependencies", {}).get("rea-agents")
        installed = lock.get("packages", {}).get("node_modules/rea-agents", {}).get("version")
        return (
            lock.get("lockfileVersion") in (2, 3)
            and declared == REA_VERSION
            and locked_root == REA_VERSION
            and installed == REA_VERSION
        )
    except (OSError, ValueError, AttributeError):
        return False


def _stage_marker_path(stage: Path) -> Path:
    return stage / STAGE_MARKER


def _write_stage_marker(stage: Path, state: str) -> None:
    _atomic_json(_stage_marker_path(stage), {
        "kind": "minis-rea-install-stage",
        "version": REA_VERSION,
        "state": state,
        "updatedAt": time.time(),
    })


def _stage_state(stage: Path) -> str | None:
    try:
        marker_path = _stage_marker_path(stage)
        if stage.is_symlink() or not stage.is_dir() or not _managed_regular_file(marker_path, stage):
            return None
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if marker.get("kind") != "minis-rea-install-stage" or marker.get("version") != REA_VERSION:
            return None
        return marker.get("state") if marker.get("state") in {"preparing", "prepared"} else None
    except (OSError, ValueError, AttributeError):
        return None


def _staged_package_is_ready(stage: Path) -> bool:
    return _stage_state(stage) == "prepared" and _managed_package_is_ready(stage)


def _managed_package_is_ready(root: Path) -> bool:
    if not _package_lock_is_compatible(root):
        return False
    package, entry = _paths(root)
    try:
        package_version = json.loads((package / "package.json").read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError):
        return False
    return (
        package_version == REA_VERSION
        and _managed_regular_file(package / "package.json", root)
        and _managed_regular_file(entry, root)
    )


def _validate_wrapper_target() -> None:
    if WRAPPER.is_symlink():
        raise InstallError(f"Refusing to replace symlink wrapper: {WRAPPER}")
    if WRAPPER.exists():
        existing = WRAPPER.read_text(encoding="utf-8", errors="replace")
        if MANAGED_WRAPPER_MARKER not in existing:
            raise InstallError(f"Custom {WRAPPER} exists; left untouched")


def _prepare_package(npm: str, stage: Path, node: str) -> None:
    if PREFIX.is_symlink():
        raise InstallError(f"Refusing symlink install root: {PREFIX}")
    stage.mkdir(parents=True, mode=0o755, exist_ok=True)
    if PREFIX.is_dir() and _package_lock_is_compatible(PREFIX):
        shutil.copy2(PREFIX / "package.json", stage / "package.json")
        shutil.copy2(PREFIX / "package-lock.json", stage / "package-lock.json")
        _run([npm, "ci", "--prefix", str(stage), "--ignore-scripts", "--omit=dev", "--no-audit", "--no-fund"],
             timeout=NPM_TIMEOUT_SECONDS)
    else:
        manifest = {
            "name": "minis-rea-runtime",
            "private": True,
            "version": "1.0.0",
            "dependencies": {"rea-agents": REA_VERSION},
        }
        (stage / "package.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        _run([npm, "install", "--prefix", str(stage), "--ignore-scripts", "--omit=dev",
              "--save-exact", "--package-lock=true", "--no-audit", "--no-fund",
              f"rea-agents@{REA_VERSION}"], timeout=NPM_TIMEOUT_SECONDS)
    if not _package_lock_is_compatible(stage):
        raise InstallError("npm did not produce a persistent lockfile pinned to rea-agents 6.4.0")
    package, entry = _paths(stage)
    try:
        actual = json.loads((package / "package.json").read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError) as exc:
        raise InstallError("REA package metadata is missing after npm install") from exc
    if actual != REA_VERSION or not entry.is_file():
        raise InstallError(f"Pinned REA package/entrypoint missing (expected {REA_VERSION}, got {actual})")
    for critical_file in (stage / "package.json", stage / "package-lock.json",
                          package / "package.json", entry):
        if not _managed_regular_file(critical_file, stage):
            raise InstallError(f"Managed install file is missing, linked, or outside staging tree: {critical_file.name}")
        _fsync_file(critical_file)
    _fsync_dir(stage / "node_modules")
    _fsync_dir(stage)


def _publish_package(stage: Path) -> None:
    backup: Path | None = None
    if PREFIX.exists():
        if PREFIX.is_symlink() or not PREFIX.is_dir():
            raise InstallError(f"Refusing unexpected install target: {PREFIX}")
        backup = PREFIX.with_name(f"{PREFIX.name}.backup-{time.time_ns()}")
        if backup.exists():
            raise InstallError(f"Backup path already exists: {backup}")
        os.replace(PREFIX, backup)
    try:
        os.replace(stage, PREFIX)
        _fsync_dir(PREFIX.parent)
    except BaseException:
        if backup is not None and backup.exists() and not PREFIX.exists():
            os.replace(backup, PREFIX)
        raise
    if backup:
        LOG.info("previous installation retained at %s", backup)


def _publish_wrapper(node: str) -> None:
    WRAPPER.parent.mkdir(parents=True, exist_ok=True)
    _validate_wrapper_target()
    if WRAPPER.exists():
        backup = WRAPPER.with_name(f"rea.backup-{time.time_ns()}")
        if backup.exists():
            raise InstallError(f"Wrapper backup path already exists: {backup}")
        shutil.copy2(WRAPPER, backup)
    content = (
        "#!/bin/sh\n"
        f"{MANAGED_WRAPPER_MARKER}\n"
        f"exec {node} {PREFIX}/node_modules/rea-agents/scripts/rea.mjs \"$@\"\n"
    )
    fd, temp_name = tempfile.mkstemp(prefix=".rea.", dir=str(WRAPPER.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o755)
        os.replace(temp_name, WRAPPER)
        _fsync_dir(WRAPPER.parent)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _install_official_skill(package: Path) -> str:
    source = package / REA_SKILL_SOURCE
    if not (source / "SKILL.md").is_file():
        raise InstallError("REA npm package does not contain the official reverse-engineer-anything skill")
    if REA_SKILL_DEST.exists() or REA_SKILL_DEST.is_symlink():
        LOG.info("preserving existing skill at %s", REA_SKILL_DEST)
        return "preserved_existing"
    SKILLS_ROOT.mkdir(parents=True, exist_ok=True)
    temp = SKILLS_ROOT / f".rea-skill-stage-{os.getpid()}-{int(time.time())}"
    if temp.exists():
        raise InstallError(f"Skill staging path already exists: {temp}")
    try:
        shutil.copytree(source, temp, symlinks=False)
        shutil.copy2(package / "LICENSE", temp / "LICENSE.rea-agents")
        if not (temp / "SKILL.md").is_file() or not (temp / "LICENSE.rea-agents").is_file():
            raise InstallError("Official REA skill copy is incomplete")
        os.replace(temp, REA_SKILL_DEST)
        return "installed"
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def _installed_entry() -> tuple[str, Path]:
    return _paths(PREFIX)


def install() -> dict[str, Any]:
    node, npm, node_version = _node_and_npm()
    PREFIX.parent.mkdir(parents=True, exist_ok=True)
    _validate_wrapper_target()
    active_ready = _managed_package_is_ready(PREFIX)
    if active_ready:
        LOG.info("reusing verified active REA package at %s; npm will not be rerun", PREFIX)
        install_root = PREFIX
        publish_stage = False
        npm_install_path = "reused_active"
    else:
        stage = PREFIX.with_name(f".{PREFIX.name}.stage")
        if stage.exists() and _stage_state(stage) is None:
            raise InstallError(f"Unrecognized staging directory; preserved without modifying: {stage}")
        if stage.is_symlink():
            raise InstallError(f"Refusing symlink staging directory: {stage}")
        if _staged_package_is_ready(stage):
            LOG.info("reusing verified npm stage at %s; npm will not be rerun", stage)
            npm_install_path = "reused_stage"
        else:
            stage.mkdir(parents=True, mode=0o755, exist_ok=True)
            _write_stage_marker(stage, "preparing")
            _prepare_package(npm, stage, node)
            package, stage_entry = _paths(stage)
            if not _package_lock_is_compatible(stage) or not _managed_regular_file(stage_entry, stage):
                raise InstallError("npm staging validation failed; staging tree retained for diagnosis")
            _write_stage_marker(stage, "prepared")
            npm_install_path = "npm_install"
        install_root = stage
        publish_stage = True

    _, stage_entry = _paths(install_root)
    version_timeout = _adaptive_cli_timeout(stage_entry)
    actual = _version(node, stage_entry, timeout=version_timeout)
    if actual != REA_VERSION:
        raise InstallError(f"REA version mismatch: expected {REA_VERSION}, got {actual}; verified npm stage retained")
    doctor = _doctor(node, stage_entry)
    mcp = _mcp_probe(node, stage_entry)
    # All actual CLI/MCP checks happen before publishing or registering. The
    # prepared npm stage survives recoverable CLI/probe failures so a retry
    # does not repeat the long npm download.
    if publish_stage:
        marker_path = _stage_marker_path(install_root)
        if marker_path.exists():
            marker_path.unlink()
            _fsync_dir(install_root)
        _publish_package(install_root)
    _publish_wrapper(node)
    package, _ = _installed_entry()
    skill_status = _install_official_skill(package)
    _, published_entry = _installed_entry()
    try:
        fingerprint = _package_fingerprint(PREFIX, published_entry, node_version)
        verification = _write_validation_cache(PREFIX, fingerprint, mcp, doctor)
    except (InstallError, OSError) as exc:
        LOG.warning("could not persist verified runtime cache: %s", exc)
        verification = {"live": True, "cached": False, "verifiedAt": time.time()}
    return {
        "status": "installed",
        "installed": True,
        "version": actual,
        "nodeVersion": node_version,
        "cliVersionTimeoutSeconds": version_timeout,
        "npmInstallPath": npm_install_path,
        "packageLock": str(PREFIX / "package-lock.json"),
        "mcp": mcp,
        "doctor": doctor,
        "verification": verification,
        "skill": {"status": skill_status, "path": str(REA_SKILL_DEST)},
        "registrationReady": True,
    }


def diagnose(*, deep: bool = False) -> dict[str, Any]:
    node, _npm, node_version = _node_and_npm()
    package, entry = _installed_entry()
    if not _managed_package_is_ready(PREFIX):
        raise InstallError("REA package/lock is not installed at the managed path")
    fingerprint = _package_fingerprint(PREFIX, entry, node_version)
    if not deep:
        cache = _read_validation_cache(PREFIX, entry, fingerprint)
        if cache is not None:
            doctor = cache.get("doctor") if isinstance(cache.get("doctor"), dict) else {
                "completed": False, "healthy": False,
                "environmentHealthy": False,
                "backendStatus": "not_included_in_last_verification",
            }
            return {
                "status": "last_verified",
                "installed": True,
                "version": REA_VERSION,
                "nodeVersion": node_version,
                "cliVersionTimeoutSeconds": _adaptive_cli_timeout(entry),
                "doctor": {**doctor, "cached": True},
                "mcp": {**cache["mcp"], "cached": True},
                "verification": {
                    "live": False,
                    "cached": True,
                    "verifiedAt": cache.get("verifiedAt"),
                    "entrySha256": fingerprint["entrySha256"],
                    "packageLockSha256": fingerprint["packageLockSha256"],
                    "nodeVersion": node_version,
                },
                "packageLock": str(PREFIX / "package-lock.json"),
                "registrationReady": False,
            }
    version_timeout = _adaptive_cli_timeout(entry)
    actual = _version(node, entry, timeout=version_timeout)
    if actual != REA_VERSION:
        raise InstallError(f"REA version mismatch: expected {REA_VERSION}, got {actual}")
    doctor = _doctor(node, entry, deep=deep, use_cache=not deep)
    mcp = _mcp_probe(node, entry)
    fingerprint = _package_fingerprint(PREFIX, entry, node_version)
    verification = _write_validation_cache(PREFIX, fingerprint, mcp, doctor)
    return {
        "status": "ready" if mcp["initialize"] and mcp["toolsList"] else "failed",
        "installed": True,
        "version": actual,
        "nodeVersion": node_version,
        "cliVersionTimeoutSeconds": version_timeout,
        "doctor": doctor,
        "mcp": mcp,
        "verification": verification,
        "packageLock": str(PREFIX / "package-lock.json"),
        "registrationReady": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "doctor", "verify"), nargs="?", default="install")
    parser.add_argument("--deep", action="store_true",
                        help="refresh full REA backend diagnostics instead of using the brief cached status")
    args = parser.parse_args()
    try:
        result = install() if args.action == "install" else diagnose(deep=args.deep)
        print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
        return 0
    except Exception as exc:
        LOG.exception("REA %s failed", args.action)
        stage = PREFIX.with_name(f".{PREFIX.name}.stage")
        stage_state = _stage_state(stage) if args.action == "install" else None
        print(json.dumps({
            "status": "failed",
            "installed": False if args.action == "install" else None,
            "registrationReady": False,
            "stageRetained": stage_state is not None,
            "stageState": stage_state,
            "error": str(exc),
            "log": str(LOG_PATH),
        }, separators=(",", ":"), ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
