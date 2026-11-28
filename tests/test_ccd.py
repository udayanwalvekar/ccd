"""Tests for ccd: the plan filter (`ccd 200`), choosing by hand (`ccdm`), carrying a chat over to another account
(`ccdr`), the automatic move, and adding/removing accounts. No network, no real tokens, never starts claude.
Run: python3 -I tests/test_ccd.py"""
import io, json, os, re, signal, sys, tempfile, time, unittest
from contextlib import redirect_stderr
from importlib.machinery import SourceFileLoader
from unittest import mock

os.environ['CCD_HOME'] = tempfile.mkdtemp(prefix='ccd-test-')  # never the real settings or Keychain
os.environ['CCD_TOKEN_STORE'] = 'file'
os.environ['CCD_SELF_UPDATE'] = '0'  # never a real background update from a test
ccd = SourceFileLoader('ccd', os.path.join(os.path.dirname(__file__), '..', 'ccd')).load_module()
ccd.CLAUDE = os.path.join(os.environ['CCD_HOME'], 'no-such-claude')  # never the real claude, whatever slips through
ccd.FLAGS = ['--dangerously-skip-permissions']  # what most of these tests were written with (a setting, off by default)


def acct(key, plan, five=0.0, week=0.0, blocked=False, reachable=True):
    a = {'key': key, 'label': key, 'token': 'tok-' + key, 'plan': plan}
    if reachable:
        a.update(five=five, week=week, blocked=blocked)
    return a


class FakeMenu:
    """Stands in for the ccdm screen: `choice` picks from the listed rows (None = he pressed Esc)."""
    def __init__(self, choice=None, chat=None, how=None):
        self.choice, self.rows, self.closed = choice, None, 0
        self.chat, self.how, self.chats, self.waited = chat, how, None, None  # ccdr: the chat list, the wait screen

    def choose_chat(self, chs):
        self.chats = chs
        return self.chat(chs)

    def wait(self, chat, still_open):
        self.waited, self.was_open = chat, still_open()
        return self.how

    def choose(self, rws):
        self.rows = rws
        return self.choice(rws)

    def close(self):
        self.closed += 1


def run(argv, accts, menu=None, ping=lambda a: a):
    """Run ccd.main() with fake accounts; return (exec call or None, exit code or None, stderr).
    `menu` = a FakeMenu, or an exception class to act as "no terminal"."""
    err = io.StringIO()
    make = mock.Mock(side_effect=menu) if isinstance(menu, type) else mock.Mock(return_value=menu)
    with mock.patch.object(ccd, 'accounts', return_value=accts), \
         mock.patch.object(ccd, 'Menu', make), \
         mock.patch.object(ccd, 'ping', side_effect=ping), \
         mock.patch.object(ccd.os, '_exit', side_effect=SystemExit), \
         mock.patch.object(ccd, 'auto_on', return_value=False), \
         mock.patch.object(ccd.os, 'execve') as ex, \
         mock.patch.object(ccd.random, 'choice', side_effect=lambda xs: xs[0]), \
         mock.patch.object(sys, 'argv', ['ccd'] + argv), \
         mock.patch.dict(os.environ, {}, clear=False), redirect_stderr(err):
        os.environ.pop('CCD_DRY_RUN', None)
        try:
            ccd.main()
            code = None
        except SystemExit as e:
            code = e.code
    return (ex.call_args if ex.called else None), code, err.getvalue()


def picked(call):
    return call.args[2].get('CCD_ACCOUNT')


class PlanFilter(unittest.TestCase):
    MIX = [acct('team100', 100, five=0.05), acct('a200', 200, five=0.70), acct('b200', 200, five=0.10, week=0.30)]

    def test_plain_ccd_picks_most_room_across_all_plans(self):
        call, code, _ = run([], self.MIX)
        self.assertEqual(picked(call), 'team100')

    def test_200_never_picks_a_100_account(self):
        call, code, _ = run(['200'], self.MIX)
        self.assertEqual(picked(call), 'b200')  # 70% left beats a200's 30% left; team100 (95% left) excluded

    def test_200_uses_weekly_limit_too(self):
        accts = [acct('a200', 200, five=0.10, week=0.90), acct('b200', 200, five=0.40, week=0.40)]
        call, _, _ = run(['200'], accts)
        self.assertEqual(picked(call), 'b200')

    def test_200_with_only_one_200_account_uses_it(self):
        call, _, err = run(['200'], [acct('team100', 100), acct('a200', 200, five=0.5)])
        self.assertEqual(picked(call), 'a200')
        self.assertIn('using a200', err)

    def test_200_skips_a_rate_limited_200_account(self):
        call, _, _ = run(['200'], [acct('a200', 200, blocked=True), acct('b200', 200, five=0.9)])
        self.assertEqual(picked(call), 'b200')

    def test_200_stops_when_every_200_account_is_out(self):
        call, code, err = run(['200'], [acct('team100', 100), acct('a200', 200, blocked=True),
                                        acct('b200', 200, reachable=False)])
        self.assertIsNone(call)
        self.assertIn('no $200 account has room', str(code))

    def test_200_stops_when_no_200_account_exists(self):
        call, code, _ = run(['200'], [acct('team100', 100)])
        self.assertIsNone(call)
        self.assertIn('no $200 account is set up', str(code))

    def test_100_picks_only_100_accounts(self):
        call, _, _ = run(['100'], self.MIX)
        self.assertEqual(picked(call), 'team100')

    def test_unknown_plan_accounts_excluded_from_200(self):
        call, _, _ = run(['200'], [acct('third', None), acct('a200', 200, five=0.9)])
        self.assertEqual(picked(call), 'a200')


class Launch(unittest.TestCase):
    def test_number_is_not_passed_to_claude_but_other_words_are(self):
        call, _, _ = run(['200', '-p', 'hi', '--model', 'haiku'], [acct('a200', 200)])
        self.assertEqual(call.args[1], [ccd.CLAUDE] + ccd.FLAGS + ['-p', 'hi', '--model', 'haiku'])

    def test_plain_args_still_pass_through(self):
        call, _, _ = run(['--resume'], [acct('a200', 200)])
        self.assertEqual(call.args[1][-1], '--resume')

    def test_other_numbers_are_not_treated_as_a_plan(self):
        call, _, _ = run(['50'], [acct('team100', 100), acct('a200', 200)])
        self.assertEqual(call.args[1][-1], '50')

    def test_backup_gets_its_token_main_gets_keychain(self):
        call, _, _ = run(['200'], [acct('a200', 200)])
        self.assertEqual(call.args[2]['CLAUDE_CODE_OAUTH_TOKEN'], 'tok-a200')
        with mock.patch.dict(os.environ, {'CLAUDE_CODE_OAUTH_TOKEN': 'from-zshrc'}):
            call, _, _ = run(['200'], [acct('main', 200)])
        self.assertNotIn('CLAUDE_CODE_OAUTH_TOKEN', call.args[2])


def row(key, five=0.0, week=0.0, blocked=False, org=None, label=None):
    return {'key': key, 'label': label or key, 'token': 'tok-' + key, 'plan': 200, 'five': five, 'week': week,
            'blocked': blocked, 'org': org, 'five_reset': 0.0, 'week_reset': 0.0}


class ChooseByHand(unittest.TestCase):
    """ccdm = `ccd --pick`: the account he chooses is the one that starts."""
    MIX = [acct('team100', 100, five=0.05), acct('a200', 200, five=0.70), acct('b200', 200, five=0.10, week=0.30)]

    def test_his_choice_wins_over_the_one_with_most_room(self):
        menu = FakeMenu(lambda rws: next(r for r in rws if r['key'] == 'a200'))
        call, code, err = run(['--pick'], self.MIX, menu)
        self.assertEqual(picked(call), 'a200')  # plain ccd would have started team100
        self.assertEqual(call.args[2]['CLAUDE_CODE_OAUTH_TOKEN'], 'tok-a200')
        self.assertIn('using a200', err)
        self.assertEqual(menu.closed, 1)

    def test_pick_flag_is_not_passed_to_claude(self):
        menu = FakeMenu(lambda rws: rws[0])
        call, _, _ = run(['--pick', '--resume'], self.MIX, menu)
        self.assertEqual(call.args[1], [ccd.CLAUDE] + ccd.FLAGS + ['--resume'])

    def test_esc_starts_nothing(self):
        menu = FakeMenu(lambda rws: None)
        call, code, _ = run(['--pick'], self.MIX, menu)
        self.assertIsNone(call)
        self.assertEqual(code, 130)
        self.assertEqual(menu.closed, 1)

    def test_ctrl_c_starts_nothing_and_puts_the_terminal_back(self):
        def boom(rws):
            raise KeyboardInterrupt
        menu = FakeMenu(boom)
        call, code, _ = run(['--pick'], self.MIX, menu)
        self.assertIsNone(call)
        self.assertEqual(code, 130)
        self.assertEqual(menu.closed, 1)

    def test_ccdm_200_lists_only_200_accounts(self):
        menu = FakeMenu(lambda rws: rws[0])
        run(['--pick', '200'], self.MIX, menu)
        self.assertEqual([r['key'] for r in menu.rows], ['a200', 'b200'])

    def test_choosing_the_login_uses_the_keychain_not_a_token(self):
        menu = FakeMenu(lambda rws: rws[0])
        with mock.patch.dict(os.environ, {'CLAUDE_CODE_OAUTH_TOKEN': 'from-zshrc'}):
            call, _, _ = run(['--pick'], [acct('main', 200), acct('a200', 200)], menu)
        self.assertEqual(picked(call), 'main')
        self.assertNotIn('CLAUDE_CODE_OAUTH_TOKEN', call.args[2])

    def test_no_terminal_falls_back_to_most_room(self):
        call, _, err = run(['--pick'], self.MIX, OSError)
        self.assertEqual(picked(call), 'team100')
        self.assertIn('no terminal to ask in', err)

    def test_ctrl_c_while_still_checking_leaves_at_once(self):
        # A slow check must not hold the screen: the terminal is put back, then a hard exit (no waiting on threads).
        def slow(a):
            raise KeyboardInterrupt
        menu = FakeMenu(lambda rws: self.fail('list shown'))
        with mock.patch.object(ccd.os, '_exit', side_effect=SystemExit) as hard:
            call, code, _ = run(['--pick'], self.MIX, menu, ping=slow)
            self.assertIsNone(call)
        self.assertGreaterEqual(menu.closed, 1)

    def test_every_account_full_says_so_and_starts_nothing(self):
        import time
        full = [dict(row('a', 0.2, 1.0, blocked=True, label='Team'), week_reset=time.time() + 7200 + 30),
                dict(row('b', 1.0, 0.3, blocked=True, label='Mine'), five_reset=time.time() + 600 + 30)]
        menu = FakeMenu(lambda rws: self.fail('list shown'))
        call, code, err = run(['--pick'], full, menu)
        self.assertIsNone(call)
        self.assertEqual(code, 1)
        self.assertIn('every account is at its limit. Nothing started.', err)
        self.assertIn('Team: resets in 2h 0m', err)   # weekly is the one that is full
        self.assertIn('Mine: resets in 10m', err)     # 5-hour is the one that is full
        self.assertEqual(menu.closed, 1)

    def test_no_account_answering_says_so_and_starts_nothing(self):
        menu = FakeMenu(lambda rws: self.fail('list shown'))
        call, code, _ = run(['--pick'], [acct('a200', 200, reachable=False)], menu)
        self.assertIsNone(call)
        self.assertIn('could not reach any account', str(code))

    def test_plain_ccd_with_every_account_full_still_starts_as_before(self):
        call, code, err = run([], [acct('a200', 200, blocked=True)])
        self.assertIsNotNone(call)
        self.assertIn('starting with your usual login', err)

    def test_plain_ccd_never_opens_the_menu(self):
        menu = FakeMenu(lambda rws: self.fail('menu opened'))
        call, _, _ = run([], self.MIX, menu)
        self.assertEqual(picked(call), 'team100')
        self.assertEqual(menu.closed, 0)


