#!/usr/bin/env python
from __future__ import annotations

import argparse
import base64
import datetime
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


CONFIG_ALIASES = {
    "base_url": ("BASE_URL", "OPENAI_BASE_URL", "base_url"),
    "api_key": ("API_KEY", "OPENAI_API_KEY", "api_key"),
    "image_model": ("IMAGE_MODEL", "OPENAI_IMAGE_MODEL", "image_model"),
    "out_dir": ("OUT_DIR", "IMAGEGEN_OUT_DIR", "out_dir"),
}
REQUIRED_KEYS = tuple(CONFIG_ALIASES)
QUALITY_VALUES = {"low", "medium", "high", "auto"}
FORMAT_VALUES = {"png", "jpeg", "jpg", "webp"}
KNOWN_SIZES = {
    "auto",
    "1024x1024",
    "1536x1024",
    "1024x1536",
    "2048x2048",
    "2048x1152",
    "3840x2160",
    "2160x3840",
}

CHINESE_ONLY_INSTRUCTION = (
    "\u753b\u9762\u4e2d\u7684\u53d9\u8ff0\u6027\u6587\u5b57\u548c\u7248\u5f0f\u6807\u7b7e\u4f18\u5148\u4f7f\u7528\u7b80\u4f53\u4e2d\u6587\u3002"
    "\u4e0d\u8981\u51fa\u73b0\u4e71\u7801\u3001\u968f\u673a\u5b57\u6bcd\u6216\u65e0\u610f\u4e49\u4f2a\u6587\u5b57\u3002"
    "\u5982\u679c\u6e90\u5185\u5bb9\u660e\u786e\u8981\u6c42\u4fdd\u7559\u82f1\u6587\u7f29\u5199\u3001\u6a21\u578b\u540d\u3001\u7f16\u53f7\u3001\u4ee3\u7801\u6807\u8bc6\u6216\u5355\u4f4d\uff0c"
    "\u4f8b\u5982 API\u3001AI\u3001TrafficVLM\u3001G40\u3001CSV\u3001km/h\uff0c\u8bf7\u6309\u6e90\u6587\u672c\u4fdd\u7559\u3002"
    "\u5176\u4ed6\u975e\u6e90\u5185\u5bb9\u7684\u82f1\u6587\u8bf4\u660e\u5c3d\u91cf\u6539\u5199\u4e3a\u7b80\u4f53\u4e2d\u6587\u3002"
    "\u6587\u5b57\u6807\u7b7e\u8981\u77ed\uff0c\u5b57\u53f7\u8981\u5927\uff0c\u6e05\u6670\u53ef\u8bfb\u3002"
)


def parse_dotenv_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def parse_env_file(path: Path) -> dict[str, str]:
    alias_to_key = {
        alias: canonical
        for canonical, aliases in CONFIG_ALIASES.items()
        for alias in aliases
    }
    config: dict[str, str] = {}
    api_key_count = 0

    if path.exists():
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            raw_key, raw_value = line.split("=", 1)
            key = raw_key.strip()
            canonical = alias_to_key.get(key)
            if not canonical:
                continue
            value = parse_dotenv_value(raw_value)
            if not value:
                continue
            if canonical == "api_key":
                api_key_count += 1
            config[canonical] = value

    for canonical, aliases in CONFIG_ALIASES.items():
        if config.get(canonical):
            continue
        for alias in aliases:
            value = os.environ.get(alias)
            if value:
                config[canonical] = value
                break

    missing = [key for key in REQUIRED_KEYS if not config.get(key)]
    if missing:
        if path.exists():
            source_hint = f"Missing required key(s) in {path}"
        else:
            source_hint = f"Missing env file: {path}"
        expected = ", ".join("/".join(CONFIG_ALIASES[key]) for key in missing)
        raise SystemExit(
            f"{source_hint}: {', '.join(missing)}. "
            f"Copy .env.sample to .env or set these environment variables: {expected}."
        )

    config["_api_key_count"] = str(api_key_count)
    return config


