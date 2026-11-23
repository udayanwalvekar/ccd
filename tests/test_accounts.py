"""Tests for what ccd needs to work on anyone's Mac: accounts added with `ccd add` (kept in the Keychain or a 0600
file), `ccd remove`, `ccd accounts`, the first-run screen without a terminal, reading the token off the sign-in
screen, and the ccdm / ccdr names. No network, no real tokens, never touches the real Keychain or starts claude.
Run: python3 -I tests/test_accounts.py"""
import io, json, os, stat, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from importlib.machinery import SourceFileLoader
from unittest import mock

SANDBOX = tempfile.mkdtemp(prefix='ccd-test-')
os.environ['CCD_HOME'] = os.path.join(SANDBOX, 'config')  # before loading: where settings and tokens go
os.environ['CCD_TOKEN_STORE'] = 'file'
ccd = SourceFileLoader('ccd_accounts', os.path.join(os.path.dirname(__file__), '..', 'ccd')).load_module()
ccd.CLAUDE = os.path.join(SANDBOX, 'no-such-claude')  # a test that slips through to starting claude fails, never runs it

TOKEN = 'sk-ant-oat01-' + 'Ab3_-' * 20
OTHER = 'sk-ant-oat01-' + 'Zz9-_' * 20


def answering(five=0.1, week=0.2, org='org-a', by_token=None):
    """A stand-in for ping: every token answers with these figures (or per token, from by_token)."""
    def ping(a):
        f = (by_token or {}).get(a['token'], (five, week, org))
        if f is None:
            a['error'] = 'the token was revoked or has run out'
            return a
        a.update(five=f[0], week=f[1], org=f[2], blocked=False, five_reset=0, week_reset=0)
        return a
    return ping


class Clean(unittest.TestCase):
    def setUp(self):
        import shutil
        shutil.rmtree(ccd.HOME, ignore_errors=True)
        self.stdin = mock.patch.object(sys, 'stdin', io.StringIO(''))
        self.stdin.start()
        self.addCleanup(self.stdin.stop)

    def add(self, token, *words, ping=None):
        out, err = io.StringIO(), io.StringIO()
        sys.stdin = io.StringIO(token)
        with mock.patch.object(ccd, 'ping', side_effect=ping or answering()), redirect_stdout(out), redirect_stderr(err):
            try:
                code = ccd.cmd_add(list(words))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue() + err.getvalue() + (code if isinstance(code, str) else '')


class TokenStore(Clean):
    def test_a_token_is_kept_read_back_and_forgotten(self):
        ccd.token_put('work', TOKEN)
        self.assertEqual(ccd.token_get('work'), TOKEN)
        self.assertEqual(stat.S_IMODE(os.stat(ccd.TOKENS).st_mode), 0o600)  # nobody else on the Mac can read it
        ccd.token_del('work')
        self.assertIsNone(ccd.token_get('work'))

    def test_a_key_may_have_an_underscore_but_nothing_that_breaks_the_keychain_line(self):
        ccd.token_put('personal_200', TOKEN)  # keys carried over from an older setup look like this
        self.assertEqual(ccd.token_get('personal_200'), TOKEN)
        for bad in ('a b', 'a"b', 'A', 'a;b', ''):
            with self.assertRaises(ValueError):
                ccd.token_put(bad, TOKEN)

    def test_only_a_real_looking_token_is_kept(self):
        for bad in ('hello', 'sk-ant-api03-' + 'a' * 40, TOKEN + ' rm -rf', TOKEN + '"'):
            with self.assertRaises(ValueError):
                ccd.token_put('work', bad)

    def test_the_keychain_gets_the_token_on_stdin_never_on_a_command_line(self):
        calls = []

        def run(argv, **kw):
            calls.append((argv, kw.get('input')))
            return mock.Mock(returncode=0, stdout=TOKEN + '\n')
        with mock.patch.object(ccd, 'file_store', return_value=False), mock.patch.object(ccd.subprocess, 'run', run):
            ccd.token_put('work', TOKEN)
        for argv, _ in calls:
            self.assertFalse(any(TOKEN in w for w in argv), argv)  # `ps` shows every command line to everyone
        self.assertIn(TOKEN, calls[0][1])
        self.assertEqual(calls[0][0], [ccd.SECURITY, '-i'])

    def test_a_keychain_that_did_not_keep_it_is_an_error(self):
        with mock.patch.object(ccd, 'file_store', return_value=False), \
             mock.patch.object(ccd.subprocess, 'run', return_value=mock.Mock(returncode=44, stdout='')):
            with self.assertRaises(OSError):
                ccd.token_put('work', TOKEN)


