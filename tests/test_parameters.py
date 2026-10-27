"""Credential views must reflect current config and stay private/read-only."""
import json
import uuid
import unittest
import test_manager as manager


class ParameterTests(unittest.TestCase):
    setUp = manager.ManagerTest.setUp
    script = manager.ManagerTest.script
    shell = manager.ManagerTest.shell
    configure = manager.ManagerTest.configure

    def snapshot(self):
        return {str(p): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
                for p in self.root.rglob('*') if p.is_file()}

    def test_current_config_parameters_are_read_only_and_exclude_private_data(self):
        cfg = self.configure('3')
        current = str(uuid.uuid4())
        cfg['inbounds'][0]['users'][0]['uuid'] = current
        tls = cfg['inbounds'][0]['tls']
        tls['server_name'] = 'current.example'
        tls['reality']['short_id'] = ['aabbccdd', '']
        tls['reality']['handshake'] = {'server': '::1', 'server_port': 8443}
        (self.config/'config.json').write_text(json.dumps(cfg))
        meta = json.loads((self.base/'state.json').read_text())
        meta.update(uuid='STALE_UUID', sni='stale.example', sid='STALE_SID', public_key='PUBLIC_ONLY')
        (self.base/'state.json').write_text(json.dumps(meta))
        before = self.snapshot()
        for language in ('zh_CN', 'en_US'):
            output = self.shell('LANGUAGE_CHOICE='+language+';node_parameters').stdout
            for value in (current, 'current.example', 'aabbccdd', '[::1]:8443', 'PUBLIC_ONLY', 'VPS', 'SSH', 'd → 2'):
                self.assertIn(value, output)
            for value in ('STALE_UUID', 'stale.example', 'STALE_SID', self.password, self.key.read_text()):
                self.assertNotIn(value, output)
            if self.private:
                self.assertNotIn(self.private, output)
            self.assertIn('KEEP PRIVATE' if language == 'en_US' else '保密提醒', output)
        self.assertEqual(before, self.snapshot())

    def test_hy2_only_does_not_present_stale_reality_credentials(self):
        self.configure('2')
        for language in ('zh_CN', 'en_US'):
            output = self.shell('LANGUAGE_CHOICE='+language+';node_parameters').stdout
            self.assertIn('Hysteria2', output)
            self.assertNotIn(self.uuid, output)
            self.assertNotIn(self.password, output)

    def test_argo_uses_its_own_uuid_without_reality_fields(self):
        self.configure('2')
        uid = str(uuid.uuid4())
        (self.base/'argo-server.json').write_text(json.dumps({'inbounds': [
            {'type': 'vless', 'listen': '127.0.0.1', 'listen_port': 8080,
             'users': [{'uuid': uid}], 'transport': {'type': 'ws', 'path': '/private'}}]}))
        (self.base/'argo-state.json').write_text(json.dumps({'domain': 'argo.example', 'node_name': 'Argo'}))
        before = self.snapshot()
        output = self.shell('node_parameters').stdout
        for value in (uid, 'argo.example', 'Not applicable', 'Port: 443'):
            self.assertIn(value, output)
        self.assertNotIn(self.uuid, output)
        self.assertEqual(before, self.snapshot())

    def test_missing_nodes_and_menu_dispatch(self):
        before = self.snapshot()
        self.assertIn('No nodes installed', self.shell('node_parameters').stdout)
        self.assertEqual(before, self.snapshot())
        result = self.shell('sub_menu 2;echo "ACTION=$MAIN_ACTION"', input='7\n')
        self.assertIn('ACTION=node_parameters', result.stdout)
        self.assertIn('UUID / public key / Short ID / SNI', result.stdout)

    def test_symlinked_argo_and_malformed_json_do_not_disclose_contents(self):
        self.configure('1')
        outside = self.root/'outside.json'
        outside.write_text('PRIVATE_DATA_DO_NOT_PRINT')
        link = self.base/'argo-server.json'
        link.symlink_to(outside)
        result = self.shell('node_parameters', ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(outside.read_text(), result.stdout+result.stderr)
        link.unlink()
        (self.config/'config.json').write_text('PRIVATE_DATA_DO_NOT_PRINT')
        result = self.shell('node_parameters', ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('PRIVATE_DATA_DO_NOT_PRINT', result.stdout+result.stderr)
