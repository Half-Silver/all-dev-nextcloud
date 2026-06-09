#!/usr/bin/env python3
"""CT Engine — Universal snap plugin engine for Control Tower integration.

Reads a per-app plugin.yaml manifest and handles:
- Config loading via snapctl get with YAML file fallback
- Config validation (required keys, types)
- Setup command execution with config interpolation
- App process management with graceful shutdown
- Callback reporting to Control Tower
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(message: str) -> None:
    print(f"[ct-engine] {message}", file=sys.stderr, flush=True)


def log_error(message: str) -> None:
    print(f"[ct-engine] ERROR: {message}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# YAML Parser (minimal, no external dependencies)
# ---------------------------------------------------------------------------

def parse_yaml_value(raw: str) -> str | int | bool:
    """Parse a single YAML value string into a typed Python value."""
    stripped = raw.strip()

    # Quoted strings
    if len(stripped) >= 2:
        if (stripped.startswith("'") and stripped.endswith("'")) or \
           (stripped.startswith('"') and stripped.endswith('"')):
            return stripped[1:-1]

    # Booleans
    if stripped.lower() in ("true", "yes"):
        return True
    if stripped.lower() in ("false", "no"):
        return False

    # Integers
    try:
        return int(stripped)
    except ValueError:
        pass

    # Empty collections
    if stripped == "[]":
        return []
    if stripped == "{}":
        return {}

    # Flow-style dict: { key: val, key: val }
    if stripped.startswith("{") and stripped.endswith("}"):
        inner = stripped[1:-1].strip()
        if not inner:
            return {}
        flow_dict: dict = {}
        for pair in inner.split(","):
            if ":" in pair:
                k, _, v = pair.partition(":")
                flow_dict[k.strip()] = parse_yaml_value(v.strip())
        return flow_dict

    return stripped


def parse_simple_yaml(text: str) -> dict:
    """Parse a simple flat or one-level-nested YAML document.

    Supports:
        key: value
        parent:
          child-key: child-value
        list-parent:
          - command: "something"
            on: config-change

    This is intentionally minimal — no anchors, no multi-line strings,
    no flow syntax. Sufficient for plugin.yaml and config.yaml files.
    """
    result: dict = {}
    lines = text.splitlines()
    i = 0
    current_parent = None
    current_list = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # Detect indentation level
        indent = len(line) - len(line.lstrip())

        # Top-level key
        if indent == 0 and ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()

            if value:
                result[key] = parse_yaml_value(value)
                current_parent = None
                current_list = None
            else:
                # Start of a nested block — peek ahead to determine if list or map
                if i + 1 < len(lines):
                    next_stripped = lines[i + 1].strip()
                    if next_stripped.startswith("- "):
                        result[key] = []
                        current_list = key
                        current_parent = None
                    else:
                        result[key] = {}
                        current_parent = key
                        current_list = None
                else:
                    result[key] = {}
                    current_parent = key
                    current_list = None

            i += 1
            continue

        # Nested map entry (2-space indent under a parent)
        if indent >= 2 and current_parent is not None and ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()

            if value:
                result[current_parent][key] = parse_yaml_value(value)
            else:
                # Sub-nested block (3rd level, e.g. config keys with properties)
                sub_dict: dict = {}
                j = i + 1
                while j < len(lines):
                    sub_line = lines[j]
                    sub_stripped = sub_line.strip()
                    sub_indent = len(sub_line) - len(sub_line.lstrip())
                    if not sub_stripped or sub_stripped.startswith("#"):
                        j += 1
                        continue
                    if sub_indent <= indent:
                        break
                    if ":" in sub_stripped:
                        sk, _, sv = sub_stripped.partition(":")
                        sub_dict[sk.strip()] = parse_yaml_value(sv.strip()) if sv.strip() else ""
                    j += 1
                result[current_parent][key] = sub_dict
                i = j
                continue

            i += 1
            continue

        # List entry (under a list parent)
        if indent >= 2 and current_list is not None and stripped.startswith("- "):
            entry_content = stripped[2:].strip()
            if ":" in entry_content:
                # Dict entry in list: - key: value
                list_item: dict = {}
                k, _, v = entry_content.partition(":")
                list_item[k.strip()] = parse_yaml_value(v.strip()) if v.strip() else ""

                # Collect continuation keys at deeper indent
                j = i + 1
                while j < len(lines):
                    cont_line = lines[j]
                    cont_stripped = cont_line.strip()
                    cont_indent = len(cont_line) - len(cont_line.lstrip())
                    if not cont_stripped or cont_stripped.startswith("#"):
                        j += 1
                        continue
                    if cont_indent <= indent or cont_stripped.startswith("- "):
                        break
                    if ":" in cont_stripped:
                        ck, _, cv = cont_stripped.partition(":")
                        list_item[ck.strip()] = parse_yaml_value(cv.strip()) if cv.strip() else ""
                    j += 1

                result[current_list].append(list_item)
                i = j
                continue
            else:
                result[current_list].append(parse_yaml_value(entry_content))
                i += 1
                continue

        i += 1

    return result


# ---------------------------------------------------------------------------
# Plugin Loader
# ---------------------------------------------------------------------------

class Plugin:
    """Parsed plugin.yaml manifest."""

    def __init__(self, data: dict) -> None:
        self.raw = data

        # App section
        app = data.get("app", {})
        self.app_name: str = app.get("name", "unknown")
        self.app_version: str = str(app.get("version", "0.0.0"))

        # Config section — each key maps to its properties dict
        self.config_schema: dict[str, dict] = {}
        config_raw = data.get("config", {})
        for key, props in config_raw.items():
            if isinstance(props, dict):
                self.config_schema[key] = props
            else:
                # Simple key: value shorthand
                self.config_schema[key] = {"required": False, "type": "string", "default": str(props)}

        # Setup commands
        self.setup_commands: list[dict] = data.get("setup", [])

        # Run section
        run = data.get("run", {})
        self.run_command: str = run.get("command", "")
        self.run_workdir: str = run.get("workdir", "")

        # Output section
        output = data.get("output", {})
        self.output_mode: str = output.get("mode", "logs")
        self.output_interval: int = int(output.get("interval", 0))
        # CT-compatible event names (matches Control Tower expected values)
        self.initial_event: str = output.get("initial_event", "message_initial")
        self.periodic_event: str = output.get("periodic_event",
                                              output.get("event_name", "message"))
        # 'deployment_stop' = uninstall confirmation. Sent ONLY from the remove
        # hook (actual `snap remove`) — never on a transient stop/restart/refresh.
        self.stop_event: str = output.get("stop_event", "deployment_stop")
        # Auto-update lifecycle events, sent from the snap refresh hooks.
        self.pre_refresh_event: str = output.get("pre_refresh_event", "update_started")
        self.post_refresh_event: str = output.get("post_refresh_event", "update_complete")
        # Non-terminal liveness: a SIGTERM (stop/restart, or the stop phase of a
        # refresh) that is NOT an uninstall.
        self.stopping_event: str = output.get("stopping_event", "app_stopping")
        # Fast "the app is installed and booting" ping. Emitted as the VERY FIRST
        # callback — before setup commands and before message_initial — so Control
        # Tower shows liveness as soon as the snap is installed, instead of waiting
        # for setup + the initial status gather to finish.
        self.started_event: str = output.get("started_event", "app_started")

        # Sidecar section — command whose output becomes callback content
        sidecar = data.get("sidecar", {})
        self.sidecar_status_command: str = sidecar.get("status_command", "") if isinstance(sidecar, dict) else ""

    def validate(self) -> list[str]:
        """Return a list of validation errors. Empty = valid."""
        errors: list[str] = []
        if not self.app_name or self.app_name == "unknown":
            errors.append("plugin.yaml: app.name is required")
        # Note: run.command is optional — when empty, ct-engine runs in
        # "sidecar" mode (sends callbacks without launching an app process).
        for key, props in self.config_schema.items():
            if not isinstance(props, dict):
                errors.append(f"plugin.yaml: config.{key} must be a mapping with type/required/default")
        return errors


def load_plugin(plugin_path: Path) -> Plugin:
    """Load and validate a plugin.yaml file."""
    if not plugin_path.exists():
        log_error(f"Plugin manifest not found: {plugin_path}")
        sys.exit(1)

    raw_text = plugin_path.read_text(encoding="utf-8")
    data = parse_simple_yaml(raw_text)
    plugin = Plugin(data)

    errors = plugin.validate()
    if errors:
        for err in errors:
            log_error(err)
        sys.exit(1)

    log(f"Loaded plugin: {plugin.app_name} v{plugin.app_version}")
    return plugin


# ---------------------------------------------------------------------------
# Config Loader (matches all-dev-testcontrol pattern)
# ---------------------------------------------------------------------------

# CT integration keys — always available, not defined in plugin.yaml
CT_KEYS = (
    "ct-callback-url",
    "ct-snap-name",
    "ct-node-id",
    "ct-deployment-id",
)


def snapctl_get(key: str) -> str:
    """Read a snap config key via snapctl get."""
    result = subprocess.run(
        ["snapctl", "get", key],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def read_config_yaml(path: Path) -> tuple[bool, dict[str, str]]:
    """Read persisted config.yaml from SNAP_COMMON."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False, {}
    except OSError as exc:
        log(f"Failed to read config file {path}: {exc}")
        return False, {}

    parsed = parse_simple_yaml(raw)
    # Flatten all values to strings
    flat: dict[str, str] = {}
    for k, v in parsed.items():
        flat[k] = str(v) if not isinstance(v, str) else v
    return True, flat