class Settings(Clean):
    def write(self, d):
        os.makedirs(ccd.HOME, exist_ok=True)
        with open(ccd.CONFIG, 'w') as f:
            f.write(d if isinstance(d, str) else json.dumps(d))

    def test_no_settings_means_no_added_accounts(self):
        self.assertEqual(ccd.added(), [])

    def test_a_broken_settings_file_is_not_a_crash(self):
        for junk in ('{', '[]', '"x"', json.dumps({'accounts': 'x'}), json.dumps({'accounts': [1, None, {'key': 5}]})):
            self.write(junk)
            self.assertEqual(ccd.added(), [], junk)

    def test_an_unknown_plan_counts_as_unknown(self):
        self.write({'accounts': [{'key': 'a', 'label': 'A', 'plan': 300}, {'key': 'b', 'label': 'B', 'plan': 200}]})
        self.assertEqual(ccd.added(), [('a', 'A', None), ('b', 'B', 200)])

    def test_accounts_are_the_login_plus_every_added_one_that_still_has_its_token(self):
        self.write({'accounts': [{'key': 'a', 'label': 'A', 'plan': 200}, {'key': 'gone', 'label': 'Gone'}]})
        ccd.token_put('a', TOKEN)
        with mock.patch.object(ccd, 'login', return_value=None):
            self.assertEqual([(a['key'], a['token']) for a in ccd.accounts()], [('a', TOKEN)])


class Add(Clean):
    def test_a_piped_token_is_tested_then_kept_and_never_printed(self):
        code, said = self.add(TOKEN, 'Work', '200')
        self.assertEqual(code, 0)
        self.assertEqual(ccd.added(), [('work', 'Work', 200)])
        self.assertEqual(ccd.token_get('work'), TOKEN)
        self.assertNotIn(TOKEN[13:], said)
        self.assertIn('added Work', said)

    def test_a_token_that_does_not_answer_is_not_kept(self):
        code, said = self.add(TOKEN, 'Work', ping=answering(by_token={TOKEN: None}))
        self.assertNotEqual(code, 0)
        self.assertEqual(ccd.added(), [])
        self.assertIn('revoked', said)

    def test_not_a_token_is_refused_before_anything_is_sent(self):
        ping = mock.Mock()
        code, said = self.add('my password', 'Work', ping=ping)
        self.assertNotEqual(code, 0)
        ping.assert_not_called()
        self.assertEqual(ccd.added(), [])

    def test_the_same_token_twice_is_refused(self):
        self.add(TOKEN, 'Work')
        code, said = self.add(TOKEN, 'Again')
        self.assertNotEqual(code, 0)
        self.assertIn('already added, as Work', said)
        self.assertEqual(len(ccd.added()), 1)

    def test_a_second_token_for_the_same_account_is_refused(self):
        self.add(TOKEN, 'Work')
        code, said = self.add(OTHER, 'Again')  # same organisation, same figures = same account
        self.assertNotEqual(code, 0)
        self.assertIn('same account as Work', said)

    def test_a_teammate_in_the_same_organisation_is_a_different_account(self):
        both = answering(by_token={TOKEN: (0.1, 0.2, 'org-a'), OTHER: (0.6, 0.5, 'org-a')})
        self.add(TOKEN, 'Work', ping=both)
        code, _ = self.add(OTHER, 'Second', ping=both)
        self.assertEqual(code, 0)
        self.assertEqual([l for _, l, _ in ccd.added()], ['Work', 'Second'])

    def test_two_accounts_with_one_name_get_told_apart(self):
        both = answering(by_token={TOKEN: (0.1, 0.2, 'org-a'), OTHER: (0.3, 0.2, 'org-b')})
        self.add(TOKEN, 'Work', ping=both)
        self.add(OTHER, 'work', ping=both)
        self.assertEqual(ccd.added(), [('work', 'Work', None), ('work-2', 'work 2', None)])

    def test_main_is_never_a_key(self):
        self.assertEqual(ccd.slug('Main', set()), 'account')
        self.assertEqual(ccd.slug('!!!', set()), 'account')
        self.assertEqual(ccd.slug('Work', {'work'}), 'work-2')


