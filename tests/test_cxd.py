"""Tests for cxd, ccd for Codex: reading an account's limits from Codex's app server, choosing the account,
the chat list and carrying a chat to another account's folder, adding and removing accounts. No network, never
starts the real codex (a stand-in app server answers instead). Run: python3 -I tests/test_cxd.py"""
import io, json, os, shutil, sys, tempfile, time, unittest
from contextlib import redirect_stderr, redirect_stdout
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from unittest import mock

os.environ['CCD_HOME'] = tempfile.mkdtemp(prefix='cxd-test-')  # never the real settings
os.environ['CCD_TOKEN_STORE'] = 'file'
os.environ.pop('CCD_DRY_RUN', None)
_loader = SourceFileLoader('ccd', os.path.join(os.path.dirname(__file__), '..', 'ccd'))
ccd = module_from_spec(spec_from_loader('ccd', _loader))
_loader.exec_module(ccd)
ccd.CLAUDE = ccd.CODEX = os.path.join(os.environ['CCD_HOME'], 'no-such-program')
ccd.CODEX_MAIN = os.path.join(os.environ['CCD_HOME'], 'codex-main')

FAKE_SERVER = r'''#!%s -I
import json, sys
answers = json.loads(%r)
for line in sys.stdin:
    m = json.loads(line)
    if m.get('method') in answers and 'id' in m:
        print(json.dumps({'id': m['id'], 'result': answers[m['method']]}), flush=True)
    elif m.get('method') == 'initialize':
        print(json.dumps({'id': m['id'], 'result': {}}), flush=True)
'''


def acct(key, week, five=0.0, blocked=False, home=None, org=None):
    return {'key': key, 'label': key, 'home': home or '/x/' + key, 'five': five, 'week': week, 'five_reset': 0,
            'week_reset': 0, 'blocked': blocked, 'org': org or key}


def signed_in(week_used=36, five_used=None, reached=None, resets=None):
    resets = resets or time.time() + 86400
    week = {'usedPercent': week_used, 'windowDurationMins': 10080, 'resetsAt': resets}
    five = five_used is not None and {'usedPercent': five_used, 'windowDurationMins': 300, 'resetsAt': resets}
    return {'account/read': {'account': {'type': 'chatgpt', 'planType': 'pro'}, 'userId': 'user-1',
                             'workspaceRouting': {'chatgptAccountId': 'acc-1'}},
            'account/rateLimits/read': {'rateLimits': {'primary': five or week, 'secondary': week if five else None,
                                                       'rateLimitReachedType': reached}}}


A, B, C, D, OLD = '01a2167a-5b39-72b1-af86-061d6873b493', '01a216a5-661a-7cc3-8e39-a399c6419df9', '01a21385-cfe1-7000-8000-000000000001', '01a21385-cfe1-7000-8000-000000000002', '01a1fc35-9611-71c1-a37d-cda861a00001'


def line(kind, **payload):
    return json.dumps({'type': kind, 'payload': payload}) + '\n'


