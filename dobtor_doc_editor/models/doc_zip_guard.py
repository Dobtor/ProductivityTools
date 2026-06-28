"""DOCX / ODT 上傳的 Zip Bomb 防護工具。

威脅模型：
    攻擊者上傳一個 1KB 的高壓縮率 zip 檔，解壓後變成數 GB（甚至 TB），
    塞爆 RAM / disk / 處理時間，造成 DoS。

防禦三道閘門（任一觸發即拒絕）：
    1. 原檔大小（uncompressed_input_max_bytes）
    2. 解壓後總大小（uncompressed_output_max_bytes）
    3. 內部 entry 數量（max_entries）

使用方式：
    from .doc_zip_guard import safe_open_docx_zip, ZipBombError

    raw_bytes = uploaded.read()
    try:
        zf = safe_open_docx_zip(raw_bytes)
    except ZipBombError as e:
        return {'error': str(e)}
"""

import io
import zipfile

from odoo import _
from odoo.exceptions import UserError

# ── 預設限制 ──────────────────────────────────────────────────────────
# 數值經驗值：
#   - 一般 DOCX 檔案壓縮後 < 5MB；含大量內嵌圖片可能到 30-40MB
#   - 50MB 上限可涵蓋 99% 合理用例，惡意 zip bomb 會在此被擋
DEFAULT_INPUT_MAX_BYTES = 50 * 1024 * 1024            # 50MB 原檔上限
DEFAULT_OUTPUT_MAX_BYTES = 200 * 1024 * 1024          # 200MB 解壓總大小上限
DEFAULT_MAX_ENTRIES = 1000                            # 1000 個 entry 上限
DEFAULT_MAX_RATIO = 100                               # 任一檔案壓縮比 100x 上限


class ZipBombError(UserError):
    """偵測到可能的 zip bomb 攻擊或檔案過大。"""
    pass


def assert_input_size(
    raw_bytes,
    max_bytes=DEFAULT_INPUT_MAX_BYTES,
):
    """檢查原檔位元組大小。

    Args:
        raw_bytes: bytes — 上傳的原始檔案內容
        max_bytes: int — 允許上限

    Raises:
        ZipBombError: 超過上限
    """
    size = len(raw_bytes)
    if size > max_bytes:
        raise ZipBombError(_(
            "上傳檔案過大（%(size).1f MB），上限為 %(limit).1f MB。"
        ) % {
            'size': size / (1024 * 1024),
            'limit': max_bytes / (1024 * 1024),
        })


def inspect_zip_safe(
    raw_bytes,
    max_entries=DEFAULT_MAX_ENTRIES,
    max_total_uncompressed=DEFAULT_OUTPUT_MAX_BYTES,
    max_ratio=DEFAULT_MAX_RATIO,
):
    """檢查 zip 結構安全性（不解壓）。

    讀取中央目錄的 file_size 而非實際解壓，速度快且無 DoS 風險。
    此函式為唯讀檢查；通過後再用 safe_open_docx_zip() 取得 ZipFile。

    Args:
        raw_bytes: bytes — zip 檔案內容
        max_entries: int — 允許的 entry 數量上限
        max_total_uncompressed: int — 解壓後總大小上限
        max_ratio: int — 單一 entry 的最大壓縮比（防 bomb 條件 2）

    Returns:
        dict — {entry_count, total_uncompressed, total_compressed}

    Raises:
        ZipBombError: 任一閘門觸發
        zipfile.BadZipFile: 不是合法 zip
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw_bytes), 'r')
    except zipfile.BadZipFile:
        raise ZipBombError(_("檔案不是合法的 ZIP / DOCX 格式。"))

    try:
        infos = zf.infolist()
        entry_count = len(infos)
        if entry_count > max_entries:
            raise ZipBombError(_(
                "壓縮檔內 entry 數量過多（%(n)d 個），上限為 %(limit)d。"
            ) % {'n': entry_count, 'limit': max_entries})

        total_uncompressed = 0
        total_compressed = 0
        for info in infos:
            total_uncompressed += info.file_size
            total_compressed += info.compress_size

            if total_uncompressed > max_total_uncompressed:
                raise ZipBombError(_(
                    "解壓後總大小超過上限（>%(limit).1f MB）— 疑似 zip bomb。"
                ) % {'limit': max_total_uncompressed / (1024 * 1024)})

            # 單檔壓縮比檢查（防止單一 entry 即為 bomb）
            if info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > max_ratio and info.file_size > 1024 * 1024:
                    # 只對 >1MB 的檔案檢查比例（小檔案高比例正常，例如純文字）
                    raise ZipBombError(_(
                        "Entry「%(name)s」壓縮比異常（%(ratio).0fx）— 疑似 zip bomb。"
                    ) % {'name': info.filename, 'ratio': ratio})

        return {
            'entry_count': entry_count,
            'total_uncompressed': total_uncompressed,
            'total_compressed': total_compressed,
        }
    finally:
        zf.close()


def safe_open_docx_zip(
    raw_bytes,
    input_max_bytes=DEFAULT_INPUT_MAX_BYTES,
    output_max_bytes=DEFAULT_OUTPUT_MAX_BYTES,
    max_entries=DEFAULT_MAX_ENTRIES,
):
    """檢查 + 開啟 DOCX zip 的安全包裝。

    通過所有閘門後回傳一個可讀的 ZipFile（呼叫方負責 close）。

    Args:
        raw_bytes: bytes — 上傳的 DOCX 檔案內容
        input_max_bytes: int — 原檔大小上限（預設 50MB）
        output_max_bytes: int — 解壓總大小上限（預設 200MB）
        max_entries: int — entry 數量上限（預設 1000）

    Returns:
        zipfile.ZipFile — 已開啟、可讀的物件

    Raises:
        ZipBombError: 任一安全閘門觸發
    """
    assert_input_size(raw_bytes, input_max_bytes)
    inspect_zip_safe(
        raw_bytes,
        max_entries=max_entries,
        max_total_uncompressed=output_max_bytes,
    )
    # 通過檢查 → 開 ZipFile 給呼叫方
    return zipfile.ZipFile(io.BytesIO(raw_bytes), 'r')