class Remove(Clean):
    def remove(self, *words):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = ccd.cmd_remove(list(words))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue() + err.getvalue() + (code if isinstance(code, str) else '')

    def test_remove_forgets_the_account_and_its_token(self):
        self.add(TOKEN, 'Work')
        code, _ = self.remove('work')
        self.assertEqual(code, 0)
        self.assertEqual(ccd.added(), [])
        self.assertIsNone(ccd.token_get('work'))

    def test_a_name_that_matches_nobody_removes_nothing_and_lists_the_real_ones(self):
        self.add(TOKEN, 'Work')
        code, said = self.remove('wor')  # never a near match
        self.assertNotEqual(code, 0)
        self.assertIn('Yours: Work', said)
        self.assertEqual(len(ccd.added()), 1)

    def test_the_claude_code_login_is_not_ccds_to_remove(self):
        code, said = self.remove('main')
        self.assertIn('/logout', said)


class ReadingTheToken(unittest.TestCase):
    def test_a_token_on_one_line(self):
        self.assertEqual(ccd.tokens_in('Your OAuth token (valid for 1 year):\n\n%s\n\nStore this token securely.' % TOKEN)[-1], TOKEN)
        self.assertIn(TOKEN, ccd.tokens_in('Your OAuth token (valid for 1 year):\n\n%s\n\nStore this token securely.' % TOKEN))

    def test_a_token_wrapped_over_lines_with_colour_codes_is_read_whole_first(self):
        wrapped = '\x1b[1mYour OAuth token:\x1b[22m\r\n  \x1b[36m%s\r\n  %s\x1b[39m\r\n\r\nStore this token securely.' % (
            TOKEN[:60], TOKEN[60:])
        found = ccd.tokens_in(wrapped)
        self.assertEqual(found[0], TOKEN)

    def test_the_line_after_is_not_glued_on(self):
        found = ccd.tokens_in('%s\nStore this token securely.' % TOKEN)
        self.assertEqual(found, [TOKEN])

    def test_nothing_printed_nothing_found(self):
        self.assertEqual(ccd.tokens_in('Opening browser to sign in…\nCancelled'), [])


class Names(unittest.TestCase):
    def start(self, argv0, words=()):
        seen = {}

        class Stop(Exception):
            pass

        def carry_chat(given):
            seen['carry'] = True
            raise Stop

        def menu(*a):
            seen['menu'] = True
            raise OSError  # "no terminal": ccdm then picks by itself
        with mock.patch.object(sys, 'argv', [argv0] + list(words)), mock.patch.object(ccd, 'carry_chat', carry_chat), \
             mock.patch.object(ccd, 'Menu', side_effect=menu), mock.patch.object(ccd, 'accounts', return_value=[]), \
             mock.patch.object(ccd, 'auto_on', return_value=False), mock.patch.object(ccd.os, 'execve') as ex, \
             redirect_stderr(io.StringIO()) as err:
            try:
                ccd.main()
            except (Stop, SystemExit):
                pass
        seen['started'] = ex.called
        seen['said'] = err.getvalue()
        return seen

    def test_ccdm_asks_for_the_account(self):
        self.assertTrue(self.start('/Users/x/.local/bin/ccdm').get('menu'))

    def test_ccdr_asks_for_the_chat(self):
        self.assertTrue(self.start('/Users/x/.local/bin/ccdr').get('carry'))

    def test_plain_ccd_asks_nothing(self):
        seen = self.start('/Users/x/.local/bin/ccd')
        self.assertFalse(seen.get('menu') or seen.get('carry'))
        self.assertTrue(seen['started'])

    def test_no_account_at_all_just_starts_claude_without_a_warning(self):
        seen = self.start('ccd')
        self.assertTrue(seen['started'])
        self.assertEqual(seen['said'], '')

    def test_a_command_word_is_not_sent_to_claude(self):
        acc = mock.Mock(return_value=0)
        with mock.patch.dict(ccd.COMMANDS, {'accounts': acc}):
            seen = self.start('ccd', ['accounts'])
        acc.assert_called_once()
        self.assertFalse(seen['started'])