def ensure_gitignore(workspace: Path) -> None:
    gitignore = workspace / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    lines = {line.strip() for line in existing.splitlines()}
    wanted = [".env", ".env.*", "!.env.sample", ".imagegen-preview-runs.jsonl"]
    missing = [line for line in wanted if line not in lines]
    if not missing:
        return
    suffix = "" if not existing or existing.endswith(("\n", "\r\n")) else "\n"
    block = "# imagegen-preview secrets\n" + "\n".join(missing) + "\n"
    gitignore.write_text(existing + suffix + block, encoding="utf-8")


def normalize_format(value: str | None, out_path: Path) -> str:
    if value:
        fmt = value.lower()
    else:
        suffix = out_path.suffix.lower().lstrip(".")
        fmt = suffix if suffix in FORMAT_VALUES else "png"
    if fmt == "jpg":
        return "jpeg"
    if fmt not in FORMAT_VALUES:
        raise SystemExit("--format must be one of png, jpeg, jpg, or webp.")
    return fmt


def normalize_out_path(out_path: Path, fmt: str) -> Path:
    suffix = ".jpg" if fmt == "jpeg" else f".{fmt}"
    if not out_path.suffix:
        return out_path.with_suffix(suffix)
    return out_path


def validate_size(size: str) -> None:
    if size in KNOWN_SIZES:
        return
    match = re.fullmatch(r"(\d+)x(\d+)", size)
    if not match:
        raise SystemExit("--size must be auto or WIDTHxHEIGHT.")
    width, height = int(match.group(1)), int(match.group(2))
    short = min(width, height)
    long = max(width, height)
    pixels = width * height
    if width % 16 or height % 16:
        raise SystemExit("--size width and height must both be multiples of 16.")
    if long > 3840:
        raise SystemExit("--size max side must be <= 3840.")
    if short == 0 or long / short > 3:
        raise SystemExit("--size aspect ratio must be <= 3:1.")
    if pixels < 655_360 or pixels > 8_294_400:
        raise SystemExit("--size total pixels must be between 655360 and 8294400.")


def response_preview(text: str, limit: int = 1200) -> str:
    return text[:limit].replace("\r", "\\r").replace("\n", "\\n")


def transient_error_message(exc: BaseException) -> str:
    return f"{exc.__class__.__name__}: {exc}"


def fetch_url(url: str, timeout: int) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


def maybe_decode_base64(value: str) -> bytes | None:
    raw = value.strip()
    if raw.startswith("data:image"):
        raw = raw.split(",", 1)[1]
    compact = re.sub(r"\s+", "", raw)
    if len(compact) < 1000 or not re.fullmatch(r"[A-Za-z0-9+/=]+", compact):
        return None
    return base64.b64decode(compact)


def extract_image_bytes(data: Any, timeout: int) -> bytes:
    if not isinstance(data, dict):
        raise RuntimeError("Image response is not a JSON object.")

    items = data.get("data")
    if isinstance(items, list) and items:
        item = items[0]
        if isinstance(item, dict):
            for field in ("b64_json", "base64", "image"):
                value = item.get(field)
                if isinstance(value, str):
                    decoded = maybe_decode_base64(value)
                    if decoded:
                        return decoded
            url = item.get("url")
            if isinstance(url, str) and url:
                return fetch_url(url, timeout)

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        content: Any = ""
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content", "")
            content = content or first.get("text", "")
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        if isinstance(content, str):
            decoded = maybe_decode_base64(content)
            if decoded:
                return decoded
            match = re.search(r"https?://[^\s)\"']+", content)
            if match:
                return fetch_url(match.group(0), timeout)

    raise RuntimeError(
        "No image bytes found in response. Top-level keys: "
        + ", ".join(str(key) for key in data.keys())
    )