class MenuRows(unittest.TestCase):
    def test_accounts_that_did_not_answer_are_left_out(self):
        got = ccd.rows([row('a'), {'key': 'dead', 'label': 'dead', 'token': 't', 'plan': None}])
        self.assertEqual([r['key'] for r in got], ['a'])

    def test_login_and_its_added_twin_show_once_named_by_owner(self):
        got = ccd.rows([row('main', 0.4, 0.6, org='team', label='your login ($100)'),
                        row('second', 0.4, 0.6, org='team', label='Team account ($100)'),
                        row('alex', 0.1, 0.1, org='k')])
        self.assertEqual([(r['key'], r['label']) for r in got],
                         [('main', 'Team account ($100)'), ('alex', 'alex')])

    def test_two_people_in_one_team_stay_two_rows(self):
        got = ccd.rows([row('main', 0.4, 0.6, org='team'), row('second', 0.1, 0.2, org='team')])
        self.assertEqual([r['key'] for r in got], ['main', 'second'])

    def test_rows_do_not_change_the_accounts_they_came_from(self):
        a = row('main', org='team', label='your login')
        ccd.rows([a, row('second', org='team', label='Team')])
        self.assertEqual(a['label'], 'your login')


class MenuKeys(unittest.TestCase):
    ROWS = [row('a'), row('b', blocked=True), row('c')]

    def test_arrows_skip_an_account_at_its_limit_and_wrap(self):
        self.assertEqual(ccd.press(self.ROWS, 0, 'down'), (2, None))
        self.assertEqual(ccd.press(self.ROWS, 2, 'down'), (0, None))
        self.assertEqual(ccd.press(self.ROWS, 0, 'up'), (2, None))

    def test_enter_starts_the_highlighted_one(self):
        self.assertEqual(ccd.press(self.ROWS, 2, 'enter'), (2, 'go'))

    def test_a_number_starts_that_account(self):
        self.assertEqual(ccd.press(self.ROWS, 0, '3'), (2, 'go'))

    def test_a_number_for_a_full_or_missing_account_does_nothing(self):
        self.assertEqual(ccd.press(self.ROWS, 0, '2'), (0, None))
        self.assertEqual(ccd.press(self.ROWS, 0, '7'), (0, None))
        self.assertEqual(ccd.press(self.ROWS, 0, '0'), (0, None))

    def test_esc_and_q_back_out_other_keys_do_nothing(self):
        self.assertEqual(ccd.press(self.ROWS, 0, 'esc')[1], 'quit')
        self.assertEqual(ccd.press(self.ROWS, 0, 'q')[1], 'quit')
        for junk in ('', 'x', '\xb2', '~'):
            self.assertEqual(ccd.press(self.ROWS, 0, junk), (0, None))

    def keys(self, sent):
        """Feed raw bytes through a real pipe into Menu.key()."""
        r, w = os.pipe()
        os.write(w, sent)
        os.close(w)
        m = ccd.Menu.__new__(ccd.Menu)
        m.fd = r
        out = []
        while True:
            k = m.key()
            out.append(k)
            if k == 'esc':  # end of input reads as Esc
                os.close(r)
                return out[:-1]

    def test_raw_keys_are_read_as_whole_keys(self):
        self.assertEqual(self.keys(b'\x1b[A\x1b[B\x1bOA\r2'), ['up', 'down', 'up', 'enter', '2'])

    def test_a_long_key_code_never_leaks_a_digit(self):
        # Ctrl+Up is Esc [ 1 ; 5 A and Page Down is Esc [ 6 ~ : the digits inside must not pick account 1, 5 or 6.
        self.assertEqual(self.keys(b'\x1b[1;5A\x1b[6~'), ['up', ''])


class MenuScreen(unittest.TestCase):
    ROWS = [row('main', 0.12, 0.37, label="Sam's Max plan ($200)"), row('second', 0.4, 0.69, blocked=True,
            label='Team account ($100)'), row('alex', 0.03, 0.01, label="Alex's account ($200)")]
    plain = staticmethod(lambda line: re.sub(r'\x1b\[[0-9;]*m', '', line))

    def screen(self, at, cols, lines):
        return [self.plain(ccd.paint(l, cols)) for l in ccd.frame(self.ROWS, at, cols, lines)]

    def test_nothing_is_wider_than_the_window_or_taller(self):
        for cols in (30, 48, 80, 140):
            for lines in (8, 12, 24, 50):
                got = self.screen(0, cols, lines)
                self.assertLessEqual(max(map(len, got)), cols - 1, (cols, lines))
                if lines >= 3 + len(self.ROWS) + 2:
                    self.assertLessEqual(len(got), lines, (cols, lines))

    def test_shows_every_account_its_numbers_and_the_marker(self):
        got = '\n'.join(self.screen(2, 100, 40))
        for want in ("1  Sam's Max plan ($200)", '2  Team account ($100)   at its limit',
                     "❯ 3  Alex's account ($200)   most room", ' 12%', ' 37%', '  3%'):
            self.assertIn(want, got)
        self.assertEqual(got.count('❯'), 1)

    def test_short_window_gets_one_line_per_account(self):
        got = self.screen(0, 100, 10)
        self.assertEqual(len(got), 3 + 3 + 2)
        self.assertIn('5-hour 12% · weekly 37%', '\n'.join(got))

    def test_bar_is_always_exactly_its_width(self):
        for used in (0, 0.004, 0.12, 0.5, 0.999, 1, 1.4):
            self.assertEqual(sum(len(t) for t, _ in ccd.bar(used, 20)), 20, used)


class KeychainPlan(unittest.TestCase):
    def keychain(self, tier):
        import json, time
        raw = json.dumps({'claudeAiOauth': {'accessToken': 'x', 'expiresAt': (time.time() + 3600) * 1000,
                                            'rateLimitTier': tier}})
        with mock.patch.object(ccd.subprocess, 'run', return_value=mock.Mock(stdout=raw)), \
             mock.patch('builtins.open', side_effect=OSError):
            return [a for a in ccd.accounts() if a['key'] == 'main'][0]

    def test_max_20x_login_counts_as_200(self):
        self.assertEqual(self.keychain('default_claude_max_20x')['plan'], 200)

    def test_max_5x_login_counts_as_100(self):
        self.assertEqual(self.keychain('default_claude_max_5x')['plan'], 100)




# ---- ccdr (`ccd --carry`): carry a chat over to another account ---------------------------------------
LIMIT_TEXT = "You've hit your 5-hour limit · resets 5pm (Asia/Calcutta)"


def stamp(ago=0):
    return time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(time.time() - ago))


def he_said(text, cwd='/work/here', entry='cli', ago=0):
    return {'type': 'user', 'message': {'role': 'user', 'content': text}, 'cwd': cwd, 'entrypoint': entry,
            'timestamp': stamp(ago)}


def it_said(text='done', ago=0, **more):
    return dict({'type': 'assistant', 'timestamp': stamp(ago), 'cwd': '/work/here', 'entrypoint': 'cli',
                 'message': {'role': 'assistant', 'model': 'claude-opus-5-5',
                             'content': [{'type': 'text', 'text': text}]}}, **more)


def limit_hit(ago=0):
    return {'type': 'assistant', 'timestamp': stamp(ago), 'isApiErrorMessage': True, 'error': 'rate_limit',
            'apiError': 'usage_limit_reached', 'cwd': '/work/here', 'entrypoint': 'cli',
            'message': {'role': 'assistant', 'model': '<synthetic>', 'content': [{'type': 'text', 'text': LIMIT_TEXT}]}}


OFF_TEXT = ('Your organization has disabled Claude subscription access for Claude Code · Use an Anthropic API key '
            'instead, or ask your admin to enable access')


def switched_off(ago=0):
    """The line claude saved on 27 Nov 2026 when an account that had worked all day was refused mid-chat."""
    return {'type': 'assistant', 'timestamp': stamp(ago), 'isApiErrorMessage': True, 'error': 'oauth_org_not_allowed',
            'cwd': '/work/here', 'entrypoint': 'cli',
            'message': {'role': 'assistant', 'model': '<synthetic>', 'content': [{'type': 'text', 'text': OFF_TEXT}]}}


WAITING = {'type': 'system', 'subtype': 'informational',
           'content': 'Usage limit reached · continuing automatically at 5pm · esc to cancel'}