class Screens(Clean):
    def test_accounts_listing_without_a_terminal_has_no_colour_codes_and_shows_a_dead_token(self):
        self.add(TOKEN, 'Work')
        out = io.StringIO()
        with mock.patch.object(ccd, 'login', return_value=None), \
             mock.patch.object(ccd, 'ping', side_effect=answering(by_token={TOKEN: None})), redirect_stdout(out), \
             mock.patch.object(ccd, 'PLAIN', False):
            ccd.cmd_accounts([])
        self.assertNotIn('\x1b', out.getvalue())
        self.assertIn('Work', out.getvalue())
        self.assertIn('revoked', out.getvalue())

    def test_listing_lines_never_pass_the_window_edge(self):
        accts = [dict(key='a', label='A very long account name that goes on and on ' * 2, five=0.4, week=0.9,
                      blocked=False, org='o1', five_reset=0, week_reset=0)]
        with mock.patch.object(ccd, 'PLAIN', True):
            for cols in (40, 80, 120):
                for line in ccd.usage_lines(accts, cols):
                    self.assertLess(len(ccd.paint(line, cols)), cols)

    def test_setup_with_no_terminal_says_what_to_do_and_succeeds(self):
        out = io.StringIO()
        with mock.patch.object(ccd, 'Ask', side_effect=OSError), redirect_stdout(out):
            self.assertEqual(ccd.cmd_setup([]), 0)
        self.assertIn('ccd add', out.getvalue())
        self.assertNotIn('\x1b', out.getvalue())

    def test_add_with_no_terminal_and_no_piped_token_says_how(self):
        sys.stdin = mock.Mock(isatty=lambda: True)
        with mock.patch.object(ccd, 'Ask', side_effect=OSError):
            with self.assertRaises(SystemExit) as e:
                ccd.cmd_add([])
        self.assertIn('Pipe the token', str(e.exception.code))