def build_http_payload(args: argparse.Namespace, config: dict[str, str], fmt: str) -> dict[str, Any]:
    prompt = args.prompt
    if args.chinese_only:
        prompt = f"{prompt}\n\n{CHINESE_ONLY_INSTRUCTION}"
    return {
        "model": config["image_model"],
        "prompt": prompt,
        "n": args.n,
        "size": args.size,
        "quality": args.quality,
        "format": fmt,
    }


def print_safe_config(config: dict[str, str], out_path: Path, transport: str) -> None:
    print(f"Model: {config['image_model']}")
    print(f"Output path: {out_path}")
    print(f"Transport: {transport}")
    print(f"Base URL configured: {bool(config['base_url'])}")
    print("API key configured: True")
    if int(config.get("_api_key_count", "0")) > 1:
        print("Warning: multiple API key entries found; using the last one.")


def risk_warnings(args: argparse.Namespace, config: dict[str, str], transport: str) -> list[str]:
    warnings: list[str] = []
    host = urllib.parse.urlparse(config["base_url"]).netloc.lower()
    model = config["image_model"].lower()
    if transport == "http" and "yunwu.ai" in host and model == "gpt-image-2" and args.quality == "high":
        warnings.append(
            "yunwu.ai gpt-image-2 quality=high has been observed to disconnect after billing; "
            "prefer quality=medium for reliable paid runs."
        )
    if args.retries > 0:
        warnings.append(
            "HTTP retries may create additional paid image requests if the upstream processed "
            "a disconnected attempt."
        )
    return warnings


def default_log_path() -> Path:
    return Path.cwd() / ".imagegen-preview-runs.jsonl"