class Disk(unittest.TestCase):
    """A stand-in for ~/.claude: saved chats under projects/, open windows under sessions/."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.projects = os.path.join(self.tmp.name, 'projects')
        self.live = os.path.join(self.tmp.name, 'sessions')
        os.makedirs(self.projects)
        os.makedirs(self.live)
        for name, value in (('PROJECTS', self.projects), ('LIVE', self.live)):
            patch = mock.patch.object(ccd, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def chat(self, sid, lines, folder='-work-here', age=0, raw_head=b''):
        d = os.path.join(self.projects, folder)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, sid + '.jsonl')
        with open(path, 'wb') as f:
            f.write(raw_head)
            for line in lines:
                f.write(json.dumps(line).encode() + b'\n')
        if age:
            os.utime(path, (time.time() - age,) * 2)
        return path

    def window(self, sid, pid, **more):
        with open(os.path.join(self.live, '%d.json' % pid), 'w') as f:
            json.dump(dict({'pid': pid, 'sessionId': sid, 'name': 'sam-x1', 'status': 'idle'}, **more), f)

    def found(self):
        return {c['id']: c for c in ccd.chats()}


class ChatList(Disk):
    def test_a_chat_that_stopped_at_its_limit_is_marked(self):
        self.chat('aaa', [he_said('make the page'), it_said('working on it'), limit_hit()])
        self.assertTrue(self.found()['aaa']['limited'])

    def test_the_line_claude_adds_while_it_waits_does_not_hide_the_mark(self):
        self.chat('aaa', [he_said('make the page'), limit_hit(), WAITING, {'type': 'cost-state'}])
        self.assertTrue(self.found()['aaa']['limited'])

    def test_a_chat_that_carried_on_after_its_limit_is_not_marked(self):
        self.chat('aaa', [he_said('make the page'), limit_hit(600), he_said('continue', ago=60), it_said('done', ago=30)])
        self.assertFalse(self.found()['aaa']['limited'])

    def test_a_chat_that_hit_the_limit_again_when_he_retried_is_marked(self):
        self.chat('aaa', [he_said('make the page'), limit_hit(600), he_said('continue', ago=60), limit_hit(59)])
        self.assertTrue(self.found()['aaa']['limited'])

    def test_a_chat_that_never_hit_a_limit_is_not_marked(self):
        self.chat('aaa', [he_said('make the page'), it_said('done')])
        self.assertFalse(self.found()['aaa']['limited'])

    def test_a_chat_stopped_because_its_account_was_switched_off_is_marked(self):
        self.chat('aaa', [he_said('make the page'), it_said('working on it'), switched_off()])
        found = self.found()['aaa']
        self.assertEqual((found['limited'], found['why']), (True, 'off'))

    def test_a_switched_off_account_is_known_by_its_mark_even_if_the_wording_changes(self):
        off = switched_off()
        off['message'] = dict(off['message'], content=[{'type': 'text', 'text': 'Some new wording'}])
        self.chat('aaa', [he_said('make the page'), off])
        self.assertTrue(self.found()['aaa']['limited'])

    def test_a_chat_that_carried_on_after_being_switched_off_is_not_marked(self):
        self.chat('aaa', [he_said('make the page'), switched_off(600), he_said('continue', ago=60), it_said('done', ago=30)])
        self.assertFalse(self.found()['aaa']['limited'])

    def test_a_usage_limit_says_so(self):
        self.chat('aaa', [he_said('make the page'), limit_hit()])
        self.assertEqual(self.found()['aaa']['why'], 'limit')

    def test_another_kind_of_error_is_not_a_limit(self):
        oops = dict(limit_hit(), error='server_error', apiError='overloaded')
        oops['message'] = dict(oops['message'], content=[{'type': 'text', 'text': 'API Error: 529 overloaded'}])
        self.chat('aaa', [he_said('make the page'), oops])
        self.assertFalse(self.found()['aaa']['limited'])

    def test_helper_agent_lines_do_not_clear_the_mark(self):
        self.chat('aaa', [he_said('make the page'), limit_hit(), it_said('helper finished', isSidechain=True)])
        self.assertTrue(self.found()['aaa']['limited'])

    def test_chats_run_by_scripts_are_left_out(self):
        self.chat('bot', [he_said('nightly job', entry='sdk-cli'), it_said('ok', entrypoint='sdk-cli')])
        self.chat('his', [he_said('make the page'), it_said('ok')])
        self.assertEqual(list(self.found()), ['his'])

    def test_helper_agent_transcripts_are_not_listed(self):
        self.chat('his', [he_said('make the page'), it_said('ok')])
        self.chat('agent-a1', [he_said('sub task'), it_said('ok')], folder='-work-here/his/subagents')
        self.assertEqual(list(self.found()), ['his'])

    def test_chats_untouched_for_days_are_left_out(self):
        self.chat('old', [he_said('last week'), limit_hit()], age=5 * 86400)
        self.chat('new', [he_said('today'), it_said('ok')])
        self.assertEqual(list(self.found()), ['new'])

    def test_name_is_his_own_rename_first(self):
        self.chat('aaa', [he_said('hello'), {'type': 'ai-title', 'aiTitle': 'Auto name'},
                          {'type': 'custom-title', 'customTitle': 'anthropic ipo'}, {'type': 'ai-title', 'aiTitle': 'Auto name 2'}])
        self.assertEqual(self.found()['aaa']['title'], 'anthropic ipo')

    def test_name_is_the_auto_title_when_he_gave_none(self):
        self.chat('aaa', [he_said('hello'), {'type': 'ai-title', 'aiTitle': 'Old name'}, {'type': 'ai-title', 'aiTitle': 'Sound and music'}])
        self.assertEqual(self.found()['aaa']['title'], 'Sound and music')

    def test_name_falls_back_to_his_last_words(self):
        self.chat('aaa', [he_said('fix the header on the events page'),
                          {'type': 'last-prompt', 'lastPrompt': 'fix the header on the events page'}])
        c = self.found()['aaa']
        self.assertEqual(c['title'], 'fix the header on the events page')
        self.assertEqual(c['said'], 'fix the header on the events page')

    def test_his_last_words_skip_tool_output_lines(self):
        tool = {'type': 'user', 'cwd': '/work/here', 'entrypoint': 'cli', 'timestamp': stamp(),
                'message': {'role': 'user', 'content': [{'type': 'tool_result', 'content': 'file saved'}]}}
        self.chat('aaa', [he_said('ship the fix'), it_said('on it'), tool])
        self.assertEqual(self.found()['aaa']['said'], 'ship the fix')

    def test_stopped_chats_come_first_then_the_newest(self):
        self.chat('busy-new', [he_said('a', ago=10), it_said('ok', ago=5)])
        self.chat('stopped-old', [he_said('b', ago=7000), limit_hit(6900)])
        self.chat('stopped-new', [he_said('c', ago=900), limit_hit(800)])
        self.chat('busy-old', [he_said('d', ago=5000), it_said('ok', ago=4000)])
        self.assertEqual([c['id'] for c in ccd.chats()], ['stopped-new', 'stopped-old', 'busy-new', 'busy-old'])

    def test_when_is_the_moment_it_stopped(self):
        self.chat('aaa', [he_said('b', ago=7000), limit_hit(1560), WAITING])
        self.assertAlmostEqual(time.time() - self.found()['aaa']['when'], 1560, delta=5)

    def test_start_folder_is_where_the_chat_began_not_where_it_wandered(self):
        self.chat('aaa', [he_said('begin', cwd='/work/here'), he_said('later', cwd='/work/here/deep/inside'), it_said('ok')])
        self.assertEqual(self.found()['aaa']['cwd'], '/work/here')

    def test_only_the_end_of_a_huge_chat_is_read(self):
        junk = (b'{"type":"user","cwd":"/work/here","entrypoint":"cli","message":{"role":"user","content":"start"}}\n'
                + b'x' * (3 * ccd.TAIL) + b'\n')  # megabytes of history in one line, cut where the reading starts
        self.chat('big', [{'type': 'ai-title', 'aiTitle': 'Long film edit'}, he_said('render it', cwd='/work/here/deep'),
                          limit_hit()], raw_head=junk)
        with mock.patch.object(ccd.json, 'loads', wraps=json.loads) as parse:
            c = self.found()['big']
        self.assertEqual((c['title'], c['limited'], c['cwd']), ('Long film edit', True, '/work/here'))
        self.assertLess(max(len(call.args[0]) for call in parse.call_args_list), ccd.TAIL)

    def test_a_broken_or_empty_file_is_skipped_quietly(self):
        self.chat('empty', [])
        self.chat('junk', [], raw_head=b'not json at all\n{"half":')
        self.chat('his', [he_said('make the page'), it_said('ok')])
        self.assertEqual(list(self.found()), ['his'])

    def test_a_chat_open_in_a_window_is_seen_as_open(self):
        self.chat('aaa', [he_said('make the page'), limit_hit()])
        self.window('aaa', os.getpid(), status='shell')
        c = self.found()['aaa']
        self.assertEqual((c['open']['name'], c['open']['status']), ('sam-x1', 'shell'))

    def test_a_window_that_has_closed_is_not_open(self):
        self.chat('aaa', [he_said('make the page'), limit_hit()])
        self.window('aaa', 2 ** 22 + 12345)  # no such process
        self.assertIsNone(self.found()['aaa']['open'])

    def test_a_leftover_window_file_whose_number_now_belongs_to_another_program_is_not_open(self):
        self.chat('aaa', [he_said('make the page'), limit_hit()])
        self.window('aaa', os.getpid(), procStart='Mon Jan  5 01:02:03 2015')  # this process did not start then
        self.assertIsNone(self.found()['aaa']['open'])

    def test_find_by_id_reaches_old_and_script_chats_too(self):
        self.chat('old', [he_said('last month', entry='sdk-cli'), limit_hit()], age=40 * 86400)
        self.assertTrue(ccd.find_chat('old')['limited'])
        self.assertIsNone(ccd.find_chat('ol'))  # a near miss matches nobody
        self.assertIsNone(ccd.find_chat('../old'))


def a_chat(sid='chat-1', limited=True, live=None, cwd='/work/here', title='Sound and music'):
    return {'id': sid, 'title': title, 'said': 'render it', 'cwd': cwd, 'when': time.time() - 300,
            'limited': limited, 'open': live}


def carry(argv, found, menu=None, accts=None, dry=False, live_account=None):
    """Run `ccd --carry …` with these chats on disk; team account full, Ultra with room unless told otherwise."""
    if accts is None:
        accts = [acct('team', 100, five=1.02, blocked=True), acct('ultra', 200, five=0.2)]
    by_id = lambda i: next((c for c in found if c['id'] == i), None)
    live = {c['id']: c['open'] for c in found if c['open']}
    with mock.patch.object(ccd, 'chats', return_value=found), mock.patch.object(ccd, 'find_chat', side_effect=by_id), \
         mock.patch.object(ccd, 'open_chats', return_value=live), mock.patch.object(ccd, 'running', return_value=True), \
         mock.patch.object(ccd, 'account_of', side_effect=lambda pid: (live_account or {}).get(pid)), \
         mock.patch.object(ccd, 'behind_of', return_value=None), \
         mock.patch.object(ccd.os.path, 'isdir', return_value=True), mock.patch.object(ccd.time, 'sleep'), \
         mock.patch.object(ccd.os, 'chdir') as cd:
        if dry:
            with mock.patch.object(ccd.os.environ, 'pop'), mock.patch.dict(os.environ, {'CCD_DRY_RUN': '1'}):
                call, code, err = run(['--carry'] + argv, accts, menu=menu)
        else:
            call, code, err = run(['--carry'] + argv, accts, menu=menu)
    return call, code, err, cd


def words(call):
    return call.args[1][1:]  # what claude is started with, after its own name


class CarryOn(unittest.TestCase):
    def test_reopens_the_chosen_chat_on_the_account_with_room(self):
        menu = FakeMenu(chat=lambda chs: chs[1])
        call, code, err, cd = carry([], [a_chat('chat-1'), a_chat('chat-2', cwd='/work/film')], menu)
        self.assertEqual(words(call)[:3], ['--dangerously-skip-permissions', '--resume', 'chat-2'])
        self.assertEqual(picked(call), 'ultra')
        self.assertEqual(call.args[2]['CLAUDE_CODE_OAUTH_TOKEN'], 'tok-ultra')
        cd.assert_called_once_with('/work/film')
        self.assertEqual(menu.closed, 1)

    def test_a_chat_that_stopped_at_its_limit_is_told_to_carry_on(self):
        call, *_ = carry([], [a_chat(limited=True)], FakeMenu(chat=lambda chs: chs[0]))
        self.assertEqual(words(call)[3:], [ccd.NUDGE])
        self.assertNotIn('--fork-session', words(call))

    def test_a_chat_that_was_not_stopped_just_reopens_and_waits_for_him(self):
        call, *_ = carry([], [a_chat(limited=False)], FakeMenu(chat=lambda chs: chs[0]))
        self.assertEqual(words(call), ['--dangerously-skip-permissions', '--resume', 'chat-1'])

    def test_esc_on_the_list_starts_nothing(self):
        call, code, err, cd = carry([], [a_chat()], FakeMenu(chat=lambda chs: None))
        self.assertEqual((call, code), (None, 130))
        cd.assert_not_called()

    def test_no_recent_chats_says_so_and_starts_nothing(self):
        call, code, err, _ = carry([], [], FakeMenu(chat=lambda chs: self.fail('no list to show')))
        self.assertIsNone(call)
        self.assertIn('no chat', str(code))

    def test_open_in_another_window_waits_until_he_closes_it(self):
        live = {'pid': 4242, 'name': 'sam-dc', 'status': 'shell'}
        menu = FakeMenu(chat=lambda chs: chs[0], how='same')
        call, *_ = carry([], [a_chat(live=live)], menu)
        self.assertEqual(menu.waited['id'], 'chat-1')
        self.assertEqual(words(call)[:3], ['--dangerously-skip-permissions', '--resume', 'chat-1'])
        self.assertNotIn('--fork-session', words(call))

    def test_open_in_another_window_and_he_asks_for_a_copy(self):
        menu = FakeMenu(chat=lambda chs: chs[0], how='copy')
        call, *_ = carry([], [a_chat(live={'pid': 4242, 'name': 'sam-dc', 'status': 'idle'})], menu)
        self.assertEqual(words(call)[:4], ['--dangerously-skip-permissions', '--resume', 'chat-1', '--fork-session'])
        self.assertEqual(words(call)[4:], [ccd.NUDGE_COPY])
        self.assertIn('still open', ccd.NUDGE_COPY)
        self.assertNotIn('has ended', ccd.NUDGE_COPY)

    def test_open_in_another_window_and_he_backs_out(self):
        menu = FakeMenu(chat=lambda chs: chs[0], how=None)
        call, code, *_ = carry([], [a_chat(live={'pid': 4242, 'name': 'sam-dc', 'status': 'idle'})], menu)
        self.assertEqual((call, code), (None, 130))
        self.assertEqual(menu.closed, 2)  # the list, then the wait screen

    def test_a_closed_chat_never_shows_the_wait_screen(self):
        menu = FakeMenu(chat=lambda chs: chs[0], how='copy')
        call, *_ = carry([], [a_chat(live=None)], menu)
        self.assertIsNone(menu.waited)
        self.assertNotIn('--fork-session', words(call))

    def test_every_account_full_starts_nothing_and_says_when_one_is_back(self):
        full = [dict(acct('team', 100, five=1.0, blocked=True), five_reset=time.time() + 5400, week_reset=0),
                dict(acct('ultra', 200, week=1.0, blocked=True), five_reset=0, week_reset=time.time() + 90000)]
        call, code, err, _ = carry([], [a_chat()], FakeMenu(chat=lambda chs: chs[0]), accts=full)
        self.assertEqual((call, code), (None, 1))
        self.assertIn('every account is at its limit', err)
        self.assertRegex(err, r'team: resets in 1h (29|30)m')

    def test_no_account_answering_starts_nothing(self):
        dead = [acct('team', 100, reachable=False), acct('ultra', 200, reachable=False)]
        call, code, err, _ = carry([], [a_chat()], FakeMenu(chat=lambda chs: chs[0]), accts=dead)
        self.assertIsNone(call)
        self.assertIn('could not reach any account', str(code))

    def test_an_id_skips_the_list(self):
        menu = FakeMenu(chat=lambda chs: self.fail('the list should not show'))
        call, *_ = carry(['chat-2'], [a_chat('chat-1'), a_chat('chat-2')], menu)
        self.assertEqual(words(call)[1:3], ['--resume', 'chat-2'])

    def test_an_id_that_matches_no_chat_starts_nothing_even_if_one_is_close(self):
        call, code, err, _ = carry(['chat-'], [a_chat('chat-1')], FakeMenu(chat=lambda chs: chs[0]))
        self.assertIsNone(call)
        self.assertIn('no chat with the id chat-', str(code))

    def test_plan_number_still_works_with_it(self):
        accts = [acct('team', 100, five=0.1), acct('ultra', 200, five=0.6)]
        call, *_ = carry(['200'], [a_chat()], FakeMenu(chat=lambda chs: chs[0]), accts=accts)
        self.assertEqual(picked(call), 'ultra')

    def test_no_terminal_to_ask_in_starts_nothing_without_an_id(self):
        call, code, err, _ = carry([], [a_chat()], menu=OSError)
        self.assertIsNone(call)
        self.assertIn('no terminal', str(code))

    def test_no_terminal_is_fine_when_the_id_is_given_and_the_chat_is_closed(self):
        call, *_ = carry(['chat-1'], [a_chat()], menu=OSError)
        self.assertEqual(words(call)[1:3], ['--resume', 'chat-1'])

    def test_dry_run_starts_nothing_and_says_what_it_would_do(self):
        call, code, err, _ = carry([], [a_chat()], FakeMenu(chat=lambda chs: chs[0]), dry=True)
        self.assertIsNone(call)
        self.assertIn('--resume chat-1', err)
        self.assertNotIn('tok-', err)

    def test_plain_ccd_still_hands_resume_words_straight_to_claude(self):
        call, _, _ = run(['-r', 'abc'], [acct('ultra', 200, five=0.2)])
        self.assertEqual(words(call), ['--dangerously-skip-permissions', '-r', 'abc'])

    def test_choosing_the_account_by_hand_works_with_it_too(self):
        accts = [acct('team', 100, five=0.1), acct('ultra', 200, five=0.6)]
        menu = FakeMenu(choice=lambda rws: next(r for r in rws if r['key'] == 'ultra'), chat=lambda chs: chs[0])
        with mock.patch.object(ccd, 'chats', return_value=[a_chat()]), mock.patch.object(ccd.os, 'chdir'), \
             mock.patch.object(ccd.os.path, 'isdir', return_value=True):
            call, _, _ = run(['--pick', '--carry'], accts, menu=menu)
        self.assertEqual(picked(call), 'ultra')
        self.assertEqual(words(call)[1:3], ['--resume', 'chat-1'])


class WaitScreen(unittest.TestCase):
    def test_c_asks_for_a_copy(self):
        self.assertEqual(ccd.waiting('c', True), 'copy')

    def test_esc_or_q_backs_out(self):
        self.assertEqual((ccd.waiting('esc', True), ccd.waiting('q', True)), ('quit', 'quit'))

    def test_keeps_waiting_while_the_other_window_is_open(self):
        self.assertIsNone(ccd.waiting(None, True))
        self.assertIsNone(ccd.waiting('x', True))

    def test_goes_ahead_once_the_other_window_has_closed(self):
        self.assertEqual(ccd.waiting(None, False), 'same')

    def test_says_a_running_command_would_be_stopped(self):
        text = '\n'.join(''.join(t for t, _ in line) for line in
                         ccd.wait_frame(a_chat(live={'pid': 1, 'name': 'sam-dc', 'status': 'shell'})))
        self.assertIn('sam-dc', text)
        self.assertIn('still running', text)
        idle = '\n'.join(''.join(t for t, _ in line) for line in
                         ccd.wait_frame(a_chat(live={'pid': 1, 'name': 'sam-dc', 'status': 'idle'})))
        self.assertNotIn('still running', idle)


class ChatScreen(unittest.TestCase):
    def text(self, chs, at=0, cols=110, lines=40):
        return [''.join(t for t, _ in line) for line in ccd.chat_frame(chs, at, cols, lines, time.time())]

    def test_a_chat_stopped_by_a_switched_off_account_says_so_not_limit(self):
        out = '\n'.join(self.text([dict(a_chat('a', True), why='off')]))
        self.assertIn('stopped: account switched off', out)
        self.assertNotIn('its limit', out)

    def test_the_wait_screen_promises_no_restart_for_a_switched_off_account(self):
        live = {'pid': 1, 'name': 'sam-dc', 'status': 'idle'}
        text = lambda c: ' '.join(' '.join(''.join(t for t, _ in line) for line in ccd.wait_frame(c, 80)).split())
        self.assertIn('when its limit resets', text(a_chat(live=live)))
        self.assertNotIn('when its limit resets', text(dict(a_chat(live=live), why='off')))

    def test_shows_which_chats_stopped_and_which_are_open(self):
        out = '\n'.join(self.text([a_chat('a', True), a_chat('b', False, live={'pid': 1, 'name': 'n', 'status': 'idle'},
                                                              title='Events page')]))
        self.assertIn('Sound and music', out)
        self.assertRegex(out, r'stopped at its limit · 5 min ago')
        self.assertIn('open in another window', out)
        self.assertIn('❯ 1', out)

    def test_never_lists_more_than_nine_or_than_fit(self):
        many = [a_chat('c%d' % i, title='Chat %d' % i) for i in range(20)]
        self.assertEqual(ccd.shown(many, 60), 9)
        self.assertEqual(ccd.shown(many, 14), 3)
        self.assertEqual(ccd.shown(many, 4), 1)
        self.assertEqual(ccd.shown(many[:2], 60), 2)
        self.assertEqual(sum('Chat ' in l for l in self.text(many, lines=14)), 3)

    def test_a_long_name_is_cut_so_the_note_still_fits(self):
        long = a_chat(title='A very long chat name that goes on and on and on about nothing at all ' * 3)
        first = next(l for l in self.text([long], cols=80) if '❯' in l)
        self.assertLessEqual(len(first), 79)
        self.assertIn('stopped at its limit', first)

    def test_his_words_are_not_shown_twice_when_they_are_also_the_name(self):
        c = dict(a_chat(title='fix the events header'), said='fix the events header')
        self.assertEqual(sum('fix the events header' in l for l in self.text([c])), 1)

    def test_a_long_folder_is_cut_from_the_left_so_his_words_keep_their_room(self):
        c = a_chat(cwd='/private/tmp/claude-501/-Users-sam/9a9fe8fd-1ec0-4eb7-a32a-235f7887f981/scratchpad/e2e-work')
        second = self.text([c], cols=110)[4]
        self.assertIn('“render it”', second)
        self.assertIn('…', second)
        self.assertTrue(second.rstrip().endswith('scratchpad/e2e-work'))
        self.assertLessEqual(len(second), 109)

    def test_a_long_name_on_the_wait_screen_keeps_its_closing_quote(self):
        c = a_chat(title='What was the secret word I gave you before the limit? One word. ' * 2,
                   live={'pid': 1, 'name': 'n', 'status': 'idle'})
        first = ''.join(t for t, _ in ccd.wait_frame(c)[1])
        self.assertRegex(first, r'“[^”]*…” is still open in another window')

    def test_ages_read_like_a_person_would_say_them(self):
        self.assertEqual([ccd.ago(s) for s in (20, 26 * 60, 3 * 3600 + 5, 30 * 3600, 80 * 3600)],
                         ['just now', '26 min ago', '3 h ago', 'yesterday', '3 days ago'])

    def test_number_keys_only_reach_rows_on_screen(self):
        self.assertEqual(ccd.press_chat(3, 0, '2'), (1, 'go'))
        self.assertEqual(ccd.press_chat(3, 0, '7'), (0, None))
        self.assertEqual(ccd.press_chat(3, 2, 'down'), (0, None))
        self.assertEqual(ccd.press_chat(3, 1, 'enter'), (1, 'go'))
        self.assertEqual(ccd.press_chat(3, 1, 'esc'), (1, 'quit'))


class ReviewFixes(Disk):
    """One fresh review, 20 Nov 2026: each of these was a real hole."""

    def test_a_stop_on_one_models_limit_is_a_limit_too(self):
        fable = dict(limit_hit(), apiError='model_requires_usage_credits')
        fable['message'] = dict(fable['message'], content=[{'type': 'text', 'text':
                                "You've reached your Fable limit. Run /usage-credits to continue or switch models with /model."}])
        self.chat('aaa', [he_said('make the page'), fable])
        self.assertTrue(self.found()['aaa']['limited'])

    def test_a_model_limit_is_known_by_its_mark_even_if_the_wording_changes(self):
        fable = dict(limit_hit(), apiError='model_requires_usage_credits')
        fable['message'] = dict(fable['message'], content=[{'type': 'text', 'text': 'Fable is out of room for now.'}])
        self.chat('aaa', [he_said('make the page'), fable])
        self.assertTrue(self.found()['aaa']['limited'])

    def test_a_limit_is_known_by_its_wording_even_if_the_mark_is_new(self):
        new_kind = dict(limit_hit(), apiError='some_new_limit_kind')
        self.chat('aaa', [he_said('make the page'), new_kind])
        self.assertTrue(self.found()['aaa']['limited'])

    def test_an_id_must_match_letter_for_letter(self):
        self.chat('abc-def', [he_said('make the page'), it_said('ok')])
        self.assertIsNotNone(ccd.find_chat('abc-def'))
        self.assertIsNone(ccd.find_chat('ABC-DEF'))  # this Mac's disk would happily open the file for either

    def test_chats_in_skipped_folders_are_not_listed_but_an_id_still_reaches_them(self):
        self.chat('bridge', [he_said('incoming message'), it_said('ok')], folder='-Users-someone-Projects-chat-bot-home')
        self.chat('his', [he_said('make the page'), it_said('ok')])
        with mock.patch.object(ccd, 'SKIP', ('chat-bot',)):
            self.assertEqual(list(self.found()), ['his'])
        self.assertEqual(sorted(self.found()), ['bridge', 'his'])  # nothing skipped unless the settings say so
        self.assertEqual(ccd.find_chat('bridge')['id'], 'bridge')

    def test_a_window_is_matched_by_its_real_start_time(self):
        started = ccd.subprocess.run(['/bin/ps', '-p', str(os.getpid()), '-o', 'lstart='], capture_output=True, text=True,
                                     env={'TZ': 'UTC', 'LC_ALL': 'C'}).stdout.strip()
        self.assertTrue(ccd.running(os.getpid(), started))  # window files record the start in UTC
        self.assertFalse(ccd.running(os.getpid(), 'Mon Jan  5 01:02:03 2015'))
        self.chat('aaa', [he_said('make the page'), limit_hit()])
        self.window('aaa', os.getpid(), procStart=started)
        self.assertEqual(self.found()['aaa']['open']['started'], started)

    def test_a_window_file_caught_half_written_is_read_again(self):
        self.chat('aaa', [he_said('make the page'), limit_hit()])
        self.window('aaa', os.getpid())
        real, calls = json.load, []

        def flaky(f):
            calls.append(1)
            if len(calls) == 1:
                raise ValueError('half written')
            return real(f)
        with mock.patch.object(ccd.json, 'load', side_effect=flaky), mock.patch.object(ccd.time, 'sleep'):
            self.assertIn('aaa', ccd.open_chats())


class ReviewFixesFlow(unittest.TestCase):
    LIVE = {'pid': 4242, 'name': 'sam-dc', 'status': 'shell', 'started': 'Fri Nov 20 09:48:34 2026'}

    def test_full_accounts_are_found_out_before_he_is_asked_to_close_a_window(self):
        full = [dict(acct('team', 100, five=1.0, blocked=True), five_reset=time.time() + 5400, week_reset=0)]
        menu = FakeMenu(chat=lambda chs: chs[0], how='same')
        call, code, err, _ = carry([], [a_chat(live=self.LIVE)], menu, accts=full)
        self.assertEqual((call, code), (None, 1))
        self.assertIsNone(menu.waited)  # never told to close a window for nothing
        self.assertIn('every account is at its limit', err)

    def test_the_wait_watches_the_other_windows_process_not_its_file(self):
        menu = FakeMenu(chat=lambda chs: chs[0], how='same')
        found = [a_chat(live=self.LIVE)]
        with mock.patch.object(ccd, 'chats', return_value=found), mock.patch.object(ccd, 'open_chats', return_value={'chat-1': self.LIVE}), \
             mock.patch.object(ccd, 'behind_of', return_value=None), mock.patch.object(ccd, 'account_of', return_value=None), mock.patch.object(ccd.time, 'sleep'), \
             mock.patch.object(ccd.os.path, 'isdir', return_value=True), mock.patch.object(ccd.os, 'chdir'), \
             mock.patch.object(ccd, 'running', return_value=True) as alive:
            run(['--carry'], [acct('ultra', 200, five=0.2)], menu=menu)
        self.assertTrue(menu.was_open)
        alive.assert_called_with(4242, 'Fri Nov 20 09:48:34 2026')

    def test_a_chat_opened_elsewhere_while_the_list_was_up_still_gets_the_wait_screen(self):
        menu = FakeMenu(chat=lambda chs: chs[0], how=None)
        found = [a_chat(live=None)]  # closed when the list was drawn
        with mock.patch.object(ccd, 'chats', return_value=found), mock.patch.object(ccd, 'open_chats', return_value={'chat-1': self.LIVE}), \
             mock.patch.object(ccd, 'behind_of', return_value=None), mock.patch.object(ccd, 'account_of', return_value=None), mock.patch.object(ccd, 'running', return_value=True), \
             mock.patch.object(ccd.os, 'chdir'):
            call, code, _ = run(['--carry'], [acct('ultra', 200, five=0.2)], menu=menu)
        self.assertEqual((call, code, menu.waited['id']), (None, 130, 'chat-1'))

    def test_a_chat_opened_elsewhere_while_the_accounts_were_checked_still_gets_the_wait_screen(self):
        menu = FakeMenu(chat=lambda chs: chs[0], how=None)
        looks = iter([{}, {'chat-1': self.LIVE}])  # closed when he picked it, open by the time an account was found
        with mock.patch.object(ccd, 'chats', return_value=[a_chat(live=None)]), \
             mock.patch.object(ccd, 'open_chats', side_effect=lambda: next(looks)), \
             mock.patch.object(ccd, 'behind_of', return_value=None), mock.patch.object(ccd, 'account_of', return_value=None), mock.patch.object(ccd, 'running', return_value=True), \
             mock.patch.object(ccd.os, 'chdir'):
            call, code, _ = run(['--carry'], [acct('ultra', 200, five=0.2)], menu=menu)
        self.assertEqual((call, code, menu.waited['id']), (None, 130, 'chat-1'))

    def test_a_chat_that_ccd_is_moving_by_itself_still_counts_as_open(self):
        # he runs ccdr seconds after the limit; the automatic move then closes that claude and opens a new one in the
        # same window. "Its process ended" must not be read as "he closed the window".
        menu = FakeMenu(chat=lambda chs: chs[0], how=None)
        with mock.patch.object(ccd, 'chats', return_value=[a_chat(live=self.LIVE)]), \
             mock.patch.object(ccd, 'open_chats', return_value={'chat-1': self.LIVE}), \
             mock.patch.object(ccd, 'account_of', return_value=None), mock.patch.object(ccd, 'behind_of', return_value=777), \
             mock.patch.object(ccd, 'running', side_effect=lambda pid, started=None: pid == 777), \
             mock.patch.object(ccd.os, 'chdir'):
            run(['--carry'], [acct('ultra', 200, five=0.2)], menu=menu)
        self.assertTrue(menu.was_open)

    def test_ctrl_c_on_the_list_starts_nothing_and_puts_the_terminal_back(self):
        def ctrl_c(chs):
            raise KeyboardInterrupt
        menu = FakeMenu(chat=ctrl_c)
        call, code, *_ = carry([], [a_chat()], menu)
        self.assertEqual((call, code, menu.closed), (None, 130, 1))

    def test_ctrl_c_on_the_wait_screen_starts_nothing(self):
        menu = FakeMenu(chat=lambda chs: chs[0])
        menu.wait = mock.Mock(side_effect=KeyboardInterrupt)
        call, code, *_ = carry([], [a_chat(live=self.LIVE)], menu)
        self.assertEqual((call, code, menu.closed), (None, 130, 2))

    def test_a_plan_number_after_the_id_is_a_plan_not_a_message(self):
        accts = [acct('team', 100, five=0.1), acct('ultra', 200, five=0.6)]
        call, *_ = carry(['chat-1', '200'], [a_chat()], accts=accts)
        self.assertEqual(picked(call), 'ultra')
        self.assertNotIn('200', words(call))

    def test_his_own_words_after_the_id_replace_the_carry_on_note(self):
        call, *_ = carry(['chat-1', 'just summarise where we are'], [a_chat(limited=True)])
        self.assertEqual(words(call), ['--dangerously-skip-permissions', '--resume', 'chat-1', 'just summarise where we are'])

    def test_the_two_words_work_in_either_order(self):
        accts = [acct('team', 100, five=0.1), acct('ultra', 200, five=0.6)]
        menu = FakeMenu(choice=lambda rws: next(r for r in rws if r['key'] == 'ultra'), chat=lambda chs: chs[0])
        with mock.patch.object(ccd, 'chats', return_value=[a_chat()]), mock.patch.object(ccd, 'open_chats', return_value={}), \
             mock.patch.object(ccd.os, 'chdir'), mock.patch.object(ccd.os.path, 'isdir', return_value=True):
            call, _, _ = run(['--carry', '--pick'], accts, menu=menu)
        self.assertEqual((picked(call), words(call)[1:3]), ('ultra', ['--resume', 'chat-1']))

    def test_a_limit_stopped_chat_does_not_reopen_on_the_account_it_stopped_on(self):
        # a limit on one model does not show in the overall figures: the team account looks the emptiest
        accts = [acct('team', 100, five=0.05), acct('ultra', 200, five=0.6)]
        menu = FakeMenu(chat=lambda chs: chs[0], how='same')
        call, *_ = carry([], [a_chat(limited=True, live=self.LIVE)], menu, accts=accts, live_account={4242: 'team'})
        self.assertEqual(picked(call), 'ultra')

    def test_but_it_does_when_that_is_the_only_account_with_room(self):
        accts = [acct('team', 100, five=0.05), acct('ultra', 200, five=1.0, blocked=True)]
        menu = FakeMenu(chat=lambda chs: chs[0], how='same')
        call, *_ = carry([], [a_chat(limited=True, live=self.LIVE)], menu, accts=accts, live_account={4242: 'team'})
        self.assertEqual(picked(call), 'team')

    def test_a_chat_that_did_not_stop_at_a_limit_may_stay_on_its_account(self):
        accts = [acct('team', 100, five=0.05), acct('ultra', 200, five=0.6)]
        menu = FakeMenu(chat=lambda chs: chs[0], how='same')
        call, *_ = carry([], [a_chat(limited=False, live=self.LIVE)], menu, accts=accts, live_account={4242: 'team'})
        self.assertEqual(picked(call), 'team')

    def test_dry_run_does_not_sit_waiting_for_a_window(self):
        menu = FakeMenu(chat=lambda chs: chs[0], how='same')
        call, code, err, _ = carry([], [a_chat(live=self.LIVE)], menu, dry=True)
        self.assertIsNone(menu.waited)
        self.assertIn('open in another window', err)


class RealScreens(unittest.TestCase):
    """The two ccdr screens' own loops, with the keyboard and the drawing stood in for."""

    def menu(self, keys):
        m = object.__new__(ccd.Menu)
        m.fd, m.frames = 0, []
        feed = iter(keys)
        m.key = lambda timeout=None: next(feed)
        m.show = m.frames.append
        return m

    def run_it(self, fn, lines=40):
        size = os.terminal_size((100, lines))
        with mock.patch.object(ccd.termios, 'tcflush'), mock.patch.object(ccd.os, 'get_terminal_size', return_value=size):
            return fn()

    def test_wait_holds_while_the_other_window_lives_then_goes_ahead(self):
        looks = iter([True, True, False])
        m = self.menu([None, 'x', None])
        self.assertEqual(self.run_it(lambda: m.wait(a_chat(live={'pid': 1, 'name': 'n', 'status': 'idle'}), lambda: next(looks))), 'same')
        self.assertEqual(len(m.frames), 3)

    def test_wait_gives_a_copy_on_c_and_nothing_on_esc(self):
        chat = a_chat(live={'pid': 1, 'name': 'n', 'status': 'idle'})
        self.assertEqual(self.run_it(lambda: self.menu(['c']).wait(chat, lambda: True)), 'copy')
        self.assertIsNone(self.run_it(lambda: self.menu(['esc']).wait(chat, lambda: True)))

    def test_list_moves_down_and_picks_with_enter(self):
        chs = [a_chat('c%d' % i, title='Chat %d' % i) for i in range(4)]
        self.assertEqual(self.run_it(lambda: self.menu(['down', 'down', 'enter']).choose_chat(chs))['id'], 'c2')
        self.assertIsNone(self.run_it(lambda: self.menu(['down', 'esc']).choose_chat(chs)))

    def test_list_scrolls_to_chats_below_the_fold(self):
        chs = [a_chat('c%d' % i, title='Chat %d' % i) for i in range(12)]
        m = self.menu(['down'] * 5 + ['enter'])
        self.assertEqual(self.run_it(lambda: m.choose_chat(chs), lines=14)['id'], 'c5')  # three rows fit
        last = '\n'.join(''.join(t for t, _ in line) for line in m.frames[-1])
        self.assertIn('Chat 5', last)
        self.assertNotIn('Chat 0', last)

    def test_a_number_means_the_row_on_screen_after_scrolling(self):
        chs = [a_chat('c%d' % i, title='Chat %d' % i) for i in range(12)]
        m = self.menu(['down'] * 5 + ['1'])
        self.assertEqual(self.run_it(lambda: m.choose_chat(chs), lines=14)['id'], 'c3')  # rows on screen: c3 c4 c5

    def test_the_list_says_when_there_are_more_than_fit(self):
        chs = [a_chat('c%d' % i, title='Chat %d' % i) for i in range(12)]
        out = '\n'.join(''.join(t for t, _ in line) for line in ccd.chat_frame(chs, 0, 100, 14, time.time()))
        self.assertIn('9 more', out)
        few = '\n'.join(''.join(t for t, _ in line) for line in ccd.chat_frame(chs[:2], 0, 100, 40, time.time()))
        self.assertNotIn('more', few)

    def test_the_wait_screen_fits_a_narrow_window_with_every_word(self):
        chat = a_chat(limited=True, live={'pid': 1, 'name': 'sam-dc', 'status': 'shell'},
                      title='Video skill sound and music learnings and a good deal more besides')
        lines = [''.join(t for t, _ in line) for line in ccd.wait_frame(chat, 80)]
        self.assertLessEqual(max(map(len, lines)), 79)
        text = ' '.join(' '.join(lines).split())
        self.assertIn('press Esc in that window', text)
        self.assertIn('is still open in another window (sam-dc)', text)


