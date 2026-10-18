#!/usr/bin/env python3
"""Install and verify the pinned REA CLI in the Minis Alpine guest.

The script deliberately separates npm/package/MCP availability from REA's
analysis-engine readiness. Missing commercial or optional engines are reported
by `doctor`; they are never installed or represented as ready here.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
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
DOCTOR_TIMEOUT_SECONDS = 120
NPM_TIMEOUT_SECONDS = 900
MANAGED_WRAPPER_MARKER = "# minis-managed-rea-wrapper-v1"


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


def _version(node: str, entry: Path) -> str:
    result = _run([node, str(entry), "--version"], timeout=30, cwd=entry.parent.parent)
    text = (result.stdout + "\n" + result.stderr).strip()
    match = re.search(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)", text)
    if not match:
        raise InstallError("REA --version returned no parseable version")
    return match.group(1)


def _doctor(node: str, entry: Path) -> dict[str, Any]:
    result = _run([node, str(entry), "doctor", "--format", "json", "--full-output"],
                  timeout=DOCTOR_TIMEOUT_SECONDS, cwd=entry.parent.parent,
                  check=False, log_output=False)
    try:
        envelope = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise InstallError("REA doctor did not return valid JSON") from exc
    if not isinstance(envelope, dict) or not isinstance(envelope.get("data"), dict):
        raise InstallError("REA doctor JSON has no data object")
    data = envelope["data"]
    healthy = data.get("healthy") is True
    environment_healthy = data.get("environment_healthy") is True
    # Provider details can contain machine-specific paths/configuration. Keep
    # the public result to status/counts; the full diagnostic is in the log.
    return {
        "completed": True,
        "exitCode": result.returncode,
        "healthy": healthy,
        "environmentHealthy": environment_healthy,
        "scopeCheckCount": len(data.get("scope_checks", [])) if isinstance(data.get("scope_checks"), list) else None,
        "providerInspectionCount": len(data.get("providerInspections", [])) if isinstance(data.get("providerInspections"), list) else None,
        "backendStatus": "ready" if healthy else "incomplete_or_unavailable",
    }


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
        package_json = json.loads((prefix / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((prefix / "package-lock.json").read_text(encoding="utf-8"))
        declared = package_json.get("dependencies", {}).get("rea-agents")
        locked_root = lock.get("packages", {}).get("", {}).get("dependencies", {}).get("rea-agents")
        installed = lock.get("packages", {}).get("node_modules/rea-agents", {}).get("version")
        return declared == REA_VERSION and locked_root == REA_VERSION and installed == REA_VERSION
    except (OSError, ValueError, AttributeError):
        return False


def _prepare_package(npm: str, stage: Path, node: str) -> None:
    target_package, _ = _paths(PREFIX)
    if PREFIX.is_symlink():
        raise InstallError(f"Refusing symlink install root: {PREFIX}")
    stage.mkdir(parents=True, mode=0o755)
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


def _publish_package(stage: Path) -> None:
    backup: Path | None = None
    if PREFIX.exists():
        if PREFIX.is_symlink() or not PREFIX.is_dir():
            raise InstallError(f"Refusing unexpected install target: {PREFIX}")
        backup = PREFIX.with_name(f"{PREFIX.name}.backup-{int(time.time())}")
        if backup.exists():
            raise InstallError(f"Backup path already exists: {backup}")
        os.replace(PREFIX, backup)
    try:
        os.replace(stage, PREFIX)
    except BaseException:
        if backup is not None and backup.exists() and not PREFIX.exists():
            os.replace(backup, PREFIX)
        raise
    if backup:
        LOG.info("previous installation retained at %s", backup)


def _publish_wrapper(node: str) -> None:
    WRAPPER.parent.mkdir(parents=True, exist_ok=True)
    if WRAPPER.is_symlink():
        raise InstallError(f"Refusing to replace symlink wrapper: {WRAPPER}")
    if WRAPPER.exists():
        existing = WRAPPER.read_text(encoding="utf-8", errors="replace")
        if MANAGED_WRAPPER_MARKER not in existing:
            raise InstallError(f"Custom {WRAPPER} exists; left untouched")
        backup = WRAPPER.with_name(f"rea.backup-{int(time.time())}")
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
    stage = PREFIX.with_name(f".{PREFIX.name}.stage-{os.getpid()}-{int(time.time())}")
    if stage.exists():
        raise InstallError(f"Staging path already exists: {stage}")
    try:
        _prepare_package(npm, stage, node)
        _, stage_entry = _paths(stage)
        actual = _version(node, stage_entry)
        if actual != REA_VERSION:
            raise InstallError(f"REA version mismatch: expected {REA_VERSION}, got {actual}")
        doctor = _doctor(node, stage_entry)
        mcp = _mcp_probe(node, stage_entry)
        # All protocol/package checks happen before publishing or registering.
        # Doctor health is separately reported because missing analysis engines
        # do not mean the MCP runtime failed to install.
        _publish_package(stage)
        _publish_wrapper(node)
        package, _ = _installed_entry()
        skill_status = _install_official_skill(package)
        return {
            "status": "installed",
            "installed": True,
            "version": actual,
            "nodeVersion": node_version,
            "packageLock": str(PREFIX / "package-lock.json"),
            "mcp": mcp,
            "doctor": doctor,
            "skill": {"status": skill_status, "path": str(REA_SKILL_DEST)},
            "registrationReady": True,
        }
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def diagnose() -> dict[str, Any]:
    node, _npm, node_version = _node_and_npm()
    package, entry = _installed_entry()
    if not entry.is_file() or not _package_lock_is_compatible(PREFIX):
        raise InstallError("REA package/lock is not installed at the managed path")
    actual = _version(node, entry)
    if actual != REA_VERSION:
        raise InstallError(f"REA version mismatch: expected {REA_VERSION}, got {actual}")
    doctor = _doctor(node, entry)
    mcp = _mcp_probe(node, entry)
    return {
        "status": "ready" if mcp["initialize"] and mcp["toolsList"] else "failed",
        "installed": True,
        "version": actual,
        "nodeVersion": node_version,
        "doctor": doctor,
        "mcp": mcp,
        "packageLock": str(PREFIX / "package-lock.json"),
        "registrationReady": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "doctor", "verify"), nargs="?", default="install")
    args = parser.parse_args()
    try:
        result = install() if args.action == "install" else diagnose()
        print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
        return 0
    except Exception as exc:
        LOG.exception("REA %s failed", args.action)
        print(json.dumps({
            "status": "failed",
            "installed": False if args.action == "install" else None,
            "registrationReady": False,
            "error": str(exc),
            "log": str(LOG_PATH),
        }, separators=(",", ":"), ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