def write_run_log(
    args: argparse.Namespace,
    config: dict[str, str],
    out_path: Path,
    fmt: str,
    endpoint: str,
    status: str,
    elapsed_seconds: float,
    attempts: int,
    *,
    error: str | None = None,
    byte_count: int | None = None,
) -> None:
    if args.no_log:
        return
    log_path = Path(args.log_file) if args.log_file else default_log_path()
    if not log_path.is_absolute():
        log_path = Path.cwd() / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    parsed = urllib.parse.urlparse(config["base_url"])
    entry = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "transport": "http",
        "provider_host": parsed.netloc,
        "endpoint_path": urllib.parse.urlparse(endpoint).path,
        "model": config["image_model"],
        "size": args.size,
        "quality": args.quality,
        "format": fmt,
        "n": args.n,
        "timeout_seconds": args.timeout,
        "retries": args.retries,
        "attempts": attempts,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "output": str(out_path),
        "bytes": byte_count,
        "prompt_chars": len(args.prompt),
        "error": error,
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def open_url_with_retries(
    endpoint: str,
    request_data: bytes,
    headers: dict[str, str],
    timeout: int,
    retries: int,
    retry_delay: float,
) -> tuple[str, int]:
    attempts = retries + 1
    retryable_http = {408, 409, 425, 429, 500, 502, 503, 504}
    transient_errors = (
        TimeoutError,
        socket.timeout,
        ConnectionResetError,
        http.client.RemoteDisconnected,
        http.client.IncompleteRead,
        urllib.error.URLError,
    )

    for attempt in range(1, attempts + 1):
        if attempts > 1:
            print(f"HTTP attempt {attempt}/{attempts}; timeout={timeout}s")
        request = urllib.request.Request(
            endpoint,
            data=request_data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8"), attempt
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            if exc.code in retryable_http and attempt < attempts:
                print(
                    f"Image API HTTP {exc.code}; retrying in {retry_delay}s: "
                    f"{response_preview(text, 300)}"
                )
                time.sleep(retry_delay)
                continue
            raise SystemExit(f"Image API HTTP {exc.code}: {response_preview(text)}")
        except transient_errors as exc:
            if attempt < attempts:
                print(
                    f"Image API connection failed; retrying in {retry_delay}s: "
                    f"{transient_error_message(exc)}"
                )
                time.sleep(retry_delay)
                continue
            raise SystemExit(
                "Image API connection failed after "
                f"{attempts} attempt(s), timeout={timeout}s: "
                f"{transient_error_message(exc)}"
            )

    raise SystemExit("Image API request failed unexpectedly.")


def generate_http(
    args: argparse.Namespace,
    config: dict[str, str],
    out_path: Path,
    fmt: str,
) -> int:
    endpoint = config["base_url"].rstrip("/") + "/images/generations"
    payload = build_http_payload(args, config, fmt)
    print_safe_config(config, out_path, "http")
    print(f"HTTP timeout: {args.timeout}s")
    print(f"Retries: {args.retries}")
    for warning in risk_warnings(args, config, "http"):
        print(f"Warning: {warning}")
    if args.dry_run:
        print(
            json.dumps(
                {
                    "endpoint": endpoint,
                    "payload": payload,
                    "output": str(out_path),
                    "timeout_seconds": args.timeout,
                    "retries": args.retries,
                    "retry_delay_seconds": args.retry_delay,
                    "paid_retry_acknowledged": args.allow_paid_retry,
                    "log_file": None if args.no_log else str(Path(args.log_file) if args.log_file else default_log_path()),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    request_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Authorization": "Bearer " + config["api_key"],
        "Content-Type": "application/json",
    }
    started = time.monotonic()
    attempts_used = args.retries + 1
    try:
        body, attempts_used = open_url_with_retries(
            endpoint,
            request_data,
            headers,
            args.timeout,
            args.retries,
            args.retry_delay,
        )
    except SystemExit as exc:
        write_run_log(
            args,
            config,
            out_path,
            fmt,
            endpoint,
            "failed",
            time.monotonic() - started,
            attempts_used,
            error=str(exc),
        )
        raise

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        message = f"Image API returned non-JSON response: {response_preview(body)}"
        write_run_log(
            args,
            config,
            out_path,
            fmt,
            endpoint,
            "failed",
            time.monotonic() - started,
            attempts_used,
            error=f"{exc.__class__.__name__}: {message}",
        )
        raise SystemExit(message)

    try:
        image_bytes = extract_image_bytes(data, args.timeout)
    except Exception as exc:
        message = f"Could not extract image from response: {exc}; preview={response_preview(body)}"
        write_run_log(
            args,
            config,
            out_path,
            fmt,
            endpoint,
            "failed",
            time.monotonic() - started,
            attempts_used,
            error=message,
        )
        raise SystemExit(
            message
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(image_bytes)
    write_run_log(
        args,
        config,
        out_path,
        fmt,
        endpoint,
        "success",
        time.monotonic() - started,
        attempts_used,
        byte_count=len(image_bytes),
    )
    print(
        json.dumps(
            {
                "success": True,
                "model": config["image_model"],
                "output": str(out_path),
                "bytes": len(image_bytes),
                "size": args.size,
                "quality": args.quality,
                "format": fmt,
                "transport": "http",
                "timeout_seconds": args.timeout,
                "retries": args.retries,
            },
            ensure_ascii=False,
        )
    )
    return 0


def generate_cli(
    args: argparse.Namespace,
    config: dict[str, str],
    out_path: Path,
    fmt: str,
) -> int:
    imagegen_script = (
        Path.home()
        / ".codex"
        / "skills"
        / ".system"
        / "imagegen"
        / "scripts"
        / "image_gen.py"
    )
    if not imagegen_script.exists():
        raise SystemExit(f"Cannot find system imagegen CLI: {imagegen_script}")

    child_env = os.environ.copy()
    child_env["OPENAI_BASE_URL"] = config["base_url"]
    child_env["OPENAI_API_KEY"] = config["api_key"]

    prompt = args.prompt
    if args.chinese_only:
        prompt = f"{prompt}\n\n{CHINESE_ONLY_INSTRUCTION}"

    command = [
        sys.executable,
        str(imagegen_script),
        "generate",
        "--model",
        config["image_model"],
        "--prompt",
        prompt,
        "--size",
        args.size,
        "--quality",
        args.quality,
        "--output-format",
        fmt,
        "--out",
        str(out_path),
        "--force",
    ]
    if args.dry_run:
        command.append("--dry-run")

    print_safe_config(config, out_path, "cli")
    result = subprocess.run(command, env=child_env)
    return result.returncode


def choose_transport(requested: str, config: dict[str, str]) -> str:
    if requested != "auto":
        return requested
    base_url = config["base_url"].lower()
    model = config["image_model"].lower()
    if "yunwu.ai" in base_url or model == "gpt-image-2":
        return "http"
    return "cli"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate images with project-local .env settings."
    )
    parser.add_argument("--env", default=".env", help="Path to the dotenv config file.")
    parser.add_argument("--prompt", required=True, help="Image prompt.")
    parser.add_argument("--out", required=True, help="Output filename or path.")
    parser.add_argument(
        "--size",
        default="auto",
        help="Image size, for example auto, 1024x1024, or 3840x2160.",
    )
    parser.add_argument("--quality", default="low", choices=sorted(QUALITY_VALUES), help="Image quality.")
    parser.add_argument(
        "--format",
        default=None,
        help="Image format: png, jpeg, jpg, or webp. Defaults from --out or png.",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=1,
        help="Number of images to request. This wrapper saves the first image.",
    )
    parser.add_argument("--timeout", type=int, default=300, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--retries",
        type=int,
        default=0,
        help=(
            "Retry transient HTTP disconnects or timeout-like failures this many times. "
            "Use with care because a disconnected upstream may still process the first request."
        ),
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=5.0,
        help="Seconds to wait before a transient retry.",
    )
    parser.add_argument(
        "--allow-paid-retry",
        action="store_true",
        help="Allow live retries that may create additional paid upstream image requests.",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Safe JSONL run log path. Defaults to .imagegen-preview-runs.jsonl in the workspace.",
    )
    parser.add_argument("--no-log", action="store_true", help="Disable the safe JSONL run log.")
    parser.add_argument(
        "--transport",
        choices=("auto", "http", "cli"),
        default="auto",
        help="Use direct HTTP, system CLI, or auto-select.",
    )
    parser.add_argument(
        "--chinese-only",
        action="store_true",
        help="Append an instruction that visible explanatory image text should be Simplified Chinese.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print payload and output path without making the API call.")
    parser.add_argument("--no-gitignore", action="store_true", help="Do not update .gitignore.")
    args = parser.parse_args()

    if not (1 <= args.n <= 10):
        raise SystemExit("--n must be between 1 and 10.")
    if args.timeout < 1:
        raise SystemExit("--timeout must be >= 1.")
    if args.retries < 0:
        raise SystemExit("--retries must be >= 0.")
    if args.retry_delay < 0:
        raise SystemExit("--retry-delay must be >= 0.")
    if args.retries > 0 and not args.dry_run and not args.allow_paid_retry:
        raise SystemExit(
            "--retries can create additional paid image requests when the upstream disconnects "
            "after processing. Re-run with --allow-paid-retry only if the user accepts that risk."
        )
    validate_size(args.size)

    workspace = Path.cwd()
    env_path = Path(args.env)
    if not env_path.is_absolute():
        env_path = workspace / env_path

    config = parse_env_file(env_path)
    if config["api_key"].lower().startswith("bearer "):
        raise SystemExit("API_KEY should contain only the token, not the 'Bearer ' prefix.")
    if not args.no_gitignore:
        ensure_gitignore(workspace)

    out_dir = Path(config["out_dir"])
    if not out_dir.is_absolute():
        out_dir = workspace / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_out_path = Path(args.out)
    if not raw_out_path.is_absolute():
        raw_out_path = out_dir / raw_out_path
    fmt = normalize_format(args.format, raw_out_path)
    out_path = normalize_out_path(raw_out_path, fmt)

    transport = choose_transport(args.transport, config)
    if transport == "http":
        return generate_http(args, config, out_path, fmt)
    return generate_cli(args, config, out_path, fmt)


if __name__ == "__main__":
    raise SystemExit(main())
