/**
 * WorkerAlertCooldown — Sprint 342。
 *
 * Sprint 337 WorkerAlertEvaluator 之後深推。原 evaluator 每個觸發條件都產生
 * 一個 AlertEvent；caller 接 Slack/email 時可能會被「同一個 rule 連發 10 次」
 * 噪音淹沒。本 sprint 補：
 *
 *   - 依 rule+severity 做 cooldown（N ms 內同 key 只通報一次）
 *   - 提供 stats 看「壓制了多少 alert」
 *   - reset 用於測試 / 手動重置
 *
 * 紀律 #18 scope-down：
 *   - 純記憶體 cooldown state；caller 自負持久化
 *   - 不接 Slack/email/log（caller 拿 filtered events 自接）
 *   - 不做指數遞增 cooldown / circuit-breaker（用 Sprint 317 組合）
 *
 * 紀律 #21：純資料 transformation；不污染既有 worker pipeline。
 */

import type { AlertEvent } from './WorkerAlertEvaluator';

export interface WorkerAlertCooldownOptions {
  /** 同 key cooldown 時間（ms）；預設 60000 = 1min */
  cooldownMs?: number;
  /** Caller 注入 now() 給可測試的時鐘；缺省 Date.now */
  now?: () => number;
}

export interface CooldownStats {
  /** 通過 cooldown 的 alert 數 */
  passed: number;
  /** 被 cooldown 抑制掉的 alert 數 */
  suppressed: number;
  /** 當前 cooldown 中的 key 數 */
  activeKeys: number;
}

export class WorkerAlertCooldown {
  private readonly cooldownMs: number;
  private readonly now: () => number;
  /** key → 上次通過的時間 ms */
  private readonly lastPassed = new Map<string, number>();
  private passedCount = 0;
  private suppressedCount = 0;

  constructor(opts: WorkerAlertCooldownOptions = {}) {
    this.cooldownMs = opts.cooldownMs ?? 60000;
    if (this.cooldownMs <= 0) {
      throw new Error('[WorkerAlertCooldown] cooldownMs must be > 0');
    }
    this.now = opts.now ?? (() => Date.now());
  }

  /**
   * 接收 events、回過濾後（cooldown 通過的）events。
   *
   * Key = ruleName + severity（caller 想用更細的 key 自己包另一層）。
   */
  filter(events: ReadonlyArray<AlertEvent>): AlertEvent[] {
    const now = this.now();
    const out: AlertEvent[] = [];
    for (const e of events) {
      const key = `${e.ruleName}|${e.severity}`;
      const lastAt = this.lastPassed.get(key);
      if (lastAt !== undefined && now - lastAt < this.cooldownMs) {
        this.suppressedCount += 1;
        continue;
      }
      this.lastPassed.set(key, now);
      this.passedCount += 1;
      out.push(e);
    }
    return out;
  }

  /**
   * 查 caller 是否會被 cooldown 抑制（不更新 state）。
   */
  isInCooldown(ruleName: string, severity: AlertEvent['severity']): boolean {
    const key = `${ruleName}|${severity}`;
    const lastAt = this.lastPassed.get(key);
    if (lastAt === undefined) return false;
    return this.now() - lastAt < this.cooldownMs;
  }

  /** 清掉所有 cooldown state（測試 / 手動 reset 用）。 */
  reset(): void {
    this.lastPassed.clear();
    this.passedCount = 0;
    this.suppressedCount = 0;
  }

  /**
   * 把過期的 cooldown key 清掉（caller idle-time cleanup）。
   * 回清掉的 key 數。
   */
  purgeExpired(): number {
    const now = this.now();
    let count = 0;
    for (const [k, at] of this.lastPassed) {
      if (now - at >= this.cooldownMs) {
        this.lastPassed.delete(k);
        count += 1;
      }
    }
    return count;
  }

  getStats(): CooldownStats {
    return {
      passed: this.passedCount,
      suppressed: this.suppressedCount,
      activeKeys: this.lastPassed.size,
    };
  }
}