# ---- the automatic move: ccd stays behind the chat and carries it over when it hits a limit ------------
PS = """
  100     1  12.0
  200   100   1.5
  201   100  80.0
  300   200   0.5
  400     1  99.0
  401   400  50.0
"""


class Processor(unittest.TestCase):
    def test_adds_up_everything_the_chat_started_and_nothing_else(self):
        self.assertAlmostEqual(ccd.tree_load(PS, 100), 1.5 + 80.0 + 0.5)  # not the chat itself, not the other chat's
        self.assertEqual(ccd.tree_load(PS, 999), 0.0)
        self.assertEqual(ccd.tree_load('rubbish\n\n  7 x 1.0\n', 100), 0.0)

    def test_reads_the_real_process_table(self):
        self.assertRegex(ccd.ps_table(), r'(?m)^\s*%d\s+\d+\s+\d+[.,]\d' % os.getpid())


class Clock:
    """Stands in for time passing beside a chat: each look of the watcher moves it on by one step."""
    def __init__(self, looks):
        self.now, self.left = 1_000_000.0, looks

    def wait(self, secs):
        self.now += secs
        self.left -= 1
        return self.left < 0  # True = the chat's window has gone, stop watching


class Watching(unittest.TestCase):
    ULTRA = {'key': 'ultra', 'label': 'Ultra', 'token': 'tok-ultra', 'five': 0.2, 'week': 0.3, 'blocked': False}

    def rig(self, looks=40, limited=True, stopped_at=1, status='idle', room=None, cpu=None, chat_after=None,
            stopped_on=None, sid='chat-1', table='', kill=None, why=None):
        """Run the watcher beside a pretend chat. `status`, `cpu` (percent of a processor in use now) and `room` may be
        functions of the number of looks so far; `stopped_at` = seconds after the window opened that the chat hit
        its limit. Returns (the move it asked for, signals sent, account checks)."""
        clock = Clock(looks)
        count = self.count = {'looks': 0, 'room': 0, 'reads': 0, 'avoid': [], 'paths': []}
        val = lambda v: v(count['looks']) if callable(v) else v

        def window(pid):
            count['looks'] += 1
            return {'sessionId': val(sid), 'status': val(status)}

        def read(path, any_kind=False, tail=None):
            count['reads'] += 1
            count['paths'].append(path)
            if callable(limited) and limited.__code__.co_argcount == 2:
                lim = limited(count['looks'], path)  # depends on WHICH chat is read
            else:
                lim = val(limited) if chat_after is None or count['room'] == 0 else chat_after
            return {'id': 'x', 'limited': lim, 'why': why if lim else None, 'when': 1_000_000.0 + stopped_at}

        def find_room(account, want=None, avoid=()):
            count['room'] += 1
            count['avoid'].append(set(avoid))
            return val(room) if room is not None else self.ULTRA

        def send(pid, sig):
            if kill:
                raise kill
            sent.append((pid, sig))
        move, sent = {}, []
        with mock.patch.object(ccd, 'window_of', side_effect=window), mock.patch.object(ccd, 'read_chat', side_effect=read), \
             mock.patch.object(ccd, 'chat_path', side_effect=lambda s: '/x/%s.jsonl' % s), \
             mock.patch.object(ccd, 'chat_stamp', side_effect=lambda p: count['looks']), \
             mock.patch.object(ccd, 'running', return_value=True), \
             mock.patch.object(ccd, 'ps_table', return_value=table), \
             mock.patch.object(ccd, 'tree_load', side_effect=lambda text, pid: val(cpu) if cpu is not None else 0.0), \
             mock.patch.object(ccd, 'room_elsewhere', side_effect=find_room), \
             mock.patch.object(ccd.time, 'time', side_effect=lambda: clock.now), \
             mock.patch.object(ccd.os, 'kill', side_effect=send):
            ccd.watch(4242, 'team', None, move, clock, stopped_on)
        return move, sent, count

    def test_a_chat_that_is_working_fine_is_left_alone(self):
        move, sent, count = self.rig(limited=False)
        self.assertEqual((move, sent, count['room']), ({}, [], 0))

    def test_a_chat_stopped_at_its_limit_is_closed_and_handed_to_an_account_with_room(self):
        move, sent, _ = self.rig()
        self.assertEqual((move['id'], move['to']['key'], move['old']), ('chat-1', 'ultra', 'team'))
        self.assertEqual(sent, [(4242, signal.SIGTERM)])

    def test_a_chat_stopped_by_a_switched_off_account_is_moved_too_and_says_why(self):
        move, sent, _ = self.rig(why='off')
        self.assertEqual((move['id'], move['to']['key'], move['why']), ('chat-1', 'ultra', 'off'))
        self.assertEqual(sent, [(4242, signal.SIGTERM)])

    def test_it_waits_a_moment_after_the_limit_so_he_can_read_the_message(self):
        looks_in_grace = int(ccd.GRACE / ccd.WATCH_EVERY) - 1
        move, sent, count = self.rig(looks=looks_in_grace, stopped_at=0)
        self.assertEqual((move, sent, count['room']), ({}, [], 0))
        move, sent, _ = self.rig(looks=looks_in_grace + 6, stopped_at=0)
        self.assertEqual(sent, [(4242, signal.SIGTERM)])

    def test_a_limit_from_before_this_window_opened_is_history(self):
        # a chat just reopened on a new account still ENDS with the old limit message until its first answer lands:
        # acting on that would bounce it straight on to the next account
        move, sent, count = self.rig(looks=200, stopped_at=-30)
        self.assertEqual((move, sent, count['room']), ({}, [], 0))

    def test_an_account_this_chat_stopped_on_is_avoided_for_an_hour_and_no_longer(self):
        # two accounts on his plan: A filled, the chat moved to B; hours later B fills and A is empty again
        was = {'alex': 1_000_000.0 - (ccd.AVOID - 200)}  # it stopped on alex 56 minutes before this window opened
        move, sent, count = self.rig(looks=int(2.5 * ccd.RETRY / ccd.WATCH_EVERY), room=lambda n: None, stopped_on=was)
        self.assertEqual(count['avoid'][0], {'alex'})
        self.assertEqual(count['avoid'][-1], set())  # the hour has passed: alex may be used again

    def test_a_limit_that_arrives_later_is_seen(self):
        move, sent, count = self.rig(looks=60, limited=lambda n: n > 12, stopped_at=13 * ccd.WATCH_EVERY)
        self.assertEqual(sent, [(4242, signal.SIGTERM)])
        self.assertGreater(count['reads'], 12)  # the chat is read again whenever its file changes

    def test_the_chat_showing_in_the_window_now_is_the_one_that_moves(self):
        # /clear or /resume inside the window: it shows another chat than the one it opened with
        move, sent, count = self.rig(looks=60, sid=lambda n: 'chat-1' if n <= 5 else 'chat-2', limited=lambda n: n > 5,
                                     stopped_at=6 * ccd.WATCH_EVERY)
        self.assertEqual(move['id'], 'chat-2')
        self.assertIn('/x/chat-2.jsonl', count['paths'])

    def test_a_chat_that_started_working_while_the_accounts_were_checked_is_not_closed(self):
        move, sent, count = self.rig(status=lambda n: 'busy' if self.count['room'] else 'idle')
        self.assertEqual((move, sent), ({}, []))
        self.assertGreaterEqual(count['room'], 1)

    def test_a_window_that_switched_chats_while_the_accounts_were_checked_is_not_closed(self):
        # the chat he switched to is not at a limit; the one that was is no longer in this window
        move, sent, count = self.rig(sid=lambda n: 'chat-2' if self.count['room'] else 'chat-1',
                                     limited=lambda n, path: path.endswith('chat-1.jsonl'))
        self.assertEqual((move, sent), ({}, []))
        self.assertEqual(count['room'], 1)

    def test_a_chat_that_had_just_gone_by_itself_is_not_reopened(self):
        move, sent, _ = self.rig(kill=ProcessLookupError())  # he quit it in the same second
        self.assertEqual(move, {})

    def test_a_process_table_that_cannot_be_read_counts_as_working(self):
        move, sent, count = self.rig(status='shell', table=None)
        self.assertEqual((move, sent, count['room']), ({}, [], 0))

    def test_a_chat_that_is_still_working_is_not_touched(self):
        move, sent, count = self.rig(status='busy')
        self.assertEqual((move, sent, count['room']), ({}, [], 0))

    def test_a_background_command_that_is_using_the_processor_is_left_to_finish(self):
        move, sent, count = self.rig(status='shell', cpu=90.0)  # a render: most of a processor
        self.assertEqual((move, sent, count['room']), ({}, [], 0))

    def test_the_move_happens_once_that_command_goes_quiet(self):
        move, sent, count = self.rig(looks=60, status='shell', cpu=lambda n: 90.0 if n <= 20 else 0.2)  # busy for 20 looks
        self.assertEqual(sent, [(4242, signal.SIGTERM)])
        self.assertGreaterEqual(count['looks'], 20 + int(ccd.CPU_WINDOW / ccd.WATCH_EVERY))  # and quiet for a while, not a blink

    def test_a_gap_between_two_jobs_of_a_batch_is_not_mistaken_for_the_end(self):
        gaps = lambda n: 0.2 if n % 4 == 0 else 90.0  # one quiet look between clips, again and again
        move, sent, count = self.rig(looks=80, status='shell', cpu=gaps)
        self.assertEqual((move, sent, count['room']), ({}, [], 0))

    def test_a_background_command_that_is_only_sitting_there_does_not_hold_the_move_up(self):
        move, sent, _ = self.rig(status='shell', cpu=0.3)  # a preview server, a waiting loop
        self.assertEqual(sent, [(4242, signal.SIGTERM)])

    def test_with_no_account_free_the_chat_is_left_exactly_as_it_is(self):
        move, sent, count = self.rig(looks=int(ccd.RETRY / ccd.WATCH_EVERY) - 10, room=lambda n: None)
        self.assertEqual((move, sent), ({}, []))
        self.assertEqual(count['room'], 1)  # and the accounts are not pestered: one check, then a long pause

    def test_it_looks_again_later_and_moves_when_an_account_frees_up(self):
        answers = iter([None, self.ULTRA])
        move, sent, count = self.rig(looks=int(ccd.RETRY / ccd.WATCH_EVERY) + 20, room=lambda n: next(answers))
        self.assertEqual((count['room'], sent), (2, [(4242, signal.SIGTERM)]))

    def test_a_chat_that_carried_on_by_itself_while_the_accounts_were_checked_is_not_closed(self):
        move, sent, count = self.rig(chat_after=False)
        self.assertEqual((move, sent), ({}, []))
        self.assertGreaterEqual(count['room'], 1)

    def test_watching_ends_when_the_window_goes(self):
        clock = Clock(1000)
        with mock.patch.object(ccd, 'running', return_value=False), mock.patch.object(ccd, 'window_of') as window:
            ccd.watch(4242, 'team', None, {}, clock)
        window.assert_not_called()
        self.assertGreater(clock.left, 990)

    def test_a_fault_while_watching_never_takes_the_chat_down(self):
        clock = Clock(5)
        with mock.patch.object(ccd, 'running', return_value=True), mock.patch.object(ccd, 'window_of', side_effect=RuntimeError('boom')), \
             mock.patch.object(ccd.os, 'kill') as kill:
            ccd.watch(4242, 'team', None, {}, clock)  # must not raise
        kill.assert_not_called()