def load_config(plugin: Plugin) -> dict[str, str]:
    """Load config from snapctl / config.yaml / defaults, following the reference pattern."""
    config: dict[str, str] = {}

    # Try persisted YAML first
    snap_common = os.environ.get("SNAP_COMMON")
    persisted: dict[str, str] = {}
    has_yaml = False
    if snap_common:
        config_path = Path(snap_common) / "config.yaml"
        has_yaml, persisted = read_config_yaml(config_path)
        if not has_yaml:
            log(f"No persisted config at {config_path}. Using snapctl/defaults.")
    else:
        log("SNAP_COMMON not set. Using snapctl/defaults.")

    # Collect all keys: CT keys + plugin config keys
    all_keys = list(CT_KEYS) + list(plugin.config_schema.keys())

    for key in all_keys:
        # Priority: snapctl → persisted YAML → plugin default → empty
        value = snapctl_get(key)
        
        if not value and has_yaml and key in persisted:
            value = persisted[key]

        # Apply default from plugin schema if still empty
        if not value and key in plugin.config_schema:
            props = plugin.config_schema[key]
            if isinstance(props, dict) and "default" in props:
                value = str(props["default"])

        config[key] = value

    # ct-snap-name is part of the snap's runtime identity, not something Control
    # Tower pushes in snap_config (it only sends ct-node-id / ct-callback-url /
    # ct-deployment-id). Derive it from the snap environment so it is always
    # populated — otherwise it logs as "(unset)" and any {ct-snap-name}
    # interpolation in plugin.yaml resolves to an empty string.
    if not config.get("ct-snap-name"):
        config["ct-snap-name"] = (
            os.environ.get("SNAP_INSTANCE_NAME")
            or os.environ.get("SNAP_NAME")
            or plugin.app_name
        )

    return config