class ExpiredLogin(unittest.TestCase):
    def keychain(self, expires_in):
        raw = json.dumps({'claudeAiOauth': {'accessToken': 'x', 'expiresAt': (__import__('time').time() + expires_in) * 1000,
                                            'rateLimitTier': 'default_claude_max_20x'}})
        with mock.patch.object(ccd.subprocess, 'run', return_value=mock.Mock(stdout=raw)):
            return ccd.login()

    def test_an_expired_login_is_kept_not_dropped(self):
        me = self.keychain(-60)
        self.assertIsNotNone(me)  # dropped, it would never be used again, so never renewed
        self.assertTrue(me['expired'])
        self.assertFalse(self.keychain(3600)['expired'])

    def test_an_expired_login_is_not_asked_over_the_network(self):
        with mock.patch.object(ccd.urllib.request, 'urlopen') as net:
            a = ccd.ping({'key': 'main', 'label': 'L', 'token': 'x', 'expired': True})
        net.assert_not_called()
        self.assertTrue(a['unchecked'])
        self.assertEqual(ccd.room(a), 0.5)

    def test_it_is_used_once_the_checked_accounts_are_half_full(self):
        def pick(other_used):
            accts = [{'key': 'main', 'label': 'L', 'token': 'x', 'plan': 200, 'expired': True},
                     {'key': 'work', 'label': 'W', 'token': TOKEN, 'plan': 200}]
            real = ccd.ping  # (patched below: keep the real one for the expired login)
            ping = lambda a: real(a) if a.get('expired') else dict(a, five=other_used, week=0.0, blocked=False, org='o')
            with mock.patch.object(sys, 'argv', ['ccd']), mock.patch.object(ccd, 'accounts', return_value=accts), \
                 mock.patch.object(ccd, 'ping', side_effect=ping), mock.patch.object(ccd, 'auto_on', return_value=False), \
                 mock.patch.object(ccd.random, 'choice', side_effect=lambda xs: xs[0]), \
                 mock.patch.object(ccd, 'login_org', return_value=None), \
                 mock.patch.object(ccd.os, 'execve') as ex, redirect_stderr(io.StringIO()) as err:
                ccd.main()
            env = ex.call_args.args[2]
            return env['CCD_ACCOUNT'], err.getvalue()
        self.assertEqual(pick(0.2)[0], 'work')
        who, said = pick(0.7)
        self.assertEqual(who, 'main')
        self.assertIn('not checked', said)

    def test_the_list_says_not_checked_instead_of_empty_bars(self):
        rws = [dict(key='main', label='Your login', five=0.0, week=0.0, blocked=False, unchecked=True),
               dict(key='w', label='Work', five=0.3, week=0.1, blocked=False, org='o')]
        text = '\n'.join(''.join(t for t, _ in l) for l in ccd.frame(rws, 1, 80, 30))
        self.assertIn('not checked', text)
        self.assertNotIn('  0%', text)


class ExpiredLoginTwin(unittest.TestCase):
    def accts(self, org_of_added, answered=True):
        me = dict(key='main', label='Your login', token='x', expired=True, unchecked=True, five=0.0, week=0.0, blocked=False)
        other = dict(key='team', label='Team', token=TOKEN)
        if answered:
            other.update(five=0.3, week=0.1, blocked=False, org=org_of_added)
        return [me, other]

    def keys(self, accts, login_org):
        with mock.patch.object(ccd, 'login_org', return_value=login_org):
            return [a['key'] for a in ccd.settle(accts)]

    def test_an_expired_login_of_an_added_accounts_organisation_shows_once(self):
        self.assertEqual(self.keys(self.accts('org-t'), 'org-t'), ['team'])

    def test_another_organisation_keeps_both(self):
        self.assertEqual(self.keys(self.accts('org-x'), 'org-t'), ['main', 'team'])

    def test_kept_when_that_account_did_not_answer_or_the_organisation_is_unknown(self):
        self.assertEqual(self.keys(self.accts('org-t', answered=False), 'org-t'), ['main', 'team'])
        self.assertEqual(self.keys(self.accts('org-t'), None), ['main', 'team'])

    def test_a_login_that_has_not_expired_is_left_to_the_usual_merge(self):
        accts = self.accts('org-t')
        accts[0].pop('unchecked')
        self.assertEqual(self.keys(accts, 'org-t'), ['main', 'team'])

    def test_every_check_goes_through_settle(self):
        src = open(os.path.join(os.path.dirname(__file__), '..', 'ccd')).read()
        self.assertEqual(src.count('pool.map(ping, accts)'), src.count('settle(list(pool.map(ping, accts)))'))


class EveryAccountFull(unittest.TestCase):
    def test_full_accounts_are_called_full_not_unreachable(self):
        accts = [dict(key='a', label='A', token=TOKEN, plan=None)]
        with mock.patch.object(sys, 'argv', ['ccd']), mock.patch.object(ccd, 'accounts', return_value=accts), \
             mock.patch.object(ccd, 'ping', side_effect=lambda a: dict(a, five=1.0, week=0.2, blocked=True, org='o')), \
             mock.patch.object(ccd, 'auto_on', return_value=False), mock.patch.object(ccd.os, 'execve'), \
             redirect_stderr(io.StringIO()) as err:
            ccd.main()
        self.assertIn('every account is at its limit', err.getvalue())