class RoomElsewhere(unittest.TestCase):
    def find(self, accts, account, want=None, avoid=()):
        with mock.patch.object(ccd, 'accounts', return_value=accts), mock.patch.object(ccd, 'ping', side_effect=lambda a: a):
            return ccd.room_elsewhere(account, want, avoid)

    def test_never_back_to_an_account_this_chat_stopped_on_a_little_while_ago(self):
        # a limit on one model does not show in an account's figures: without this a chat would bounce A, B, A, B…
        accts = [acct('team', 100, five=0.01), acct('ultra', 200, five=0.6), acct('alex', 200, five=0.7)]
        self.assertEqual(self.find(accts, 'ultra', avoid={'team'})['key'], 'alex')
        self.assertIsNone(self.find(accts, 'ultra', avoid={'team', 'alex'}))

    def test_picks_the_other_account_with_the_most_room(self):
        accts = [acct('team', 100, five=1.0, blocked=True), acct('ultra', 200, five=0.6), acct('alex', 200, five=0.2)]
        self.assertEqual(self.find(accts, 'team')['key'], 'alex')

    def test_never_the_account_the_chat_is_on_even_if_it_looks_the_emptiest(self):
        accts = [acct('team', 100, five=0.01), acct('ultra', 200, five=0.6)]  # a one-model limit hides in these figures
        self.assertEqual(self.find(accts, 'team')['key'], 'ultra')
        self.assertIsNone(self.find([acct('team', 100, five=0.01)], 'team'))

    def test_nor_that_same_account_under_its_other_name(self):
        same = [dict(acct('main', 100, five=0.5, week=0.2), org='e46'), dict(acct('team', 100, five=0.5, week=0.2), org='e46')]
        self.assertIsNone(self.find(same, 'team'))

    def test_full_or_silent_accounts_are_no_use(self):
        accts = [acct('team', 100, five=0.2), acct('ultra', 200, week=1.0, blocked=True), acct('alex', 200, reachable=False)]
        self.assertIsNone(self.find(accts, 'team'))

    def test_an_account_that_is_almost_full_is_not_worth_a_move(self):
        # each move re-reads the whole chat at full price: hopping to an account with 2% left wastes that for nothing
        accts = [acct('team', 100, five=1.0, blocked=True), acct('ultra', 200, week=0.98), acct('alex', 200, five=0.97)]
        self.assertIsNone(self.find(accts, 'team'))
        self.assertEqual(self.find(accts + [acct('third', None, week=0.90)], 'team')['key'], 'third')

    def test_keeps_to_the_plan_he_started_with(self):
        accts = [acct('team', 100, five=0.1), acct('ultra', 200, five=0.9), acct('alex', 200, five=0.5)]
        self.assertEqual(self.find(accts, 'ultra', want=200)['key'], 'alex')
        self.assertIsNone(self.find(accts[:2], 'ultra', want=200))


