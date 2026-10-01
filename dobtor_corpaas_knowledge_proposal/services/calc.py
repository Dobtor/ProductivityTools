# -*- coding: utf-8 -*-
"""估算與校正的純函式（不 import odoo，可獨立測試）。"""
import json
import math
import re

_NUMBER = re.compile(r'(\d[\d,]*(?:\.\d+)?)')


def effort_days(base_days, per_unit_days, unit_size, driver_qty):
    """days = base_days + ceil(driver_qty / unit_size) × per_unit_days。

    ★ unit_size ≤ 0 視為 1（避免除以零）；driver_qty ≤ 0 只算基礎天數。
    """
    qty = max(0.0, float(driver_qty or 0.0))
    size = float(unit_size or 0.0)
    if size <= 0:
        size = 1.0
    units = math.ceil(qty / size - 1e-9) if qty else 0
    return float(base_days or 0.0) + units * float(per_unit_days or 0.0)


def driver_units(unit_size, driver_qty):
    qty = max(0.0, float(driver_qty or 0.0))
    size = float(unit_size or 0.0) or 1.0
    return math.ceil(qty / size - 1e-9) if qty else 0


def observed_base(actual_days, per_unit_days, unit_size, driver_qty):
    """由實際人天反推「基礎天數」：扣掉依驅動量的那一段，下限 0。"""
    driver_part = driver_units(unit_size, driver_qty) * float(per_unit_days or 0.0)
    return max(0.0, float(actual_days or 0.0) - driver_part)


def moving_average(seed, observations, window):
    """簡單移動平均：以種子值（初始 base_days）打底，取最後 window 個樣本的平均。

    ★ 種子值算一個樣本：第一次校正不會被單一專案整個拉走。
    """
    samples = [float(seed or 0.0)] + [float(o) for o in observations]
    window = max(1, int(window or 1))
    tail = samples[-window:]
    return round(sum(tail) / len(tail), 2)


def parse_third_party_monthly(text, default_amount):
    """能力的「第三方費用說明」→ 每月金額。

    一行一項；行內最後一個數字視為月費（例：`簡訊 NT$1,200/月`）。
    有內容但沒寫金額的行，以設定頁的第三方預設月費估。
    回傳 (金額, 是否含預設估值)。
    """
    total, guessed = 0.0, False
    for line in (text or '').splitlines():
        line = line.strip()
        if not line:
            continue
        nums = _NUMBER.findall(line)
        if nums:
            total += float(nums[-1].replace(',', ''))
        else:
            total += float(default_amount or 0.0)
            guessed = True
    return total, guessed


def parse_resource_profile(text):
    """capability.resource_profile（JSON）→ dict；壞 JSON 當作沒填。"""
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def infra_monthly_for_profile(profile, records, cost_per_gb, cost_per_worker, worker_mb):
    """單一能力的基礎設施月成本（相對權重 × 單價）。

    storage_per_record_kb × 主資料筆數 → GB × 每 GB 月成本；
    extra_worker_mb ÷ worker_mb ＋ heavy_cron（半個 worker）→ worker 數 × 每 worker 月成本。
    """
    kb = float(profile.get('storage_per_record_kb') or 0.0)
    gb = kb * float(records or 0) / 1024.0 / 1024.0
    workers = float(profile.get('extra_worker_mb') or 0.0) / float(worker_mb or 512)
    if profile.get('heavy_cron'):
        workers += 0.5
    return gb * float(cost_per_gb or 0.0) + workers * float(cost_per_worker or 0.0)


def periods_per_year(rule_type):
    return {'daily': 365, 'weekly': 52, 'monthly': 12, 'quarterly': 4,
            'yearly': 1}.get(rule_type or '', 12)
