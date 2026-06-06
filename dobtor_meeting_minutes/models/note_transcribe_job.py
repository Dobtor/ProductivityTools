# -*- coding: utf-8 -*-
"""轉錄 Job 佇列模型

提供持久化的工作佇列，支援：
- 崩潰生還（at-least-once）：Odoo 重啟後 pending jobs 仍存在
- Atomic 認領：多個 worker 用 PostgreSQL FOR UPDATE SKIP LOCKED 安全競爭
- Self-healing：stale running jobs 被 cleanup cron 重設為 pending
- 觀測性：Dashboard 可看所有進行中/失敗工作

設計哲學：不取代現有 thread 即時處理，而是作為持久化層：
- action_transcribe 先 create Job（commit），再 spawn thread
- Thread 若立即失敗/死亡，job 仍在佇列
- Cron 定期 claim pending jobs，重啟 thread 處理
"""
import logging
import os

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class NoteTranscribeJob(models.Model):
    _name = 'note.transcribe.job'
    _description = 'Transcription Background Job'
    _order = 'priority desc, scheduled_at, id'

    recording_id = fields.Many2one(
        'note.recording',
        required=True,
        ondelete='cascade',
        index=True,
    )
    note_id = fields.Many2one(
        'note.note',
        related='recording_id.note_id',
        store=True,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        index=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Requested By',
        default=lambda self: self.env.user,
    )

    state = fields.Selection([
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('done', 'Done'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ], default='pending', required=True, index=True)

    priority = fields.Integer(default=10, index=True)
    scheduled_at = fields.Datetime(
        default=fields.Datetime.now,
        required=True, index=True,
        help='Job becomes eligible at this time (for delayed retry).',
    )
    picked_at = fields.Datetime(help='When a worker atomically claimed this job.')
    started_at = fields.Datetime()
    ended_at = fields.Datetime()
    worker_pid = fields.Integer()

    error_message = fields.Text()
    log_id = fields.Many2one(
        'note.transcribe.log',
        string='Final Log',
        help='Populated after execution with the resulting log entry.',
    )

    @api.constrains('recording_id', 'state')
    def _check_unique_active_job(self):
        """No two active (pending/running) jobs for the same recording"""
        for job in self:
            if job.state not in ('pending', 'running'):
                continue
            dup = self.search([
                ('id', '!=', job.id),
                ('recording_id', '=', job.recording_id.id),
                ('state', 'in', ('pending', 'running')),
            ], limit=1)
            if dup:
                raise UserError(_(
                    'Another active job already exists for this recording (job #%s).',
                    dup.id,
                ))

    @api.model
    def create_for_recordings(self, recordings, priority=10):
        """Create pending jobs for the given recordings (skip if already active)."""
        if not recordings:
            return self.browse()
        existing = self.search([
            ('recording_id', 'in', recordings.ids),
            ('state', 'in', ('pending', 'running')),
        ])
        already = set(existing.mapped('recording_id.id'))
        to_create = [
            {'recording_id': rec.id, 'priority': priority}
            for rec in recordings if rec.id not in already
        ]
        if to_create:
            return self.create(to_create)
        return self.browse()

    @api.model
    def claim_pending(self, limit=5):
        """Atomically claim up to ``limit`` pending jobs.

        Uses PostgreSQL's ``FOR UPDATE SKIP LOCKED`` so multiple workers
        (threads or cron jobs) can safely compete without double-processing.

        Caller must commit the claim before long-running work.
        """
        # Guard: require Postgres (always true for Odoo)
        self.env.cr.execute("""
            SELECT id FROM note_transcribe_job
            WHERE state = 'pending'
              AND scheduled_at <= (NOW() AT TIME ZONE 'UTC')
            ORDER BY priority DESC, scheduled_at ASC, id ASC
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        """, (limit,))
        ids = [r[0] for r in self.env.cr.fetchall()]
        if not ids:
            return self.browse()
        jobs = self.browse(ids)
        jobs.write({
            'state': 'running',
            'picked_at': fields.Datetime.now(),
            'worker_pid': os.getpid(),
        })
        return jobs

    def _mark_done(self, log=None):
        self.ensure_one()
        vals = {'state': 'done', 'ended_at': fields.Datetime.now()}
        if log:
            vals['log_id'] = log.id
        self.write(vals)

    def _mark_failed(self, error_message, log=None):
        self.ensure_one()
        vals = {
            'state': 'failed',
            'ended_at': fields.Datetime.now(),
            'error_message': (error_message or '')[:4000],
        }
        if log:
            vals['log_id'] = log.id
        self.write(vals)

    def action_cancel(self):
        """Cancel pending/running jobs (manual admin action)"""
        for job in self:
            if job.state not in ('pending', 'running'):
                raise UserError(_('Only pending or running jobs can be cancelled.'))
        self.write({
            'state': 'cancelled',
            'ended_at': fields.Datetime.now(),
        })
        return True

    def action_requeue(self):
        """Reset failed/cancelled job back to pending"""
        for job in self:
            if job.state not in ('failed', 'cancelled'):
                raise UserError(_('Only failed or cancelled jobs can be requeued.'))
        self.write({
            'state': 'pending',
            'picked_at': False,
            'started_at': False,
            'ended_at': False,
            'worker_pid': 0,
            'error_message': False,
            'scheduled_at': fields.Datetime.now(),
        })
        return True

    @api.model
    def _cron_reclaim_stale_jobs(self):
        """將 running 中的 stale jobs 重設為 pending

        Stale 判定：
        - picked_at 超過 15 分鐘 + worker_pid 已不存在 → stale
        - picked_at 超過 30 分鐘（無論 PID）→ stale
        """
        from datetime import timedelta
        now = fields.Datetime.now()
        pid_stale_cutoff = now - timedelta(minutes=15)
        abs_stale_cutoff = now - timedelta(minutes=30)

        abs_stale = self.search([
            ('state', '=', 'running'),
            ('picked_at', '<', abs_stale_cutoff),
        ])

        candidates = self.search([
            ('state', '=', 'running'),
            ('picked_at', '<', pid_stale_cutoff),
            ('worker_pid', '>', 0),
        ])
        from .note_recording import NoteRecording
        pid_dead = candidates.filtered(
            lambda j: not NoteRecording._is_pid_alive(j.worker_pid)
        )
        stale = abs_stale | pid_dead
        if stale:
            _logger.info('[queue] reclaiming %d stale running jobs', len(stale))
            stale.write({
                'state': 'pending',
                'picked_at': False,
                'worker_pid': 0,
                'error_message': _('Worker died or exceeded time limit — requeued.'),
                'scheduled_at': now,
            })

    @api.model
    def _cron_process_queue(self, limit=3):
        """定期 drain queue — 接手任何未被 thread 即時處理的 pending jobs"""
        jobs = self.claim_pending(limit=limit)
        if not jobs:
            return
        self.env.cr.commit()
        # 各 job 的 recording 重新走 action_transcribe，但避免重複建 job
        recordings = jobs.mapped('recording_id').filtered(lambda r: r.state != 'processing')
        if recordings:
            # action_transcribe 會再 create_for_recordings 但會被 unique constraint 擋掉
            # 這裡改為直接 spawn 專屬 thread 處理這些 jobs
            import threading
            thread = threading.Thread(
                target=self._drain_worker,
                args=(self.env.cr.dbname, self.env.uid, jobs.ids),
                daemon=True,
            )
            thread.start()

    @api.model
    def _drain_worker(self, db_name, uid, job_ids):
        """Thread worker: 處理已 claim 的 jobs"""
        import odoo
        registry = odoo.registry(db_name)
        with registry.cursor() as cr:
            env = api.Environment(cr, uid, {})
            jobs = env['note.transcribe.job'].browse(job_ids).exists()
            for job in jobs:
                if job.state != 'running':
                    continue
                rec = job.recording_id
                if not rec.exists():
                    job.write({
                        'state': 'failed',
                        'error_message': 'Recording deleted',
                        'ended_at': fields.Datetime.now(),
                    })
                    cr.commit()
                    continue
                # Mark recording as processing (if not already)
                if rec.state != 'processing':
                    rec.write({'state': 'processing', 'error_message': False})
                    cr.commit()
                # Run the existing per-recording flow
                try:
                    rec._run_single_transcription(cr, env, 1, 1)
                    # 根據 recording 的結果設 job 狀態
                    rec.invalidate_recordset(['state'])
                    if rec.state == 'done':
                        job._mark_done(rec.latest_log_id)
                    else:
                        job._mark_failed(
                            rec.error_message or 'Unknown error',
                            rec.latest_log_id,
                        )
                    cr.commit()
                except Exception as e:
                    cr.rollback()
                    env.invalidate_all()
                    _logger.exception('[queue] drain worker failed for job %s', job.id)
                    try:
                        job._mark_failed(str(e))
                        cr.commit()
                    except Exception:
                        cr.rollback()