# ---------------------------------------------------------------------------
# Config Validator
# ---------------------------------------------------------------------------

def validate_config(plugin: Plugin, config: dict[str, str]) -> list[str]:
    """Validate config values against plugin schema. Returns list of errors."""
    errors: list[str] = []

    for key, props in plugin.config_schema.items():
        if not isinstance(props, dict):
            continue

        value = config.get(key, "")
        required = props.get("required", False)
        expected_type = props.get("type", "string")

        # Required check
        if required and not value:
            errors.append(f"Required config key '{key}' is not set.")
            continue

        # Type check (only if value is present)
        if value:
            if expected_type == "int":
                try:
                    int(value)
                except ValueError:
                    errors.append(f"Config key '{key}' must be an integer, got: '{value}'")

            elif expected_type == "url":
                if not (value.startswith("http://") or value.startswith("https://")):
                    errors.append(f"Config key '{key}' must be a URL starting with http:// or https://, got: '{value}'")

            elif expected_type == "bool":
                if value.lower() not in ("true", "false", "yes", "no", "1", "0"):
                    errors.append(f"Config key '{key}' must be a boolean, got: '{value}'")

    # Validate CT callback URL if present
    callback_url = config.get("ct-callback-url", "")
    if callback_url and not (callback_url.startswith("http://") or callback_url.startswith("https://")):
        errors.append(f"ct-callback-url must start with http:// or https://, got: '{callback_url}'")

    return errors