class Behind(unittest.TestCase):
    """ccd staying behind the chat: start it, wait for it, and start it again elsewhere when the watcher says so."""

    def stay(self, ends, moves=(), args=(), really_stopped=True, gap=None):
        """`ends` = how each claude ends, as os.waitpid statuses; `moves` = what the watcher asks for, per start."""
        starts, sent, asked, avoided, stops, joined, handlers = [], [], list(moves), [], [], [], {}
        self.avoided, self.stops, self.joined, self.handlers = avoided, stops, joined, handlers

        class Child:
            def __init__(self, words, env=None, close_fds=True):
                starts.append((words, env))
                self.kept_handles = not close_fds
                self.pid, self.returncode = 5000 + len(starts), None
                children.append(self)
        children = self.children = []

        def fake_watch(pid, account, want, move, stop, stopped_on=None):
            avoided.append(set(stopped_on or ()))
            stops.append(stop)
            if asked:
                ask = asked.pop(0)
                if ask:
                    move.update(dict(ask, going=True))
        class Inline:  # the watcher, run on the spot instead of beside the chat
            def __init__(self, target, args, daemon=None):
                self.go = lambda: target(*args)

            def start(self):
                self.go()

            def join(self, timeout=None):
                joined.append(timeout)

        def wait(pid, flags):
            end = next(waits)
            if callable(end):  # something happens while claude runs
                end = end()
            return pid, end
        waits = iter(ends)
        base = {'PATH': '/bin', 'CLAUDE_CODE_OAUTH_TOKEN': 'tok-team', 'CCD_ACCOUNT': 'team'}
        with mock.patch.object(ccd.subprocess, 'Popen', side_effect=Child), mock.patch.object(ccd.threading, 'Thread', side_effect=Inline), \
             mock.patch.object(ccd.os, 'waitpid', side_effect=wait), \
             mock.patch.object(ccd, 'watch', side_effect=fake_watch), mock.patch.object(ccd, 'tidy_terminal', side_effect=gap), \
             mock.patch.object(ccd, 'stopped', return_value=really_stopped), \
             mock.patch.object(ccd, 'note_move'), \
             mock.patch.object(ccd.signal, 'signal', side_effect=lambda sig, h: handlers.__setitem__(sig, h)), \
             mock.patch.object(ccd.os, 'kill', side_effect=lambda pid, sig: sent.append((pid, sig))), \
             redirect_stderr(io.StringIO()) as err:
            code = ccd.supervise(list(args), base, 'team', None)
        return code, starts, sent, err.getvalue()

    def test_an_ordinary_chat_starts_once_and_its_ending_is_passed_on(self):
        code, starts, sent, _ = self.stay([3 << 8])
        self.assertEqual(code, 3)
        self.assertEqual([w for w, _ in starts], [[ccd.CLAUDE, '--dangerously-skip-permissions']])
        self.assertEqual(starts[0][1]['CLAUDE_CODE_OAUTH_TOKEN'], 'tok-team')

    def test_a_moved_chat_is_reopened_whole_on_the_new_account(self):
        to = {'key': 'ultra', 'label': 'Ultra', 'token': 'tok-ultra', 'five': 0.2, 'week': 0.3}
        code, starts, sent, err = self.stay([signal.SIGTERM, 0], moves=[{'id': 'chat-1', 'to': to, 'old': 'team'}, None])
        self.assertEqual(code, 0)
        words, env = starts[1]
        self.assertEqual(words[:4], [ccd.CLAUDE, '--dangerously-skip-permissions', '--resume', 'chat-1'])
        self.assertEqual(len(words), 5)
        self.assertTrue(words[4].endswith(ccd.NUDGE))
        self.assertRegex(words[4], r'^\(ccd moved this chat from team to Ultra at \d')  # he can see in the chat what happened
        self.assertEqual((env['CLAUDE_CODE_OAUTH_TOKEN'], env['CCD_ACCOUNT']), ('tok-ultra', 'ultra'))
        self.assertGreater(int(env['CLAUDE_CODE_RESUME_THRESHOLD_MINUTES']), 10 ** 6)  # nobody is there to answer a question
        self.assertIn('Ultra', err)

    def test_a_move_off_a_switched_off_account_says_that_not_limit(self):
        to = {'key': 'ultra', 'label': 'Ultra', 'token': 'tok-ultra', 'five': 0.2, 'week': 0.3}
        _, starts, _, err = self.stay([signal.SIGTERM, 0], moves=[{'id': 'chat-1', 'to': to, 'old': 'team', 'why': 'off'},
                                                                  None])
        self.assertIn('Claude Code is switched off for team', err)
        self.assertNotIn('limit', err)
        self.assertRegex(starts[1][0][4], r'^\(ccd moved this chat from team to Ultra at \d\d:\d\d, because Claude Code was '
                                          r'switched off for the first\.\) ')

    def test_a_move_to_his_own_login_drops_the_token(self):
        to = {'key': 'main', 'label': 'your login', 'token': 'tok-main', 'five': 0.2, 'week': 0.3}
        _, starts, _, _ = self.stay([signal.SIGTERM, 0], moves=[{'id': 'chat-1', 'to': to, 'old': 'team'}, None])
        self.assertNotIn('CLAUDE_CODE_OAUTH_TOKEN', starts[1][1])

    def test_a_chat_can_move_more_than_once(self):
        a = {'key': 'ultra', 'label': 'Ultra', 'token': 'tok-ultra', 'five': 0.2, 'week': 0.3}
        b = {'key': 'alex', 'label': 'alex', 'token': 'tok-alex', 'five': 0.2, 'week': 0.3}
        code, starts, _, _ = self.stay([signal.SIGTERM, signal.SIGTERM, 0],
                                       moves=[{'id': 'chat-1', 'to': a, 'old': 'team'}, {'id': 'chat-1', 'to': b, 'old': 'ultra'}, None])
        self.assertEqual([e['CCD_ACCOUNT'] for _, e in starts], ['team', 'ultra', 'alex'])
        self.assertEqual(self.avoided, [set(), {'team'}, {'team', 'ultra'}])  # it never goes back where it just stopped

    def test_the_watcher_is_told_to_stop_and_is_waited_for_only_when_it_is_closing_the_chat(self):
        to = {'key': 'ultra', 'label': 'Ultra', 'token': 'tok-ultra', 'five': 0.2, 'week': 0.3}
        self.stay([0], moves=[None])
        self.assertTrue(self.stops[0].is_set())
        self.assertEqual(self.joined, [])  # he quit: the prompt comes back at once, even if the watcher is mid-check
        self.stay([signal.SIGTERM, 0], moves=[{'id': 'chat-1', 'to': to, 'old': 'team'}, None])
        self.assertEqual(len(self.joined), 1)  # it closed the chat: wait for it to say where to

    def test_closing_the_window_ends_claude_and_reopens_nothing(self):
        to = {'key': 'ultra', 'label': 'Ultra', 'token': 'tok-ultra', 'five': 0.2, 'week': 0.3}
        hup = lambda: self.handlers[signal.SIGHUP](signal.SIGHUP, None) or signal.SIGHUP  # the window closes mid-move
        code, starts, sent, _ = self.stay([hup], moves=[{'id': 'chat-1', 'to': to, 'old': 'team'}])
        self.assertEqual(len(starts), 1)
        self.assertIn((5001, signal.SIGHUP), sent)  # passed on to claude

    def test_told_to_end_just_as_the_chat_is_reopened_the_new_one_ends_too(self):
        to = {'key': 'ultra', 'label': 'Ultra', 'token': 'tok-ultra', 'five': 0.2, 'week': 0.3}

        def term_in_the_gap(saved):  # the signal lands after the old chat ended and before the new one starts
            self.handlers[signal.SIGTERM](signal.SIGTERM, None)
        code, starts, sent, _ = self.stay([signal.SIGTERM, signal.SIGTERM], moves=[{'id': 'chat-1', 'to': to, 'old': 'team'}, None],
                                          gap=term_in_the_gap)
        self.assertTrue(len(starts) == 1 or (5002, signal.SIGTERM) in sent)

    def test_ctrl_c_is_left_to_the_chat_without_being_switched_off_for_it(self):
        self.stay([0])
        for sig in (signal.SIGINT, signal.SIGQUIT):
            self.assertTrue(callable(self.handlers[sig]))  # a real do-nothing: "ignore" would be inherited by claude
            self.assertNotIn(self.handlers[sig], (signal.SIG_IGN, signal.SIG_DFL))

    def test_claude_gets_the_same_open_files_it_got_before(self):
        self.stay([0])
        self.assertTrue(self.children[0].kept_handles)

    def test_the_chat_knows_ccd_is_behind_it(self):
        _, starts, _, _ = self.stay([0])
        self.assertEqual(starts[0][1]['CCD_BEHIND'], str(os.getpid()))

    def test_a_chat_he_closed_himself_is_not_reopened(self):
        code, starts, _, _ = self.stay([0], moves=[None])
        self.assertEqual((code, len(starts)), (0, 1))

    def test_a_chat_that_was_killed_reports_it_the_way_a_shell_does(self):
        code, starts, _, _ = self.stay([signal.SIGKILL])
        self.assertEqual((code, len(starts)), (128 + signal.SIGKILL, 1))

    def test_ctrl_z_in_the_chat_hands_the_prompt_back_and_fg_carries_on(self):
        stopped = (signal.SIGTSTP << 8) | 0x7f
        code, starts, sent, _ = self.stay([stopped, 0])
        self.assertEqual((code, len(starts)), (0, 1))
        self.assertEqual(sent[0], (os.getpid(), signal.SIGSTOP))  # ccd stops with it, so the shell sees the job stop
        self.assertEqual(sent[1], (5001, signal.SIGCONT))  # and wakes it when he brings the job back

    def test_an_old_report_of_a_stop_does_not_stop_ccd_again_after_fg(self):
        # Ctrl-Z stops claude and ccd together; when fg wakes both, the report of claude's stop is still waiting to be read
        stopped = (signal.SIGTSTP << 8) | 0x7f
        code, starts, sent, _ = self.stay([stopped, 0], really_stopped=False)
        self.assertEqual((code, sent), (0, []))


