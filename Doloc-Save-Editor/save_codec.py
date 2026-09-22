"""Read and write encrypted Doloc Town save files."""

from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad


SAVE_PREFIX = "DOLOC-TOWN:"
AES_KEY = b"lets-mix-lives-and-change-drinks"
AES_IV = b"welcome-to-doloc"
REQUIRED_SECTIONS = ("farmData", "baseData")


class SaveFormatError(ValueError):
    """Raised when a file is not a supported or valid Doloc Town save."""


@dataclass(frozen=True)
class WriteResult:
    output_path: Path
    backup_path: Path | None
    byte_count: int


def _validate_root(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise SaveFormatError("JSON 根节点必须是对象。")
    missing = [name for name in REQUIRED_SECTIONS if name not in data]
    if missing:
        raise SaveFormatError(f"缺少必要存档区段：{', '.join(missing)}")
    if not isinstance(data["farmData"], dict) or not isinstance(data["baseData"], dict):
        raise SaveFormatError("farmData 和 baseData 必须是对象。")
    return data


def parse_json_text(json_text: str) -> dict[str, Any]:
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise SaveFormatError(
            f"JSON 格式错误：第 {exc.lineno} 行，第 {exc.colno} 列：{exc.msg}"
        ) from exc
    return _validate_root(data)


def decrypt_save_text(save_text: str) -> str:
    if not save_text.startswith(SAVE_PREFIX):
        raise SaveFormatError(f"文件缺少前缀 {SAVE_PREFIX}")

    payload = save_text[len(SAVE_PREFIX) :]
    try:
        ciphertext = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SaveFormatError("存档的 Base64 数据无效。") from exc

    if not ciphertext or len(ciphertext) % AES.block_size:
        raise SaveFormatError("加密数据长度无效。")

    try:
        cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
        plaintext = unpad(cipher.decrypt(ciphertext), AES.block_size)
        json_text = plaintext.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise SaveFormatError("AES 解密失败，文件可能损坏或来自不兼容版本。") from exc

    parse_json_text(json_text)
    return json_text


def encrypt_json_text(json_text: str) -> str:
    parse_json_text(json_text)
    plaintext = json_text.encode("utf-8")
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    ciphertext = cipher.encrypt(pad(plaintext, AES.block_size))
    return SAVE_PREFIX + base64.b64encode(ciphertext).decode("ascii")


def load_save(path: str | os.PathLike[str]) -> tuple[dict[str, Any], str]:
    source = Path(path)
    try:
        save_text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SaveFormatError(f"无法读取存档：{exc}") from exc
    json_text = decrypt_save_text(save_text)
    return parse_json_text(json_text), json_text


def format_json(data: dict[str, Any]) -> str:
    _validate_root(data)
    return json.dumps(data, ensure_ascii=False, indent=2)


def compact_json(data: dict[str, Any]) -> str:
    _validate_root(data)
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _backup_path(target: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = target.with_name(f"{target.name}.{stamp}.bak")
    counter = 1
    while candidate.exists():
        candidate = target.with_name(f"{target.name}.{stamp}-{counter}.bak")
        counter += 1
    return candidate


def write_save(
    path: str | os.PathLike[str],
    data: dict[str, Any],
    *,
    backup_existing: bool = True,
) -> WriteResult:
    target = Path(path)
    if not target.parent.exists():
        raise SaveFormatError(f"目标目录不存在：{target.parent}")

    json_text = compact_json(data)
    save_text = encrypt_json_text(json_text)
    backup: Path | None = None

    if target.exists() and backup_existing:
        backup = _backup_path(target)
        try:
            shutil.copy2(target, backup)
        except OSError as exc:
            raise SaveFormatError(f"创建备份失败：{exc}") from exc

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="ascii",
            newline="",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as temporary:
            temporary.write(save_text)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, target)
        temporary_name = None
    except OSError as exc:
        raise SaveFormatError(f"写入存档失败：{exc}") from exc
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass

    try:
        verified_data, _ = load_save(target)
        if verified_data != data:
            raise SaveFormatError("写入后的回读验证失败。")
    except Exception as exc:
        try:
            if backup is not None:
                shutil.copy2(backup, target)
            else:
                target.unlink(missing_ok=True)
        except OSError as rollback_exc:
            raise SaveFormatError(
                f"回读验证失败，且自动回滚失败：{rollback_exc}"
            ) from exc
        if isinstance(exc, SaveFormatError):
            raise
        raise SaveFormatError(f"写入后的回读验证失败：{exc}") from exc

    return WriteResult(target, backup, target.stat().st_size)