# ---------------------------------------------------------------------------
# Command Runner
# ---------------------------------------------------------------------------

def interpolate(template: str, config: dict[str, str]) -> str:
    """Replace {key-name} placeholders with config values."""
    def replacer(match: re.Match) -> str:
        key = match.group(1)
        return config.get(key, "")
    return re.sub(r"\{([a-zA-Z0-9_-]+)\}", replacer, template)


def run_command(command_str: str, config: dict[str, str], label: str = "command") -> bool:
    """Interpolate and execute a shell command. Returns True on success."""
    resolved = interpolate(command_str, config)
    log(f"Executing {label}: {resolved}")

    try:
        result = subprocess.run(
            resolved,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.stdout:
            for line in result.stdout.strip().splitlines():
                log(f"  stdout: {line}")
        if result.stderr:
            for line in result.stderr.strip().splitlines():
                log(f"  stderr: {line}")

        if result.returncode != 0:
            log_error(f"{label} failed with exit code {result.returncode}")
            return False

        log(f"{label} completed successfully.")
        return True

    except subprocess.TimeoutExpired:
        log_error(f"{label} timed out after 120 seconds.")
        return False
    except Exception as exc:
        log_error(f"{label} raised exception: {exc}")
        return False


def run_setup_commands(plugin: Plugin, config: dict[str, str], trigger: str = "config-change") -> bool:
    """Execute setup commands matching the given trigger. Returns False if any required command fails."""
    if not plugin.setup_commands:
        return True

    for idx, cmd_spec in enumerate(plugin.setup_commands):
        cmd_trigger = cmd_spec.get("on", "config-change")
        cmd_template = cmd_spec.get("command", "")

        if not cmd_template:
            continue
        if cmd_trigger != trigger:
            continue

        label = f"setup[{idx}]"
        success = run_command(cmd_template, config, label=label)
        if not success:
            log_error(f"Setup command failed: {cmd_template}")
            # Refuse to continue — setup failure is fatal
            return False

    return True


# ---------------------------------------------------------------------------
# Config Persistence (same pattern as reference)
# ---------------------------------------------------------------------------

def yaml_quote(value: str) -> str:
    """YAML-safe single-quote a value."""
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def persist_config(plugin: Plugin, config: dict[str, str]) -> None:
    """Write resolved config to $SNAP_COMMON/config.yaml."""
    snap_common = os.environ.get("SNAP_COMMON")
    if not snap_common:
        log("SNAP_COMMON not set. Cannot persist config.")
        return

    config_path = Path(snap_common) / "config.yaml"
    config_tmp = config_path.with_suffix(".yaml.tmp")

    try:
        old_umask = os.umask(0o077)
        try:
            with open(config_tmp, "w", encoding="utf-8") as f:
                # Write CT keys
                for key in CT_KEYS:
                    f.write(f"{key}: {yaml_quote(config.get(key, ''))}\n")
                # Write plugin config keys
                for key in plugin.config_schema:
                    f.write(f"{key}: {yaml_quote(config.get(key, ''))}\n")
        finally:
            os.umask(old_umask)

        config_tmp.rename(config_path)
        os.chmod(config_path, 0o600)
        log(f"Config persisted to {config_path}")

    except OSError as exc:
        log_error(f"Failed to persist config: {exc}")


# ---------------------------------------------------------------------------
# Callback Sender (matches reference pattern exactly)
# ---------------------------------------------------------------------------

def send_callback(callback_url: str, event_name: str, message: str) -> None:
    """POST a JSON callback event to the Control Tower."""
    payload = {
        "event": event_name,
        "data": {
            "message": message,
        },
    }
    try:
        request = urllib.request.Request(
            callback_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    except ValueError as exc:
        log_error(f"Callback '{event_name}' failed: invalid URL: {exc}")
        return

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.getcode()
        log(f"Sent '{event_name}' callback (HTTP {status}).")
    except urllib.error.HTTPError as exc:
        log_error(f"Callback '{event_name}' failed: HTTP {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        log_error(f"Callback '{event_name}' failed: {exc.reason}")
    except Exception as exc:  # noqa: BLE001
        log_error(f"Callback '{event_name}' failed: {exc}")


# ---------------------------------------------------------------------------
# Sidecar Status
# ---------------------------------------------------------------------------

def gather_sidecar_status(plugin: Plugin, config: dict[str, str]) -> str:
    """Run the sidecar status command to get callback content.

    In sidecar mode there is no app process to capture stdout from.
    Instead, the plugin.yaml can define a shell command whose output
    becomes the callback message (e.g. the dashboard URL).
    """
    if plugin.sidecar_status_command:
        resolved = interpolate(plugin.sidecar_status_command, config)
        try:
            result = subprocess.run(
                resolved,
                shell=True,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.stdout.strip():
                return result.stdout.strip()
        except Exception as exc:
            log(f"Sidecar status command failed: {exc}")

    # Fallback: query snap service status
    try:
        result = subprocess.run(
            ["snapctl", "services"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass

    return f"{plugin.app_name} sidecar running"


def status_message(plugin: Plugin, config: dict[str, str], fallback: str) -> str:
    """Best-effort human status for a callback.

    In sidecar mode with a status_command (e.g. the live URL) we report that;
    otherwise we use the provided fallback string.
    """
    if not plugin.run_command and plugin.sidecar_status_command:
        return gather_sidecar_status(plugin, config)
    return fallback


# ---------------------------------------------------------------------------
# App Launcher
# ---------------------------------------------------------------------------

class AppProcess:
    """Manages the child app process with graceful shutdown."""

    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self._shutdown_requested = False

    def launch(self, command_str: str, config: dict[str, str], workdir: str = "") -> bool:
        """Start the app process. Returns False if launch fails."""
        resolved = interpolate(command_str, config)
        log(f"Launching app: {resolved}")

        cwd = workdir if workdir else os.environ.get("SNAP", None)

        try:
            self.process = subprocess.Popen(
                resolved,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=cwd,
            )
            log(f"App started with PID {self.process.pid}")
            return True
        except Exception as exc:
            log_error(f"Failed to launch app: {exc}")
            return False

    def is_running(self) -> bool:
        """Check if the app process is still running."""
        if self.process is None:
            return False
        return self.process.poll() is None

    def read_output(self, max_lines: int = 50) -> str:
        """Read available output lines from the app (non-blocking)."""
        if self.process is None or self.process.stdout is None:
            return ""

        lines: list[str] = []
        try:
            while len(lines) < max_lines:
                # Use a short timeout to avoid blocking
                import select
                ready, _, _ = select.select([self.process.stdout], [], [], 0.1)
                if not ready:
                    break
                line = self.process.stdout.readline()
                if not line:
                    break
                lines.append(line.rstrip())
        except Exception:
            pass

        return "\n".join(lines)

    def shutdown(self, timeout: int = 10) -> None:
        """Gracefully stop the app process."""
        if self.process is None:
            return

        self._shutdown_requested = True
        log(f"Shutting down app (PID {self.process.pid})...")

        try:
            self.process.terminate()
            self.process.wait(timeout=timeout)
            log("App stopped gracefully.")
        except subprocess.TimeoutExpired:
            log("App did not stop in time. Sending SIGKILL.")
            self.process.kill()
            self.process.wait(timeout=5)
        except Exception as exc:
            log_error(f"Error during shutdown: {exc}")


# ---------------------------------------------------------------------------
# Main: run subcommand
# ---------------------------------------------------------------------------

def cmd_run(plugin: Plugin) -> int:
    """Main daemon loop: load config, run setup, launch app, send callbacks."""
    config = load_config(plugin)

    # Validate config
    errors = validate_config(plugin, config)
    if errors:
        for err in errors:
            log_error(err)
        log_error("Config validation failed. Waiting for valid configuration via snap set.")

        callback_url = config.get("ct-callback-url", "")
        if callback_url:
            send_callback(callback_url, "config_error", "; ".join(errors))

        # Poll snapctl every 30s — picks up changes from 'snap set' without needing a restart
        log("Polling for valid configuration every 30 seconds...")
        while True:
            time.sleep(30)
            config = load_config(plugin)
            errors = validate_config(plugin, config)
            if not errors:
                log("Valid configuration detected. Starting app...")
                break
            log("Still waiting for valid configuration via snap set...")

    # Log resolved config (redact sensitive values)
    log("Resolved configuration:")
    for key in list(CT_KEYS) + list(plugin.config_schema.keys()):
        value = config.get(key, "")
        if any(s in key.lower() for s in ("key", "token", "secret", "password")):
            display = f"{value[:4]}...{value[-4:]}" if len(value) > 8 else "****"
        else:
            display = value or "(unset)"
        log(f"  {key} = {display}")

    callback_url = config.get("ct-callback-url", "")

    # Fast liveness ping: the snap is installed and the engine is up. Sent BEFORE
    # setup commands and message_initial so Control Tower reflects "app started"
    # immediately rather than after setup + the initial status gather. Fires on
    # every (re)start of the sidecar, mirroring message_initial.
    if callback_url:
        started_msg = status_message(
            plugin, config, f"{plugin.app_name} v{plugin.app_version} installed and starting."
        )
        send_callback(callback_url, plugin.started_event, started_msg)

    # Run setup commands
    if not run_setup_commands(plugin, config, trigger="config-change"):
        log_error("Setup commands failed. Refusing to start app.")
        if callback_url:
            send_callback(callback_url, "setup_error", "One or more setup commands failed.")
        return 1

    # Send initial callback (message_initial in CT)
    if callback_url:
        initial_msg = status_message(
            plugin, config, f"{plugin.app_name} v{plugin.app_version} started."
        )
        send_callback(callback_url, plugin.initial_event, initial_msg)

    # Launch the app (or run in sidecar mode)
    app = AppProcess()
    if plugin.run_command:
        if not app.launch(plugin.run_command, config, plugin.run_workdir):
            log_error("App failed to launch.")
            if callback_url:
                send_callback(callback_url, "launch_error", "App process failed to start.")
            return 1
    else:
        log("Running in sidecar mode (no app to manage). Sending periodic callbacks only.")

    # Set up signal handler for graceful shutdown
    def handle_signal(signum: int, frame: object) -> None:
        # A SIGTERM is a TRANSIENT stop: a restart, a reboot, or the stop phase of
        # a snap refresh. It is NOT an uninstall, so we must not send the
        # 'deployment_stop' (uninstall) event here — CT would tear the app down.
        # Send a non-terminal liveness event instead; 'deployment_stop' is
        # reserved for the remove hook (see cmd_hook_remove).
        log(f"Received signal {signum}. Transient stop (not an uninstall) — shutting down.")
        app.shutdown()
        if callback_url:
            send_callback(callback_url, plugin.stopping_event,
                          f"{plugin.app_name} service stopping.")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Main event loop
    started = time.monotonic()
    interval_seconds = plugin.output_interval * 60
    next_callback = started + interval_seconds if interval_seconds > 0 else None
    output_buffer: list[str] = []

    while True:
        now = time.monotonic()

        # Check if app is still running
        if plugin.run_command and not app.is_running():
            exit_code = app.process.returncode if app.process else -1
            log(f"App process exited with code {exit_code}.")
            if callback_url:
                send_callback(callback_url, "app_exited", f"App exited with code {exit_code}.")
            return exit_code if exit_code is not None else 1

        # Capture app output
        if app.process:
            new_output = app.read_output(max_lines=100)
            if new_output:
                # Echo to our own stderr so snap logs captures it
                for line in new_output.splitlines():
                    log(f"[app] {line}")
                output_buffer.extend(new_output.splitlines())
                # Keep buffer bounded
                if len(output_buffer) > 500:
                    output_buffer = output_buffer[-500:]

        # Periodic callback
        if next_callback is not None and now >= next_callback:
            if callback_url:
                if plugin.run_command:
                    # App mode: send captured stdout
                    recent_lines = output_buffer[-20:] if output_buffer else ["(no output)"]
                    message = "\n".join(recent_lines)
                else:
                    # Sidecar mode: run status command
                    message = gather_sidecar_status(plugin, config)
                send_callback(callback_url, plugin.periodic_event, message)

            while next_callback <= now:
                next_callback += interval_seconds

        # Sleep until next event (cap at 60s to stay responsive)
        sleep_candidates: list[float] = [60.0]
        if next_callback is not None:
            sleep_candidates.append(max(0.1, next_callback - time.monotonic()))
        time.sleep(min(sleep_candidates))


# ---------------------------------------------------------------------------
# Main: hook-configure subcommand
# ---------------------------------------------------------------------------

def cmd_hook_configure(plugin: Plugin) -> int:
    """Handle the snap configure hook: validate, persist, restart the sidecar."""
    config = load_config(plugin)
    errors = validate_config(plugin, config)

    if errors:
        for err in errors:
            log_error(err)
        log_error("Validation failed. Allowing configure hook to complete so daemon can wait for valid config.")

    # Persist validated config
    persist_config(plugin, config)

    # Run setup commands that trigger on config-change
    run_setup_commands(plugin, config, trigger="config-change")

    # Restart the ct-engine sidecar so it re-reads the freshly persisted CT
    # config (callback URL / node id / deployment id) and re-registers with
    # Control Tower.
    #
    # We restart the SIDECAR, not the application daemon: the app does not
    # consume the ct-* keys, and "<snap>.<app_name>" is frequently NOT a real
    # service — app_name is the identity reported to CT and rarely matches the
    # snapcraft daemon app (e.g. "all-dev-pi-hole" vs the real "pihole-ftl").
    # Restarting a non-existent target inside a configure hook can fail the
    # whole snapd change. The sidecar app is always named "ct-engine", so this
    # target is valid in every snap. Mirrors the hermes reference and the
    # deployment plan's POST.json post_service_actions.
    snap_name = os.environ.get("SNAP_INSTANCE_NAME", os.environ.get("SNAP_NAME", plugin.app_name))
    service_name = f"{snap_name}.ct-engine"
    try:
        subprocess.run(
            ["snapctl", "restart", service_name],
            check=False,
            capture_output=True,
        )
    except Exception:
        pass

    log("Configure hook completed. ct-engine sidecar restarted.")
    return 0


# ---------------------------------------------------------------------------
# Main: auto-update lifecycle hooks (pre-refresh / post-refresh / remove)
# ---------------------------------------------------------------------------

def cmd_hook_pre_refresh(plugin: Plugin) -> int:
    """snap pre-refresh hook: tell CT an update is starting (not a stop)."""
    config = load_config(plugin)
    callback_url = config.get("ct-callback-url", "")
    if callback_url:
        snap_version = os.environ.get("SNAP_VERSION", plugin.app_version)
        send_callback(
            callback_url,
            plugin.pre_refresh_event,
            f"{plugin.app_name} update started (current: v{snap_version}).",
        )
    log("Pre-refresh hook completed.")
    return 0


def cmd_hook_post_refresh(plugin: Plugin) -> int:
    """snap post-refresh hook: tell CT the update finished successfully."""
    config = load_config(plugin)
    callback_url = config.get("ct-callback-url", "")
    if callback_url:
        snap_version = os.environ.get("SNAP_VERSION", plugin.app_version)
        send_callback(
            callback_url,
            plugin.post_refresh_event,
            f"{plugin.app_name} updated successfully (now: v{snap_version}).",
        )
    log("Post-refresh hook completed.")
    return 0


def cmd_hook_remove(plugin: Plugin) -> int:
    """snap remove hook: the app is actually being uninstalled.

    This is the ONLY place 'deployment_stop' is sent — it runs solely on
    `snap remove`, never on a stop/restart/refresh.
    """
    config = load_config(plugin)
    callback_url = config.get("ct-callback-url", "")
    if callback_url:
        send_callback(
            callback_url,
            plugin.stop_event,
            f"{plugin.app_name} removed (uninstalled).",
        )
    log("Remove hook completed.")
    return 0


# ---------------------------------------------------------------------------
# Main: status subcommand
# ---------------------------------------------------------------------------

def cmd_status(plugin: Plugin) -> int:
    """Print current config and plugin info for debugging."""
    print(f"Plugin: {plugin.app_name} v{plugin.app_version}")
    print(f"Run command: {plugin.run_command}")
    print(f"Output mode: {plugin.output_mode} (interval: {plugin.output_interval}m)")
    print(f"Setup commands: {len(plugin.setup_commands)}")
    print()

    config = load_config(plugin)
    print("Current configuration:")
    for key in list(CT_KEYS) + list(plugin.config_schema.keys()):
        value = config.get(key, "(unset)")
        schema = plugin.config_schema.get(key, {})
        required = schema.get("required", False) if isinstance(schema, dict) else False
        marker = " [REQUIRED]" if required else ""
        print(f"  {key} = {value}{marker}")

    print()
    errors = validate_config(plugin, config)
    if errors:
        print("Validation errors:")
        for err in errors:
            print(f"  ✗ {err}")
        return 1
    else:
        print("✓ Configuration is valid.")
        return 0


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def find_plugin_path() -> Path:
    """Locate the plugin.yaml file. Checks $SNAP first, then current directory."""
    snap_dir = os.environ.get("SNAP")
    if snap_dir:
        snap_path = Path(snap_dir) / "plugin.yaml"
        if snap_path.exists():
            return snap_path

    # Fallback: current directory (for development/testing)
    local_path = Path("plugin.yaml")
    if local_path.exists():
        return local_path

    # Fallback: next to this script
    script_dir = Path(__file__).parent.parent
    script_path = script_dir / "plugin.yaml"
    if script_path.exists():
        return script_path

    log_error("Cannot find plugin.yaml in $SNAP, current directory, or project root.")
    sys.exit(1)


USAGE = ("Usage: ct-engine "
         "<run|hook-configure|hook-pre-refresh|hook-post-refresh|hook-remove|status>")


def main() -> int:
    if len(sys.argv) < 2:
        print(USAGE, file=sys.stderr)
        return 1

    subcommand = sys.argv[1]
    plugin_path = find_plugin_path()
    plugin = load_plugin(plugin_path)

    if subcommand == "run":
        return cmd_run(plugin)
    elif subcommand == "hook-configure":
        return cmd_hook_configure(plugin)
    elif subcommand == "hook-pre-refresh":
        return cmd_hook_pre_refresh(plugin)
    elif subcommand == "hook-post-refresh":
        return cmd_hook_post_refresh(plugin)
    elif subcommand == "hook-remove":
        return cmd_hook_remove(plugin)
    elif subcommand == "status":
        return cmd_status(plugin)
    else:
        log_error(f"Unknown subcommand: {subcommand}")
        print(USAGE, file=sys.stderr)
        return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
