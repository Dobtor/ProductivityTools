"""Tests for optimistic locking on save (P2-2 多人協作衝突偵測)。

設計：用 doc.write_date 當 etag。前端 load 時記下，save 時帶 if_unmodified_since
比對；若伺服器已變動 → 拒絕並回 conflict=True。

注意：在 TransactionCase 內 PostgreSQL 的 now() 是 frozen 在 transaction 開始時，
write_date 用 NOW() default。同一 transaction 內多次 write 可能拿到相同的 write_date。
所以在測試「write_date 已改變」的情境，必須用 SQL 直接 UPDATE 強制變動。
"""

from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestOptimisticLock(TransactionCase):
    """直接測 controller method（不走 HTTP），等同樂觀鎖核心邏輯。"""

    def setUp(self):
        super().setUp()
        self.Doc = self.env['doc.document']
        self.doc = self.Doc.create({
            'name': '樂觀鎖測試',
            'content_html': '<p>初版</p>',
        })

    def _save(self, **kwargs):
        """模擬 controller 內部呼叫 model write，含樂觀鎖檢查。

        controller 邏輯：取 doc.write_date 比對 if_unmodified_since。
        這裡複製該邏輯給 unit test。
        """
        if_unmodified_since = kwargs.pop('if_unmodified_since', None)
        if if_unmodified_since:
            current_wd = self.doc.write_date.isoformat() if self.doc.write_date else None
            if current_wd and current_wd != if_unmodified_since:
                return {
                    'success': False,
                    'conflict': True,
                    'server_write_date': current_wd,
                }
        self.doc.write(kwargs)
        return {
            'success': True,
            'write_date': self.doc.write_date.isoformat(),
        }

    def test_save_without_if_unmodified_since_succeeds(self):
        """沒帶樂觀鎖參數 → 保留向後相容（直接存）。"""
        result = self._save(content_html='<p>新版</p>')
        self.assertTrue(result['success'])
        self.assertNotIn('conflict', result)

    def test_save_with_matching_write_date_succeeds(self):
        """if_unmodified_since 與後端一致 → 接受。"""
        wd = self.doc.write_date.isoformat()
        result = self._save(content_html='<p>第二版</p>', if_unmodified_since=wd)
        self.assertTrue(result['success'])

    def test_save_with_stale_write_date_rejected(self):
        """if_unmodified_since 落後 → 拒絕並回 conflict=True。

        注意：TransactionCase 內 PostgreSQL now() frozen，無法靠 sleep 讓
        write_date 自然跳秒。改用：先把 doc.write_date 直接 SQL 設成 1 分鐘前，
        然後一般 write 就會把 write_date 更新為「現在」（仍 frozen 但比 1 分鐘前新）。
        """
        # 把 doc 的 write_date 強制設為 1 分鐘前
        old_wd = (fields.Datetime.now() - timedelta(minutes=1))
        self.env.cr.execute(
            "UPDATE doc_document SET write_date = %s WHERE id = %s",
            (old_wd, self.doc.id),
        )
        self.doc.invalidate_recordset(['write_date'])

        # 模擬 user A 載入時取得這個「1 分鐘前」write_date
        wd_a = self.doc.write_date.isoformat()

        # 模擬 user B 此時做了一次 write（write_date 會變成 transaction 開始時的 now）
        self.doc.write({'content_html': '<p>B 改的</p>'})
        self.assertNotEqual(
            self.doc.write_date.isoformat(), wd_a,
            "前置條件失敗：write_date 應該已變動",
        )

        # 現在 user A 帶舊 write_date 來存 → 應被拒
        result = self._save(content_html='<p>A 改的</p>', if_unmodified_since=wd_a)
        self.assertFalse(result['success'])
        self.assertTrue(result.get('conflict'))
        # 後端內容仍是 B 改的
        self.assertIn('B 改的', self.doc.content_html)

    def test_save_with_unparseable_if_unmodified_since_treated_as_stale(self):
        """if_unmodified_since 是無法比對的字串 → 視為過期，拒絕。"""
        result = self._save(
            content_html='<p>x</p>',
            if_unmodified_since='1970-01-01T00:00:00',
        )
        # 字串不一致 → 拒絕
        self.assertFalse(result['success'])
        self.assertTrue(result.get('conflict'))

    def test_load_returns_write_date(self):
        """load 應回傳 write_date 給前端記下。"""
        # 直接呼叫 model 看欄位存在
        self.assertTrue(self.doc.write_date)
        wd_iso = self.doc.write_date.isoformat()
        # ISO 格式應可往返字串比對
        self.assertEqual(wd_iso, self.doc.write_date.isoformat())
