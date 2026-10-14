import contextlib
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

import yaml

import inspect_configs
import main
from util import aes_help as aes, http_util as http, push_util as push, zepp_helper as zepp
from util.token_cache import cache_lock, TokenCacheBusy

ROOT = Path(__file__).resolve().parents[1]
KEY = b'0123456789abcdef'


def response(payload=None, status=200, headers=None):
    result = Mock(status_code=status, headers=headers or {})
    result.json.return_value = payload
    return result


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        self.stack.enter_context(patch('requests.sessions.Session.request', side_effect=AssertionError('real network prohibited')))
        self.addCleanup(self.stack.close)

    def test_refreshed_and_partial_login_tokens_are_not_logged(self):
        secret = 'SYNTHETIC_SECRET'
        with patch.object(http.requests, 'request', return_value=response({'result': 'ok', 'token_info': {'app_token': secret}})):
            self.assertEqual(zepp.grant_app_token(secret), (secret, None))
        with patch.object(http.requests, 'request', return_value=response({'result': 'ok', 'token_info': {'login_token': secret}})):
            with self.assertRaises(http.RequestFailure):
                zepp.grant_login_tokens(secret, 'device')
        self.assertNotIn(secret, self.output.getvalue())

    def test_telegram_token_payload_and_exception_url_are_not_logged(self):
        secret = 'SYNTHETIC_SECRET'
        with patch.object(http.requests, 'request', return_value=response({'ok': True, 'result': {'message_id': 1}})):
            self.assertTrue(push.push_telegram_bot(secret, '123', secret))
        with patch.object(http.requests, 'request', side_effect=http.requests.Timeout(f'https://example.test/{secret}')):
            self.assertFalse(push.push_telegram_bot(secret, '123', secret))
            self.assertFalse(push.push_wechat_webhook(secret, 'title', secret))
        self.assertNotIn(secret, self.output.getvalue())

    def test_pushplus_https(self):
        with patch.object(http.requests, 'request', return_value=response({'code': 200})) as send:
            self.assertTrue(push.push_plus('synthetic', 'title', 'message'))
        self.assertEqual(send.call_args.args[:2], ('POST', 'https://www.pushplus.plus/send'))

    def test_all_business_requests_have_bounded_timeout_and_no_redirect(self):
        cases = [
            (lambda: zepp.login_access_token('review@example.test', 'synthetic'), response(status=303, headers={'Location': 'https://example.test/?access=a'})),
            (lambda: zepp.grant_login_tokens('a', 'd'), response({'result': 'ok', 'token_info': {'login_token': 'l', 'app_token': 'a', 'user_id': '99'}})),
            (lambda: zepp.grant_app_token('l'), response({'result': 'ok', 'token_info': {'app_token': 'a'}})),
            (lambda: zepp.check_app_token('a', '99'), response({'message': 'success'})),
            (lambda: zepp.renew_login_token('l'), response({'result': 'ok', 'token_info': {'login_token': 'l'}})),
            (lambda: zepp.get_user_device_id('a', '99'), response({'message': 'success', 'data': []})),
            (lambda: zepp.get_daily_steps('a', '99', '2026-10-14'), response({'message': 'success', 'data': []})),
            (lambda: zepp.post_fake_brand_data('23456', 'a', '99'), response({'message': 'success'})),
            (lambda: push.push_plus('t', 'title', 'content'), response({'code': 200})),
            (lambda: push.push_wechat_webhook('k', 'title', 'content'), response({'errcode': 0})),
            (lambda: push.push_telegram_bot('t', '1', 'content'), response({'ok': True})),
        ]
        for call, reply in cases:
            with self.subTest(call=call), patch.object(http.requests, 'request', return_value=reply) as send:
                call()
                self.assertEqual(send.call_args.kwargs['timeout'], (5, 20))
                self.assertFalse(send.call_args.kwargs['allow_redirects'])

    def test_current_user_is_checked(self):
        with patch.object(http.requests, 'request', return_value=response({'message': 'success'})) as send:
            self.assertTrue(zepp.check_app_token('app', 'CURRENT_USER')[0])
        self.assertEqual(send.call_args.kwargs['params']['userid'], 'CURRENT_USER')

    def test_transient_token_check_error_does_not_relogin(self):
        with patch.object(main, 'user_tokens', {'review@example.test': {'app_token': 'a', 'user_id': '99'}}, create=True):
            runner = main.MiMotionRunner('review@example.test', 'synthetic')
            with patch.object(http.requests, 'request', return_value=response(status=503)), patch.object(zepp, 'login_access_token') as login:
                with self.assertRaises(http.RequestFailure):
                    runner.login()
                login.assert_not_called()

    def test_invalid_app_token_refreshes_without_password_login(self):
        cache = {'review@example.test': {'app_token': 'old', 'login_token': 'l', 'user_id': '99'}}
        with patch.object(main, 'user_tokens', cache, create=True), patch.object(zepp, 'check_app_token', return_value=(False, 'expired')), patch.object(zepp, 'grant_app_token', return_value=('new', None)), patch.object(zepp, 'login_access_token') as login:
            runner = main.MiMotionRunner('review@example.test', 'synthetic')
            self.assertEqual(runner.login(), 'new')
            self.assertEqual(cache[runner.user]['app_token'], 'new')
            login.assert_not_called()

    def test_missing_cached_userid_is_recovered(self):
        cache = {'review@example.test': {'app_token': 'old', 'access_token': 'a', 'login_token': 'l'}}
        with patch.object(main, 'user_tokens', cache, create=True), patch.object(zepp, 'check_app_token', return_value=(False, None)), patch.object(zepp, 'grant_login_tokens', return_value=('l', 'a', '99', None)), patch.object(zepp, 'grant_app_token') as grant:
            runner = main.MiMotionRunner('review@example.test', 'synthetic')
            self.assertEqual(runner.login(), 'a')
            self.assertEqual(runner.user_id, '99')
            grant.assert_not_called()

    def test_device_rebinding_and_unbinding_refresh_cache(self):
        for device in ('NEW_DEVICE', None):
            with self.subTest(device=device):
                cache = {'review@example.test': {'app_token': 'a', 'user_id': '99', 'bound_device_id': 'OLD_DEVICE'}}
                with patch.object(main, 'user_tokens', cache, create=True), patch.object(zepp, 'check_app_token', return_value=(True, None)), patch.object(zepp, 'get_user_device_id', return_value=device) as query, patch.object(zepp, 'get_daily_steps', return_value=0), patch.object(zepp, 'post_fake_brand_data', return_value=(True, 'success')) as upload:
                    runner = main.MiMotionRunner('review@example.test', 'synthetic')
                    self.assertTrue(runner.login_and_post_step(100, 100)[1])
                    query.assert_called_once_with('a', '99', strict=True)
                    self.assertEqual(upload.call_args.kwargs['device_id'], device)
                    self.assertEqual(cache[runner.user].get('bound_device_id'), device)

    def test_daily_steps_reads_json_base64_and_multiple_devices(self):
        day = '2026-10-14'
        summary = {'stp': {'ttl': 2013}}
        for encoded in (summary, json.dumps(summary), base64.b64encode(json.dumps(summary).encode()).decode()):
            payload = {'message': 'success', 'data': [
                {'date_time': '2026-10-13', 'summary': 'unused'},
                {'date_time': day, 'summary': encoded},
                {'date': day, 'summary': {'stp': {'ttl': '1501'}}},
            ]}
            with self.subTest(encoded=encoded), patch.object(http.requests, 'request', return_value=response(payload)) as send:
                self.assertEqual(zepp.get_daily_steps('a', '99', day), 2013)
                self.assertEqual(send.call_args.kwargs['params']['from_date'], day)
                self.assertEqual(send.call_args.kwargs['params']['to_date'], day)
                self.assertEqual(send.call_args.kwargs['params']['userid'], '99')
        with patch.object(http.requests, 'request', return_value=response({'message': 'success', 'data': []})):
            self.assertEqual(zepp.get_daily_steps('a', '99', day), 0)

    def test_daily_steps_errors_do_not_become_zero(self):
        day = '2026-10-14'
        payloads = [
            {'message': 'failure', 'data': []}, {'message': 'success'},
            {'message': 'success', 'data': {}},
            {'message': 'success', 'data': [{'summary': {}}]},
        ]
        for summary in ('SYNTHETIC_SECRET', '{}', [], None, {'stp': {'ttl': -1}},
                        {'stp': {'ttl': True}}, {'stp': {'ttl': 2.5}}):
            payloads.append({'message': 'success', 'data': [{'date': day, 'summary': summary}]})
        for payload in payloads:
            with self.subTest(payload=payload), patch.object(http.requests, 'request', return_value=response(payload)):
                with self.assertRaises(http.RequestFailure):
                    zepp.get_daily_steps('a', '99', day)
        self.assertNotIn('SYNTHETIC_SECRET', self.output.getvalue())

    def test_lower_or_equal_target_does_not_overwrite_cloud_steps(self):
        cache = {'review@example.test': {'app_token': 'a', 'user_id': '99'}}
        for step in (892, 1501, 2013):
            with self.subTest(step=step), patch.object(main, 'user_tokens', cache, create=True), patch.object(zepp, 'check_app_token', return_value=(True, None)), patch.object(zepp, 'get_user_device_id', return_value='AABB'), patch.object(zepp, 'get_daily_steps', return_value=2013), patch.object(zepp, 'post_fake_brand_data') as upload:
                runner = main.MiMotionRunner('review@example.test', 'synthetic')
                message, ok = runner.login_and_post_step(step, step)
                self.assertTrue(ok)
                self.assertIn('已跳过上传', message)
                upload.assert_not_called()

    def test_cloud_read_failure_stops_upload(self):
        cache = {'review@example.test': {'app_token': 'a', 'user_id': '99'}}
        with patch.object(main, 'user_tokens', cache, create=True), patch.object(zepp, 'check_app_token', return_value=(True, None)), patch.object(zepp, 'get_user_device_id', return_value='AABB'), patch.object(zepp, 'get_daily_steps', side_effect=http.RequestFailure('查询失败')), patch.object(zepp, 'post_fake_brand_data') as upload:
            runner = main.MiMotionRunner('review@example.test', 'synthetic')
            with self.assertRaises(http.RequestFailure):
                runner.login_and_post_step(2500, 2500)
            upload.assert_not_called()

    def test_successful_upload_cache_guards_against_stale_cloud_read(self):
        day = main.get_beijing_time().strftime('%F')
        cache = {'review@example.test': {'app_token': 'a', 'user_id': '99'}}
        with patch.object(main, 'user_tokens', cache, create=True), patch.object(zepp, 'check_app_token', return_value=(True, None)), patch.object(zepp, 'get_user_device_id', return_value='AABB'), patch.object(zepp, 'get_daily_steps', return_value=2013), patch.object(zepp, 'post_fake_brand_data', return_value=(True, 'success')) as upload:
            runner = main.MiMotionRunner('review@example.test', 'synthetic')
            message, ok = runner.login_and_post_step(2500, 2500)
            self.assertTrue(ok)
            self.assertIn('微信更新未验证', message)
            upload.assert_called_once_with('2500', 'a', '99', device_id='AABB', date=day)
            self.assertEqual(cache[runner.user]['last_step_upload'], {'date': day, 'steps': 2500})
            self.assertTrue(runner.login_and_post_step(2200, 2200)[1])
            upload.assert_called_once()

    def test_yesterdays_upload_does_not_block_today_and_failed_upload_is_not_saved(self):
        cache = {'review@example.test': {'app_token': 'a', 'user_id': '99', 'last_step_upload': {'date': '2000-01-01', 'steps': 9000}}}
        with patch.object(main, 'user_tokens', cache, create=True), patch.object(zepp, 'check_app_token', return_value=(True, None)), patch.object(zepp, 'get_user_device_id', return_value='AABB'), patch.object(zepp, 'get_daily_steps', return_value=0), patch.object(zepp, 'post_fake_brand_data', return_value=(False, 'failure')) as upload:
            runner = main.MiMotionRunner('review@example.test', 'synthetic')
            self.assertFalse(runner.login_and_post_step(100, 100)[1])
            upload.assert_called_once()
            self.assertEqual(cache[runner.user]['last_step_upload']['date'], '2000-01-01')

    def test_password_relogin_preserves_same_users_step_guard(self):
        previous = {'date': main.get_beijing_time().strftime('%F'), 'steps': 2013}
        cache = {'review@example.test': {'app_token': 'expired', 'user_id': '99', 'last_step_upload': previous}}
        with patch.object(main, 'user_tokens', cache, create=True), patch.object(zepp, 'check_app_token', return_value=(False, None)), patch.object(zepp, 'grant_login_tokens', side_effect=[(None, None, None, 'expired'), ('l', 'a', '99', None)]), patch.object(zepp, 'login_access_token', return_value=('access', None)):
            runner = main.MiMotionRunner('review@example.test', 'synthetic')
            self.assertEqual(runner.login(), 'a')
            self.assertEqual(cache[runner.user]['last_step_upload'], previous)

    def test_device_query_failure_stops_upload_and_retains_cache(self):
        cache = {'review@example.test': {'app_token': 'a', 'user_id': '99', 'bound_device_id': 'OLD_DEVICE'}}
        with patch.object(main, 'user_tokens', cache, create=True), patch.object(zepp, 'check_app_token', return_value=(True, None)), patch.object(http.requests, 'request', return_value=response(status=503)), patch.object(zepp, 'post_fake_brand_data') as upload:
            runner = main.MiMotionRunner('review@example.test', 'synthetic')
            with self.assertRaises(http.RequestFailure):
                runner.login_and_post_step(100, 100)
            upload.assert_not_called()
            self.assertEqual(cache[runner.user]['bound_device_id'], 'OLD_DEVICE')

    def test_device_aliases_and_mac_normalization(self):
        for type_name, id_name in (('type', 'deviceId'), ('deviceType', 'macAddress'), ('device_type', 'deviceid')):
            reply = response({'message': 'success', 'data': [{type_name: '0', id_name: 'aa:bb:cc:dd:ee:ff'}]})
            with self.subTest(type_name=type_name), patch.object(http.requests, 'request', return_value=reply):
                self.assertEqual(zepp.get_user_device_id('a', '99', strict=True), 'AABBCCDDEEFF')

    def test_upload_fields_and_beijing_date(self):
        with patch.object(http.requests, 'request', return_value=response({'message': 'success'})) as send:
            self.assertTrue(zepp.post_fake_brand_data('23456', 'a', '99', 'AABBCCDDEEFF')[0])
        body = parse_qs(send.call_args.kwargs['data'])
        self.assertEqual(body['userid'], ['99'])
        self.assertEqual(body['last_deviceid'], ['AABBCCDDEEFF'])
        record = json.loads(body['data_json'][0])[0]
        self.assertEqual(record['date'], zepp.get_beijing_time().strftime('%F'))
        self.assertEqual(json.loads(record['summary'])['stp']['ttl'], 23456)

    def test_malformed_json_is_safe_and_does_not_emit_body(self):
        reply = response()
        reply.json.side_effect = ValueError('SYNTHETIC_SECRET_BODY')
        with patch.object(http.requests, 'request', return_value=reply):
            with self.assertRaisesRegex(http.RequestFailure, 'JSON'):
                zepp.check_app_token('a', '99')
            self.assertFalse(push.push_plus('t', 'title', 'content'))
        self.assertNotIn('SYNTHETIC_SECRET_BODY', self.output.getvalue())

    def test_redirect_parameters_last_encoded_fragment_or_missing(self):
        for location, token in (
            ('https://example.test/?access=token', 'token'),
            ('https://example.test/?state=ok&access=token', 'token'),
            ('https://example.test/?access=a%2Bb%26c', 'a+b&c'),
            ('https://example.test/#access=token', 'token'),
            ('https://example.test/?access=', None),
            ('https://example.test/?state=ok', None),
        ):
            with self.subTest(location=location):
                self.assertEqual(zepp.get_access_token(location), token)
        self.assertEqual(zepp.get_error_code('https://example.test/?error=invalid'), 'invalid')

    def test_invalid_push_hour_does_not_suppress_any_channel(self):
        for hour in (None, '', 'invalid', '25', -1):
            with self.subTest(hour=hour), patch.object(push, 'push_to_push_plus') as pp, patch.object(push, 'push_to_wechat_webhook') as wx, patch.object(push, 'push_to_telegram_bot') as tg:
                push.push_results([], 'summary', push.PushConfig(push_plus_hour=hour))
                pp.assert_called_once(); wx.assert_called_once(); tg.assert_called_once()

    def test_valid_hour_only_gates_pushplus_and_accepts_numeric_json(self):
        with patch.object(push, 'get_beijing_time', return_value=Mock(hour=20)), patch('builtins.open', side_effect=FileNotFoundError), patch.object(push, 'push_to_push_plus') as pp, patch.object(push, 'push_to_wechat_webhook') as wx, patch.object(push, 'push_to_telegram_bot') as tg:
            push.push_results([], 'summary', push.PushConfig(push_plus_hour=21))
            pp.assert_not_called(); wx.assert_called_once(); tg.assert_called_once()
        with patch.object(push, 'get_beijing_time', return_value=Mock(hour=21)):
            self.assertFalse(push.not_in_push_time_range(push.PushConfig(push_plus_hour=21)))

    def test_delayed_pushplus_uses_schedule_record(self):
        with tempfile.TemporaryDirectory() as folder:
            record = Path(folder, 'record')
            record.write_text('next exec time: UTC(13:35) 北京时间(21:35)\n')
            real_open = open
            with patch.object(push, 'get_beijing_time', return_value=Mock(hour=22)), patch('builtins.open', side_effect=lambda *a, **kw: real_open(record, **kw)):
                self.assertFalse(push.not_in_push_time_range(push.PushConfig(push_plus_hour='21')))

    def test_notification_html_is_escaped_and_accounts_masked(self):
        result = {'user': 'review@example.test', 'success': False, 'msg': '<bad>&error'}
        config = push.PushConfig(push_plus_token='t', telegram_bot_token='t', telegram_chat_id='1')
        for builder, sender in ((push.push_to_push_plus, 'push_plus'), (push.push_to_telegram_bot, 'push_telegram_bot')):
            with self.subTest(sender=sender), patch.object(push, sender) as send:
                builder([result], '<summary>', config)
                content = send.call_args.args[-1]
                self.assertNotIn(result['user'], content)
                self.assertNotIn('<bad>', content)
                self.assertIn('&lt;bad&gt;&amp;error', content)
                self.assertNotIn('<pre><blockquote>', content)
        content = inspect_configs.build_inspect_configs_content_for_telegram('<config>&', '<key>', '<pat>')
        self.assertIn('&lt;config&gt;&amp;', content)
        self.assertNotIn('<key>', content)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.output = io.StringIO()
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        self.stack.enter_context(patch('requests.sessions.Session.request', side_effect=AssertionError('real network prohibited')))
        folder = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.data_path = Path(folder, 'encrypted_tokens.data')
        self.stack.enter_context(patch.object(main, 'TOKEN_DATA_PATH', self.data_path))
        self.addCleanup(self.stack.close)

    def run_accounts(self, outcomes, concurrent=False, encrypted=False):
        count = len(outcomes)
        config = {'USER': '#'.join(f'review{i}@example.test' for i in range(count)), 'PWD': '#'.join(['synthetic'] * count), 'SLEEP_GAP': 0, 'USE_CONCURRENT': concurrent}
        env = {'CONFIG': json.dumps(config)}
        if encrypted:
            env['AES_KEY'] = KEY.decode()
        with patch.dict(os.environ, env, clear=True), patch.object(main.MiMotionRunner, 'login_and_post_step', side_effect=outcomes), patch.object(push, 'push_results') as notify:
            status = main.main()
            notify.assert_called_once()
        return status

    def test_all_failed_and_partial_failed_exit_nonzero(self):
        self.assertEqual(self.run_accounts([('failed', False)]), 1)
        self.assertEqual(self.run_accounts([('success', True), ('failed', False)]), 1)

    def test_cli_reports_failure_with_nonzero_process_status(self):
        code = """import runpy
from unittest.mock import patch
from util import zepp_helper
with patch('dotenv.load_dotenv'), patch.object(zepp_helper, 'login_access_token', return_value=(None, 'login rejected')):
    runpy.run_path('main.py', run_name='__main__')
"""
        env = dict(os.environ, CONFIG=json.dumps({'USER': 'review@example.test', 'PWD': 'synthetic'}), AES_KEY='')
        child = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(child.returncode, 1, child.stderr)
        self.assertIn('成功：0，失败：1', child.stdout)

    def test_serial_and_concurrent_success_exit_zero(self):
        for concurrent in (False, True):
            with self.subTest(concurrent=concurrent):
                self.assertEqual(self.run_accounts([('success', True), ('success', True)], concurrent), 0)

    def test_credentials_are_saved_even_if_all_accounts_fail(self):
        self.assertEqual(self.run_accounts([('failed', False)], encrypted=True), 1)
        self.assertTrue(self.data_path.exists())
        self.assertEqual(json.loads(aes.decrypt_token_data(self.data_path.read_bytes(), KEY)), {})

    def test_account_exception_does_not_log_sensitive_error_text(self):
        self.assertEqual(self.run_accounts([ValueError('SYNTHETIC_PASSWORD')]), 1)
        self.assertNotIn('SYNTHETIC_PASSWORD', self.output.getvalue())

    def test_invalid_configuration_fails_before_network(self):
        base = {'USER': 'review@example.test', 'PWD': 'synthetic'}
        invalid = [None, [], dict(base, USER=123), dict(base, USER=''), dict(base, PWD='x#y'),
                   dict(base, MIN_STEP=''), dict(base, MIN_STEP=200, MAX_STEP=100),
                   dict(base, MIN_STEP=-1), dict(base, SLEEP_GAP=-1), dict(base, SLEEP_GAP='nan'),
                   dict(base, PUSH_PLUS_MAX=0), dict(base, USE_CONCURRENT='maybe')]
        for config in invalid:
            with self.subTest(config=config), patch.dict(os.environ, {'CONFIG': json.dumps(config)}, clear=True):
                self.assertEqual(main.main(), 1)
        with patch.dict(os.environ, {'CONFIG': '{SYNTHETIC_PASSWORD'}, clear=True):
            self.assertEqual(main.main(), 1)
        output = self.output.getvalue()
        self.assertNotIn('SYNTHETIC_PASSWORD', output)
        self.assertIn('第 1 行 第 2 列', output)

    def test_fullwidth_punctuation_is_retried_as_halfwidth(self):
        broken = '{\n  "USER": "review@example.test",\n  "PWD": "synthetic",\n  \u201cMIN_STEP\u201d: \u201c21000\u201d\n}'
        config, corrected = main.parse_config(broken)
        self.assertTrue(corrected)
        self.assertEqual(config['MIN_STEP'], '21000')

    def test_main_accepts_fullwidth_config_without_leaking_content(self):
        config = {'USER': 'review@example.test', 'PWD': 'synthetic', 'MIN_STEP': 1000, 'MAX_STEP': 2000}
        raw = json.dumps(config).replace('"MIN_STEP"', '\u201cMIN_STEP\u201d').replace(': 1000', ': \u201c1000\u201d')
        with patch.dict(os.environ, {'CONFIG': raw}, clear=True), patch.object(main, 'get_min_max_by_time', return_value=(500, 1000)), patch.object(main.MiMotionRunner, 'login_and_post_step', return_value=('success', True)), patch.object(push, 'push_results'):
            self.assertEqual(main.main(), 0)
        output = self.output.getvalue()
        self.assertIn('全角标点', output)
        self.assertNotIn('synthetic', output)

    def test_valid_config_with_fullwidth_password_is_not_rewritten(self):
        raw = json.dumps({'USER': 'review@example.test', 'PWD': 'pass\u201cword'})
        config, corrected = main.parse_config(raw)
        self.assertFalse(corrected)
        self.assertEqual(config['PWD'], 'pass\u201cword')

    def test_fullwidth_retry_still_reports_syntax_error(self):
        with self.assertRaises(json.JSONDecodeError):
            main.parse_config('{\n  "USER"\uff1a "review@example.test"\n  "PWD": "synthetic"\n}')

    def test_json_boolean_and_zero_interval_are_preserved(self):
        config = main.validate_config({'USER': 'review@example.test', 'PWD': 'synthetic', 'SLEEP_GAP': 0, 'USE_CONCURRENT': True})
        self.assertIs(config['USE_CONCURRENT'], True)
        self.assertEqual(config['SLEEP_GAP'], 0)

    def test_one_off_target_is_exact_and_empty_target_uses_time_range(self):
        config = {'USER': 'review@example.test', 'PWD': 'synthetic', 'MIN_STEP': 1000, 'MAX_STEP': 2000}
        for target, expected in (('3000', (3000, 3000)), ('0', (0, 0)), ('', (500, 1000))):
            with self.subTest(target=target), patch.dict(os.environ, {'CONFIG': json.dumps(config), 'TARGET_STEP': target}, clear=True), patch.object(main, 'get_min_max_by_time', return_value=(500, 1000)), patch.object(main.MiMotionRunner, 'login_and_post_step', return_value=('success', True)) as run, patch.object(push, 'push_results'):
                self.assertEqual(main.main(), 0)
                run.assert_called_once_with(*expected)

    def test_invalid_one_off_target_stops_before_login(self):
        config = {'USER': 'review@example.test', 'PWD': 'synthetic'}
        for target in ('-1', '1.5', 'nan', '3e3', '$(touch marker)'):
            with self.subTest(target=target), patch.dict(os.environ, {'CONFIG': json.dumps(config), 'TARGET_STEP': target}, clear=True), patch.object(main.MiMotionRunner, 'login_and_post_step') as run:
                self.assertEqual(main.main(), 1)
                run.assert_not_called()

    def test_legacy_cache_migrates_without_losing_fields(self):
        data = {'review@example.test': {'app_token': 'synthetic', 'user_id': '99', 'bound_device_id': 'AABB'}}
        self.data_path.write_bytes(aes.encrypt_data(json.dumps(data).encode(), KEY))
        with patch.object(main, 'aes_key', KEY, create=True):
            restored = main.prepare_user_tokens()
            self.assertEqual(restored, data)
            with patch.object(main, 'user_tokens', restored, create=True):
                main.persist_user_tokens()
            self.assertTrue(self.data_path.read_bytes().startswith(aes.TOKEN_MAGIC))
            self.assertEqual(main.prepare_user_tokens(), data)

    def test_invalid_cache_shape_is_ignored(self):
        for data in ([], {'user': 'not a token object'}):
            self.data_path.write_bytes(aes.encrypt_token_data(json.dumps(data).encode(), KEY))
            with patch.object(main, 'aes_key', KEY, create=True):
                self.assertEqual(main.prepare_user_tokens(), {})

    def test_failed_atomic_replace_preserves_previous_cache(self):
        self.data_path.write_bytes(b'previous ciphertext')
        with patch.object(main, 'aes_key', KEY, create=True), patch.object(main, 'user_tokens', {}, create=True), patch.object(main.os, 'replace', side_effect=OSError('synthetic')):
            with self.assertRaises(OSError):
                main.persist_user_tokens()
        self.assertEqual(self.data_path.read_bytes(), b'previous ciphertext')
        self.assertEqual(list(self.data_path.parent.glob('.tokens-*')), [])

    def test_cache_lock_is_released_and_rejects_other_process(self):
        code = 'from pathlib import Path; from util.token_cache import cache_lock; import sys\nwith cache_lock(Path(sys.argv[1])): pass'
        with cache_lock(self.data_path):
            child = subprocess.run([sys.executable, '-c', code, str(self.data_path)], cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(child.returncode, 0)
            self.assertIn('TokenCacheBusy', child.stderr)
        child = subprocess.run([sys.executable, '-c', code, str(self.data_path)], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(child.returncode, 0, child.stderr)


class CryptoTests(unittest.TestCase):
    def test_gcm_rejects_tampering_in_nonce_tag_and_ciphertext(self):
        encrypted = aes.encrypt_token_data(b'{"token":"synthetic"}', KEY)
        self.assertEqual(aes.decrypt_token_data(encrypted, KEY), b'{"token":"synthetic"}')
        for position in (len(aes.TOKEN_MAGIC), len(aes.TOKEN_MAGIC) + 12, len(encrypted) - 1):
            changed = bytearray(encrypted)
            changed[position] ^= 1
            with self.subTest(position=position), self.assertRaises(ValueError):
                aes.decrypt_token_data(bytes(changed), KEY)
        with self.assertRaises(ValueError):
            aes.decrypt_token_data(encrypted, b'fedcba9876543210')

    def test_external_cbc_protocol_and_legacy_cache_remain_readable(self):
        for plain in (b'', b'abc', b'a' * 16, b'a' * 33):
            self.assertEqual(aes.decrypt_data(aes.encrypt_data(plain, KEY, KEY), KEY, KEY), plain)
            self.assertEqual(aes.decrypt_token_data(aes.encrypt_data(plain, KEY), KEY), plain)

    def test_decrypt_cli_runs_directly_and_as_module(self):
        ciphertext = aes.bytes_to_base64(aes.encrypt_data(b'{"value":"synthetic"}', KEY, KEY))
        for command in ([sys.executable, 'local/decrypt_data.py', ciphertext], [sys.executable, '-m', 'local.decrypt_data', ciphertext]):
            child = subprocess.run(command, cwd=ROOT, env=dict(os.environ, INSPECT_AES_KEY=KEY.decode()), capture_output=True, text=True)
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertEqual(json.loads(child.stdout), {'value': 'synthetic'})

    def test_token_decrypt_cli_and_invalid_key(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder, 'cache')
            cache.write_bytes(aes.encrypt_token_data(b'{"value":"synthetic"}', KEY))
            command = [sys.executable, 'local/decrypt_data.py', '--mode', 'token', '--file', str(cache)]
            child = subprocess.run(command, cwd=ROOT, env=dict(os.environ, AES_KEY=KEY.decode()), capture_output=True, text=True)
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertEqual(json.loads(child.stdout), {'value': 'synthetic'})
            child = subprocess.run(command, cwd=ROOT, env=dict(os.environ, AES_KEY='invalid'), capture_output=True, text=True)
            self.assertEqual(child.returncode, 1)


class WorkflowTests(unittest.TestCase):
    def test_writers_share_queue_and_checkout_latest_branch(self):
        workflows = [yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader) for name in ('run.yml', 'cron.yml')]
        self.assertEqual(workflows[0]['concurrency'], workflows[1]['concurrency'])
        for workflow in workflows:
            self.assertEqual(workflow['concurrency']['cancel-in-progress'], 'false')
            self.assertEqual(workflow['concurrency']['queue'], 'max')
            steps = next(iter(workflow['jobs'].values()))['steps']
            self.assertIn('ref', steps[0]['with'])
            for step in steps:
                self.assertNotIn('${{ vars.CRON_HOURS }}', step.get('run', ''))
        save = workflows[0]['jobs']['build']['steps'][-1]
        self.assertIn("steps.run.outcome == 'failure'", save['if'])

    def test_cron_hours_validation_normalizes_and_rejects_injection(self):
        command = 'source cron_convert.sh; normalize_cron_hours "$CRON_HOURS"'
        for value, expected in (('15,12,12,03', '3,12,15'), ('0,23', '0,23')):
            child = subprocess.run(['bash', '-c', command], cwd=ROOT, env=dict(os.environ, CRON_HOURS=value), capture_output=True, text=True)
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertEqual(child.stdout.strip(), expected)
        for value in ('24', '-1', '1,,2', '1,2;', '$(touch marker)', '1 2'):
            child = subprocess.run(['bash', '-c', command], cwd=ROOT, env=dict(os.environ, CRON_HOURS=value), capture_output=True, text=True)
            self.assertNotEqual(child.returncode, 0)

    def test_invalid_cron_does_not_modify_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workflows = root / '.github/workflows'
            workflows.mkdir(parents=True)
            (workflows / 'run.yml').write_text('original')
            (root / 'cron_change_time').write_text('original log')
            command = f'source "{ROOT / "cron_convert.sh"}"; persist_execute_log test "$CRON_HOURS"'
            child = subprocess.run(['bash', '-c', command], cwd=root, env=dict(os.environ, CRON_HOURS='24'), capture_output=True, text=True)
            self.assertNotEqual(child.returncode, 0)
            self.assertEqual((workflows / 'run.yml').read_text(), 'original')
            self.assertEqual((root / 'cron_change_time').read_text(), 'original log')

    def test_random_cron_updates_valid_schedule(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.github/workflows').mkdir(parents=True)
            target = root / '.github/workflows/run.yml'
            target.write_text((ROOT / '.github/workflows/run.yml').read_text())
            command = f'source "{ROOT / "cron_convert.sh"}"; persist_execute_log test "$CRON_HOURS"'
            child = subprocess.run(['bash', '-c', command], cwd=root, env=dict(os.environ, CRON_HOURS='15,12,13,14'), capture_output=True, text=True)
            self.assertEqual(child.returncode, 0, child.stderr)
            cron = yaml.load(target.read_text(), Loader=yaml.BaseLoader)['on']['schedule'][0]['cron']
            minute, hours, *rest = cron.split()
            self.assertTrue(0 <= int(minute) < 60)
            self.assertTrue(set(hours.split(',')) <= {'12', '13', '14', '15'})
            self.assertEqual(rest, ['*', '*', '*'])
            self.assertIn('next exec time:', (root / 'cron_change_time').read_text())


class PersistWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.origin = self.root / 'origin'
        self.git(self.root, 'init', '--bare', '-q', '-b', 'master', str(self.origin))
        self.a = self.root / 'a'
        self.b = self.root / 'b'
        self.git(self.root, 'clone', '-q', str(self.origin), str(self.a))
        (self.a / 'tokens').write_text('initial tokens')
        (self.a / 'schedule').write_text('initial schedule')
        self.git(self.a, 'add', '.')
        self.git(self.a, '-c', 'user.name=review', '-c', 'user.email=review@example.test', 'commit', '-qm', 'initial')
        self.git(self.a, 'push', '-q', 'origin', 'master')
        self.git(self.root, 'clone', '-q', str(self.origin), str(self.b))

    def git(self, cwd, *args):
        child = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)
        self.assertEqual(child.returncode, 0, child.stderr)
        return child.stdout.strip()

    def save(self, cwd, file):
        return subprocess.run(['bash', str(ROOT / '.github/scripts/persist_changes.sh'), 'review save', file], cwd=cwd, env=dict(os.environ, TARGET_BRANCH='master'), capture_output=True, text=True)

    def test_no_change_is_success_and_unrelated_files_are_not_committed(self):
        before = self.git(self.a, 'rev-parse', 'HEAD')
        (self.a / 'unrelated').write_text('must not be committed')
        child = self.save(self.a, 'tokens')
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(self.git(self.a, 'rev-parse', 'HEAD'), before)
        (self.a / 'tokens').write_text('new tokens')
        child = self.save(self.a, 'tokens')
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(self.git(self.a, 'show', '--format=', '--name-only', 'HEAD'), 'tokens')
        self.assertNotIn('unrelated', self.git(self.a, 'ls-tree', '--name-only', 'HEAD'))

    def test_remote_disjoint_changes_are_preserved(self):
        (self.a / 'schedule').write_text('new schedule')
        self.assertEqual(self.save(self.a, 'schedule').returncode, 0)
        (self.b / 'tokens').write_text('new tokens')
        child = self.save(self.b, 'tokens')
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual((self.b / 'schedule').read_text(), 'new schedule')
        self.assertEqual(self.git(self.origin, 'show', 'master:tokens'), 'new tokens')
        self.assertEqual(self.git(self.origin, 'show', 'master:schedule'), 'new schedule')

    def test_conflicting_token_changes_are_rejected_without_force_push(self):
        (self.a / 'tokens').write_text('first update')
        self.assertEqual(self.save(self.a, 'tokens').returncode, 0)
        (self.b / 'tokens').write_text('second update')
        child = self.save(self.b, 'tokens')
        self.assertNotEqual(child.returncode, 0)
        self.assertEqual(self.git(self.origin, 'show', 'master:tokens'), 'first update')
        self.assertFalse((self.b / '.git/rebase-merge').exists())


if __name__ == '__main__':
    unittest.main()