class WhichWay(unittest.TestCase):
    def start(self, auto, argv=()):
        with mock.patch.object(ccd, 'accounts', return_value=[acct('ultra', 200, five=0.2)]), \
             mock.patch.object(ccd, 'ping', side_effect=lambda a: a), mock.patch.object(ccd, 'auto_on', return_value=auto), \
             mock.patch.object(ccd, 'supervise', return_value=7) as stay, mock.patch.object(ccd.os, 'execve') as ex, \
             mock.patch.object(sys, 'argv', ['ccd'] + list(argv)), redirect_stderr(io.StringIO()):
            os.environ.pop('CCD_DRY_RUN', None)
            try:
                ccd.main()
                code = None
            except SystemExit as e:
                code = e.code
        return stay, ex, code

    def test_in_a_terminal_ccd_stays_behind_the_chat(self):
        stay, ex, code = self.start(auto=True, argv=['200'])
        ex.assert_not_called()
        args, env, account, want = stay.call_args.args
        self.assertEqual((args, account, want, code), ([], 'ultra', 200, 7))

    def test_a_chat_started_with_its_own_settings_is_started_the_old_way(self):
        # a bot started through ccd with its own tools and safety settings: a move would reopen it
        # without them, so anything started with extra words is left alone
        words = ['--mcp-config', 'x.json', '--settings', 'y.json', '-n', 'chat-bot']
        stay, ex, _ = self.start(auto=True, argv=words)
        stay.assert_not_called()
        self.assertEqual(ex.call_args.args[1], [ccd.CLAUDE, '--dangerously-skip-permissions'] + words)

    def test_switched_off_or_run_by_a_script_it_starts_claude_the_old_way(self):
        stay, ex, _ = self.start(auto=False)
        stay.assert_not_called()
        self.assertEqual(ex.call_args.args[1], [ccd.CLAUDE, '--dangerously-skip-permissions'])

    def test_auto_is_on_only_in_a_real_terminal_and_can_be_switched_off(self):
        with mock.patch.object(ccd.sys.stdin, 'isatty', return_value=True), mock.patch.object(ccd.sys.stdout, 'isatty', return_value=True):
            with mock.patch.dict(os.environ, {'CCD_AUTO': '0'}):
                self.assertFalse(ccd.auto_on())
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop('CCD_AUTO', None)
                self.assertTrue(ccd.auto_on())
        with mock.patch.object(ccd.sys.stdin, 'isatty', return_value=False):
            self.assertFalse(ccd.auto_on())
        with mock.patch.object(ccd.sys, 'stdin', None):  # started with its input closed
            self.assertFalse(ccd.auto_on())


if __name__ == '__main__':
    unittest.main(verbosity=2)