def write_chat(home, sid, said=('fix the login page',), limited=False, originator='codex-tui', cwd='/tmp', age=0):
    path = os.path.join(home, 'sessions', '2026', '11', '26', 'rollout-2026-11-26T10-00-00-%s.jsonl' % sid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(line('session_meta', account_scoped=True, creator_user_id='user-1', creator_account_id='acc-1', session_id=sid,
                     id=sid, cwd=cwd, originator=originator, source='vscode', base_instructions={'text': 'x' * 5000}))
        f.write(line('response_item', type='message', role='user', content=[{'type': 'input_text', 'text': '# AGENTS.md'}]))
        for words in said:
            f.write(line('event_msg', type='item_completed',
                         item={'type': 'UserMessage', 'content': [{'type': 'text', 'text': words}]}))
            f.write(line('event_msg', type='task_complete', error=None))
        if limited:
            f.write(line('event_msg', type='task_complete', error={'codex_error_info': 'usage_limit_exceeded'}))
    if age:
        os.utime(path, (time.time() - age, time.time() - age))
    return path


class Folders(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='cxd-homes-')
        self.addCleanup(shutil.rmtree, self.root, True)
        self.main = os.path.join(self.root, 'codex')
        os.makedirs(self.main)
        p = mock.patch.object(ccd, 'CODEX_MAIN', self.main)
        p.start()
        self.addCleanup(p.stop)
        ccd.save_settings({})

    def home(self, key):
        h = os.path.join(self.root, 'codex-' + key)
        os.makedirs(h, exist_ok=True)
        d = ccd.settings()
        d['codex_accounts'] = (d.get('codex_accounts') or []) + [{'key': key, 'label': key.upper(), 'home': h}]
        ccd.save_settings(d)
        return h


class Ping(unittest.TestCase):
    def ping(self, answers, key='b'):
        with mock.patch.object(ccd, 'CODEX', '/bin/codex'), mock.patch.object(ccd, 'codex_ask', return_value=answers), \
                mock.patch.object(ccd.os.path, 'isdir', return_value=True):
            return ccd.codex_ping({'key': key, 'label': key, 'home': '/x'})

    def test_weekly_only_plan_shows_only_its_weekly_limit(self):
        a = self.ping(signed_in(36))
        self.assertEqual((a['week'], a['five'], a['blocked'], a['only_week']), (0.36, 0.0, False, True))
        self.assertEqual(ccd.how_full(a), 'weekly 36% used')

    def test_both_windows(self):
        a = self.ping(signed_in(40, five_used=90))
        self.assertEqual((a['five'], a['week'], a['only_week']), (0.9, 0.4, False))
        self.assertEqual(ccd.how_full(a), '5-hour 90% used, weekly 40% used')

    def test_limit_reached_is_blocked(self):
        self.assertTrue(self.ping(signed_in(100, reached='rate_limit_reached'))['blocked'])
        self.assertTrue(self.ping(signed_in(100))['blocked'])

    def test_a_window_that_has_reset_counts_as_empty(self):
        self.assertEqual(self.ping(signed_in(100, resets=time.time() - 5))['week'], 0.0)

    def test_signed_out_and_no_answer(self):
        self.assertIn('cxd add b', self.ping({'account/read': {'account': None}})['error'])
        self.assertIn('codex once', self.ping({'account/read': {'account': None}}, key='main')['error'])
        self.assertEqual(self.ping({})['error'], 'no answer from codex')

    def test_same_person_same_org(self):
        self.assertEqual(self.ping(signed_in())['org'], 'user-1/acc-1')
        a = signed_in()
        a['account/read'].pop('workspaceRouting')
        self.assertNotIn('org', self.ping(a))  # unknown workspace: never taken for another account

    def test_no_limits_answer_is_not_an_empty_account(self):
        for limits in (None, {'rateLimits': {'primary': None, 'secondary': None}}):
            a = signed_in()
            a['account/rateLimits/read'] = limits
            got = self.ping(a)
            self.assertNotIn('five', got)
            self.assertIn('how much is left', got['error'])

    def test_real_protocol_against_a_stand_in_app_server(self):
        d = tempfile.mkdtemp(prefix='cxd-fake-')
        self.addCleanup(shutil.rmtree, d, True)
        fake = os.path.join(d, 'codex')
        with open(fake, 'w') as f:
            f.write(FAKE_SERVER % (sys.executable, json.dumps(signed_in(51))))
        os.chmod(fake, 0o755)
        with mock.patch.object(ccd, 'CODEX', fake):
            a = ccd.codex_ping({'key': 'c', 'label': 'c', 'home': d})
        self.assertEqual((a['week'], a['blocked']), (0.51, False))

    def test_a_server_that_never_answers_times_out(self):
        with mock.patch.object(ccd, 'CODEX', '/bin/cat'):
            t = time.time()
            got = ccd.codex_ask('/tmp', ['account/read'], timeout=1)
        self.assertEqual(got, {})
        self.assertLess(time.time() - t, 5)


class Flags(unittest.TestCase):
    def test_default_and_his_own_modes(self):
        self.assertEqual(ccd.codex_flags({}, []), ['--dangerously-bypass-approvals-and-sandbox'])
        for own in (['--sandbox', 'read-only'], ['-a', 'never'], ['--ask-for-approval=on-request'], ['--full-auto']):
            self.assertEqual(ccd.codex_flags({}, own), [], own)
        self.assertEqual(ccd.codex_flags({}, ['exec', '--', '--sandbox']), ['--dangerously-bypass-approvals-and-sandbox'])
        self.assertEqual(ccd.codex_flags({'codex_args': []}, []), [])


def start(called, args, accts, menu=None):
    """Run cxd_main with checked accounts; returns (execve call or None, exit code or None, stderr)."""
    err = io.StringIO()
    make = mock.Mock(side_effect=menu) if isinstance(menu, type) else mock.Mock(return_value=menu)
    with mock.patch.object(ccd, 'CODEX', '/bin/codex'), mock.patch.object(ccd, 'codex_check', return_value=accts), \
            mock.patch.object(ccd, 'Menu', make), mock.patch.object(ccd.os, 'execve') as ex, \
            mock.patch.object(ccd.random, 'choice', side_effect=lambda xs: xs[0]), redirect_stderr(err):
        try:
            ccd.cxd_main(called, list(args))
            code = None
        except SystemExit as e:
            code = e.code
    return (ex.call_args[0] if ex.called else None), code, err.getvalue()


class Choose(unittest.TestCase):
    def test_most_room_wins_and_its_folder_is_used(self):
        call, _, err = start('cxd', ['fix it'], [acct('main', 1.0, blocked=True), acct('c', 0.51), acct('d', 0.36)])
        self.assertEqual(call[1], ['/bin/codex', '--dangerously-bypass-approvals-and-sandbox', 'fix it'])
        self.assertEqual(call[2]['CODEX_HOME'], '/x/d')
        self.assertIn('cxd: using d', err)

    def test_all_full_starts_the_usual_login(self):
        call, _, err = start('cxd', [], [acct('main', 1.0, blocked=True, home='/x/main'), acct('b', 1.0, blocked=True)])
        self.assertEqual(call[2]['CODEX_HOME'], ccd.CODEX_MAIN)
        self.assertIn('at its limit; starting with your usual login', err)

    def test_cxdm_starts_the_one_he_chooses(self):
        class Pick:
            def choose(self, rws):
                return rws[1]

            def close(self):
                pass
        call, _, _ = start('cxdm', [], [acct('main', 0.1), acct('c', 0.5)], Pick())
        self.assertEqual(call[2]['CODEX_HOME'], '/x/c')

    def test_cxdm_every_account_full_starts_nothing(self):
        class Never:
            def choose(self, rws):
                raise AssertionError('no list when nothing has room')

            def close(self):
                pass
        call, code, err = start('cxdm', [], [acct('main', 1.0, blocked=True)], Never())
        self.assertIsNone(call)
        self.assertEqual(code, 1)
        self.assertIn('every Codex account is at its limit', err)


class Chats(Folders):
    def test_only_his_terminal_chats_newest_and_stopped_first(self):
        b = self.home('b')
        write_chat(self.main, A, said=('first words', 'later words'), age=100)
        write_chat(b, B, limited=True, age=300)
        write_chat(self.main, C, originator='codex_exec')
        write_chat(self.main, D, age=ccd.RECENT + 60)
        with mock.patch.object(ccd, 'codex_open_files', return_value=set()):
            chs = ccd.codex_chats()
        self.assertEqual([c['id'] for c in chs], [B, A])
        self.assertEqual((chs[0]['account'], chs[0]['limited']), ('b', True))
        self.assertEqual((chs[1]['title'], chs[1]['said']), ('first words', 'later words'))

    def test_a_copied_chat_is_listed_once_as_its_newest_copy(self):
        b = self.home('b')
        write_chat(self.main, A, age=500)
        write_chat(b, A, said=('fix the login page', 'and the logout'))
        with mock.patch.object(ccd, 'codex_open_files', return_value=set()):
            chs = ccd.codex_chats()
        self.assertEqual([(c['id'], c['account']) for c in chs], [(A, 'b')])

    def test_by_id_however_old(self):
        write_chat(self.main, OLD, age=30 * 86400)
        with mock.patch.object(ccd, 'codex_open_files', return_value=set()):
            self.assertEqual([c['id'] for c in ccd.codex_chats(sid=OLD)], [OLD])
            self.assertEqual(ccd.codex_chats(sid=OLD[-12:]), [])  # never a near match

    def test_answering_again_after_a_limit_is_not_limited(self):
        p = write_chat(self.main, A, limited=True)
        with open(p, 'a') as f:
            f.write(line('event_msg', type='item_completed', item={'type': 'UserMessage', 'content': [{'text': 'go on'}]}))
            f.write(line('event_msg', type='task_complete', error=None))
        self.assertFalse(ccd.read_codex_chat(p, {'key': 'main', 'home': self.main})['limited'])


class Carry(Folders):
    def test_copies_into_the_new_account_and_resumes_with_the_note(self):
        d = self.home('d')
        src = write_chat(self.main, A, limited=True, cwd=self.root)
        chat = ccd.read_codex_chat(src, {'key': 'main', 'home': self.main})
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        with mock.patch.object(ccd, 'codex_open_files', return_value=set()), redirect_stderr(io.StringIO()):
            words = ccd.codex_carry_words(chat, d, [])
        self.assertEqual(words, ['resume', A, ccd.NUDGE])
        self.assertTrue(os.path.isfile(os.path.join(d, os.path.relpath(src, self.main))))
        self.assertEqual(os.path.realpath(os.getcwd()), os.path.realpath(self.root))

    def test_his_own_words_replace_the_note_and_the_same_folder_is_not_copied(self):
        src = write_chat(self.main, A, limited=True)
        chat = ccd.read_codex_chat(src, {'key': 'main', 'home': self.main})
        with mock.patch.object(ccd, 'codex_open_files', return_value=set()), \
                mock.patch.object(ccd.shutil, 'copy2') as cp, redirect_stderr(io.StringIO()):
            self.assertEqual(ccd.codex_carry_words(chat, self.main, ['keep going']), ['resume', A, 'keep going'])
        cp.assert_not_called()

    def test_an_open_copy_in_the_new_folder_or_no_lsof_starts_nothing(self):
        d = self.home('d')
        src = write_chat(self.main, A)
        chat = ccd.read_codex_chat(src, {'key': 'main', 'home': self.main})
        there = os.path.join(d, os.path.relpath(src, self.main))
        for live in ({os.path.realpath(there)}, None):
            with mock.patch.object(ccd, 'codex_open_files', return_value=live), self.assertRaises(SystemExit):
                ccd.codex_carry_words(chat, d, [])
        self.assertFalse(os.path.exists(there))

    def test_a_failed_copy_leaves_no_chat_file_behind(self):
        d = self.home('d')
        src = write_chat(self.main, A)
        chat = ccd.read_codex_chat(src, {'key': 'main', 'home': self.main})

        def half(a, b):
            open(b, 'w').write('{"type": "session_meta"')
            raise OSError('disk full')
        with mock.patch.object(ccd, 'codex_open_files', return_value=set()), \
                mock.patch.object(ccd.shutil, 'copy2', side_effect=half), self.assertRaises(OSError):
            ccd.codex_carry_words(chat, d, [])
        folder = os.path.dirname(os.path.join(d, os.path.relpath(src, self.main)))
        self.assertEqual(os.listdir(folder), [])

    def test_still_open_in_a_window_starts_nothing(self):
        src = write_chat(self.main, A)
        chat = ccd.read_codex_chat(src, {'key': 'main', 'home': self.main})
        with mock.patch.object(ccd, 'codex_open_files', return_value={os.path.realpath(src)}):
            with self.assertRaises(SystemExit) as e:
                ccd.codex_carry_words(chat, self.home('d'), [])
        self.assertIn('still open', str(e.exception.code))

    def test_a_limited_chat_moves_off_the_account_it_stopped_on(self):
        src = write_chat(self.main, A, limited=True)
        chat = ccd.read_codex_chat(src, {'key': 'main', 'home': self.main})
        with mock.patch.object(ccd, 'codex_carry_chat', return_value=chat), \
                mock.patch.object(ccd, 'codex_carry_words', side_effect=lambda c, h, x: ['resume', c['id']]):
            call, _, _ = start('cxdr', [A], [acct('main', 0.0, home=self.main), acct('c', 0.8)])
        self.assertEqual(call[2]['CODEX_HOME'], '/x/c')
        self.assertEqual(call[1][-2:], ['resume', A])


class AddRemove(Folders):
    def run_add(self, name, pings, tty=False):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(ccd, 'CODEX', '/bin/codex'), mock.patch.object(ccd, 'codex_ping', side_effect=pings), \
                mock.patch.object(ccd, 'codex_check', side_effect=lambda accts: [dict(a, org='other') for a in accts]), \
                mock.patch.object(ccd.os.path, 'expanduser', side_effect=lambda p: p.replace('~', self.root, 1)), \
                mock.patch.object(ccd.sys.stdin, 'isatty', return_value=tty), \
                mock.patch.object(ccd.subprocess, 'run') as run, redirect_stdout(out), redirect_stderr(err):
            try:
                code = ccd.cmd_cx_add([name])
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), run

    def test_a_new_folder_shares_his_settings_and_signs_in(self):
        with open(os.path.join(self.main, 'config.toml'), 'w') as f:
            f.write('model = "x"\n')
        os.makedirs(os.path.join(self.main, 'skills'))
        pings = [lambda a: dict(a, error='not signed in'), lambda a: dict(a, five=0.0, week=0.1, org='new')]
        code, out, run = self.run_add('Work', lambda a: pings.pop(0)(a), tty=True)
        home = os.path.join(self.root, '.codex-work')
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args[0][0], ['/bin/codex', 'login'])
        self.assertEqual(run.call_args[1]['env']['CODEX_HOME'], home)
        self.assertEqual(os.readlink(os.path.join(home, 'config.toml')), os.path.join(self.main, 'config.toml'))
        self.assertTrue(os.path.islink(os.path.join(home, 'skills')))
        self.assertFalse(os.path.lexists(os.path.join(home, 'AGENTS.md')))  # none to share
        self.assertEqual(ccd.codex_added(), [('work', 'Work', home)])

    def test_a_folder_already_signed_in_is_used_as_it_is(self):
        home = os.path.join(self.root, '.codex-b')
        os.makedirs(home)
        code, out, run = self.run_add('b', lambda a: dict(a, five=0.0, week=0.5, org='b'))
        self.assertEqual(code, 0)
        run.assert_not_called()
        self.assertEqual(os.listdir(home), [])
        self.assertIn('added b', out)

    def test_no_terminal_and_not_signed_in_leaves_nothing_behind(self):
        code, _, run = self.run_add('Work', lambda a: dict(a, error='not signed in'))
        self.assertIn('needs a terminal', code)
        self.assertFalse(os.path.lexists(os.path.join(self.root, '.codex-work')))
        self.assertEqual(ccd.codex_added(), [])

    def test_the_same_account_twice_is_refused(self):
        out = io.StringIO()
        with mock.patch.object(ccd, 'CODEX', '/bin/codex'), \
                mock.patch.object(ccd, 'codex_ping', side_effect=lambda a: dict(a, five=0.0, week=0.1, org='same')), \
                mock.patch.object(ccd, 'codex_check', side_effect=lambda accts: [dict(a, org='same') for a in accts]), \
                mock.patch.object(ccd.os.path, 'expanduser', side_effect=lambda p: p.replace('~', self.root, 1)), \
                redirect_stdout(out):
            with self.assertRaises(SystemExit) as e:
                ccd.cmd_cx_add(['Work'])
        self.assertIn('same account as Your Codex login', str(e.exception.code))
        self.assertFalse(os.path.lexists(os.path.join(self.root, '.codex-work')))

    def test_remove_forgets_but_keeps_the_folder(self):
        h = self.home('b')
        with redirect_stdout(io.StringIO()) as out:
            ccd.cmd_cx_remove(['B'])
        self.assertEqual(ccd.codex_added(), [])
        self.assertTrue(os.path.isdir(h))
        self.assertIn('left as it is', out.getvalue())
        with self.assertRaises(SystemExit):
            ccd.cmd_cx_remove(['main'])


class Dispatch(unittest.TestCase):
    def test_cxd_names_reach_the_codex_commands(self):
        for argv, fn in ((['cxd', 'accounts'], 'cmd_cx_accounts'), (['cxdm', 'add', 'x'], 'cmd_cx_add'),
                         (['/a/b/cxd', 'help'], 'cmd_cx_help')):
            with mock.patch.object(ccd.sys, 'argv', argv), \
                    mock.patch.dict(ccd.CX_COMMANDS, {argv[1]: mock.Mock(return_value=0)}) as cmds:
                with self.assertRaises(SystemExit):
                    ccd.main()
                cmds[argv[1]].assert_called_once_with(argv[2:])
        with mock.patch.object(ccd.sys, 'argv', ['cxdr', 'abc']), mock.patch.object(ccd, 'cxd_main', return_value=0) as m:
            with self.assertRaises(SystemExit):
                ccd.main()
        m.assert_called_once_with('cxdr', ['abc'])


if __name__ == '__main__':
    unittest.main()