class NoAccountAtAll(unittest.TestCase):
    def test_ccdm_with_no_account_says_so_not_internet(self):
        with mock.patch.object(sys, 'argv', ['ccdm']), mock.patch.object(ccd, 'accounts', return_value=[]), \
             mock.patch.object(ccd, 'Menu', return_value=mock.Mock()), mock.patch.object(ccd.os, 'execve') as ex, \
             redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as e:
                ccd.main()
        self.assertIn('no account yet', str(e.exception.code))
        ex.assert_not_called()


class Help(unittest.TestCase):
    def test_help_says_what_the_name_means_and_lists_the_commands(self):
        out = io.StringIO()
        with redirect_stdout(out):
            ccd.cmd_help([])
        for want in ('Claude Code, dangerously', 'ccdm', 'ccdr', 'ccd add', 'ccd update'):
            self.assertIn(want, out.getvalue())


class Flags(unittest.TestCase):
    def test_chats_start_with_no_permission_prompts_unless_the_settings_say_so(self):
        self.assertEqual(ccd.claude_flags({}), ['--dangerously-skip-permissions'])
        self.assertEqual(ccd.claude_flags({'claude_args': []}), [])
        self.assertEqual(ccd.claude_flags({'claude_args': ['--model', 'x', 5]}), ['--model', 'x'])
        self.assertEqual(ccd.claude_flags({'claude_args': 'junk'}), ['--dangerously-skip-permissions'])


class Update(Clean):
    def update(self, body, version=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(ccd.urllib.request, 'urlopen', return_value=mock.Mock(read=lambda: body)), \
             mock.patch.object(ccd.subprocess, 'run', return_value=mock.Mock(returncode=0)) as run, \
             redirect_stdout(out), redirect_stderr(err):
            try:
                code = ccd.cmd_update([])
            except SystemExit as e:
                code = e.code
        return code, out.getvalue() + (code if isinstance(code, str) else ''), run

    def test_a_newer_file_is_run_over_this_one(self):
        body = b"#!/usr/bin/env bash\nVERSION = '9.9.9'\nCCD_PROGRAM_END\n"
        code, said, run = self.update(body)
        self.assertEqual(code, 0)
        self.assertIn('→ 9.9.9', said)
        self.assertEqual(run.call_args.args[0][0], '/bin/bash')

    def test_something_that_is_not_ccd_is_never_run(self):
        code, said, run = self.update(b'<html>rate limited</html>')
        self.assertNotEqual(code, 0)
        run.assert_not_called()

    def test_an_older_version_is_never_installed_over_a_newer_one(self):
        code, said, run = self.update(b"#!/usr/bin/env bash\nVERSION = '0.1.0'\nCCD_PROGRAM_END\n")
        self.assertEqual(code, 0)
        run.assert_not_called()

    def test_the_same_version_changes_nothing(self):
        body = ("#!/usr/bin/env bash\nVERSION = '%s'\nCCD_PROGRAM_END\n" % ccd.VERSION).encode()
        code, said, run = self.update(body)
        self.assertEqual(code, 0)
        run.assert_not_called()


class Uninstall(Clean):
    def test_uninstall_removes_its_links_tokens_and_settings_only(self):
        self.add(TOKEN, 'Work')
        bin_dir = os.path.join(SANDBOX, 'bin')
        os.makedirs(bin_dir, exist_ok=True)
        prog = os.path.join(SANDBOX, 'prog-ccd')
        open(prog, 'w').close()
        for n in ('ccd', 'ccdm'):
            os.symlink(prog, os.path.join(bin_dir, n))
        os.symlink('/bin/echo', os.path.join(bin_dir, 'ccdr'))  # someone else's: left alone
        with mock.patch.object(sys, 'argv', [prog]), mock.patch.dict(os.environ, {'PATH': bin_dir}), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(ccd.cmd_uninstall(['--yes']), 0)
        self.assertEqual(sorted(os.listdir(bin_dir)), ['ccdr'])
        self.assertFalse(os.path.exists(ccd.HOME))


if __name__ == '__main__':
    unittest.main()
