# -*- coding: utf-8 -*-
"""截圖結果取回：主機上打包成暫存檔再 SFTP 下載（不從 stdout 讀一整行 base64）。"""
import io
import tarfile
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged

from ..services import remote


@tagged('post_install', '-at_install')
class TestRemoteFetch(TransactionCase):

    def _tgz(self, files):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as tar:
            for name, data in files.items():
                info = tarfile.TarInfo('./' + name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    def test_fetch_uses_sftp_and_cleans_up(self):
        payload = self._tgz({'result.json': b'{}', 'b1/a.png': b'PNG'})
        conn = MagicMock()
        conn.get.side_effect = lambda remote_path, local: local.write(payload)
        cmds = []

        def fake_sudo(c, cmd, dont_raise=False):
            cmds.append(cmd)
            return MagicMock(stdout='PACKED\n' if 'tar -C' in cmd else '')

        @contextmanager
        def connect():
            yield conn

        server = MagicMock(get_connect=connect)
        with patch.object(remote, 'custom_sudo', fake_sudo):
            files = remote.fetch_dir(server, '/opt/knowledge/jobs/x/out')
        self.assertEqual(files, {'result.json': b'{}', 'b1/a.png': b'PNG'})
        self.assertTrue(conn.get.called, '用 SFTP 下載')
        self.assertFalse(any('base64' in c for c in cmds))
        self.assertTrue(any(c.startswith('rm -f /tmp/kb_get_') for c in cmds), '暫存檔要刪')

    def test_missing_dir_returns_empty(self):
        conn = MagicMock()

        @contextmanager
        def connect():
            yield conn

        with patch.object(remote, 'custom_sudo', lambda c, cmd, dont_raise=False: MagicMock(stdout='')):
            self.assertEqual(remote.fetch_dir(MagicMock(get_connect=connect), '/nope'), {})
        self.assertFalse(conn.get.called)
