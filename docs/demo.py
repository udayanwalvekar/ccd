"""Runs the real ccd screens on made-up accounts and chats, for the README screenshots. Nothing is checked over the
network, nothing starts, no real account or chat is read.
  python3 -I docs/demo.py ccdm | ccdr | setup | accounts"""
import atexit, json, os, shutil, sys, tempfile, time
from importlib.machinery import SourceFileLoader

D = tempfile.mkdtemp(prefix='ccd-demo-')
atexit.register(shutil.rmtree, D, True)
os.environ.update(CCD_HOME=os.path.join(D, 'config'), CCD_TOKEN_STORE='file', CCD_DRY_RUN='1')
ccd = SourceFileLoader('ccd', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ccd')).load_module()
now = time.time()
HOME = os.path.expanduser('~')

# (key, label, plan, 5-hour used, weekly used, at its limit)
DEMO = [('main', 'Your Claude Code login ($200)', 200, 0.12, 0.31, False),
        ('work', 'Work ($100)', 100, 0.64, 0.42, False),
        ('side', 'Side projects ($200)', 200, 1.0, 0.71, True)]


def accounts():
    return [dict(key=k, label=l, token='demo', plan=p) for k, l, p, *_ in DEMO]


def ping(a):
    for k, _, _, five, week, full in DEMO:
        if k == a['key']:
            a.update(five=five, week=week, blocked=full, org='org-' + k,
                     five_reset=now + 2 * 3600 + 14 * 60, week_reset=now + 4 * 86400 + 3 * 3600)
    return a


ccd.accounts, ccd.ping = accounts, ping
ccd.setup_token = lambda cols: []  # "Add one" in the demo never runs a sign-in
ccd.login = lambda: dict(key='main', label=DEMO[0][1], token='demo', plan=200, expired=False)
ccd.added = lambda: [(k, l, p) for k, l, p, *_ in DEMO[1:]]

# Chats for ccdr
ccd.PROJECTS, ccd.LIVE = os.path.join(D, 'projects'), os.path.join(D, 'sessions')
os.makedirs(ccd.LIVE)


def stamp(ago):
    return time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(now - ago))


def chat(sid, title, said, folder, ago, limited=False):
    cwd = os.path.join(HOME, folder)
    d = os.path.join(ccd.PROJECTS, cwd.replace('/', '-'))
    os.makedirs(d, exist_ok=True)
    lines = [{'type': 'ai-title', 'aiTitle': title},
             {'type': 'user', 'message': {'role': 'user', 'content': said}, 'cwd': cwd, 'entrypoint': 'cli',
              'timestamp': stamp(ago + 60)}]
    if limited:
        lines.append({'type': 'assistant', 'timestamp': stamp(ago), 'isApiErrorMessage': True, 'error': 'rate_limit',
                      'apiError': 'usage_limit_reached', 'cwd': cwd, 'entrypoint': 'cli',
                      'message': {'role': 'assistant', 'model': '<synthetic>',
                                  'content': [{'type': 'text', 'text': "You've hit your 5-hour limit"}]}})
    else:
        lines.append({'type': 'assistant', 'timestamp': stamp(ago), 'cwd': cwd, 'entrypoint': 'cli',
                      'message': {'role': 'assistant', 'model': 'claude-opus-5-5',
                                  'content': [{'type': 'text', 'text': 'Done.'}]}})
    path = os.path.join(d, sid + '.jsonl')
    with open(path, 'w') as f:
        f.write('\n'.join(json.dumps(l) for l in lines) + '\n')
    os.utime(path, (now - ago, now - ago))


chat('a1', 'Migrate billing to the new API', 'run the full test suite again and fix what fails', 'code/billing', 12 * 60, True)
chat('a2', 'Launch post for the new pricing page', 'make the second paragraph shorter', 'writing/launch', 40 * 60)
chat('a3', 'Speed up the image pipeline', 'try the batch size at 64 and compare', 'code/images', 3 * 3600)
chat('a4', 'Plan for the team offsite', 'add a rain backup for day two', 'notes', 26 * 3600)

mode = sys.argv[1] if len(sys.argv) > 1 else 'ccdm'
if mode == 'setup':
    ccd.CLAUDE = '/bin/sh'  # "Claude Code found"
    sys.exit(ccd.cmd_setup([]))
if mode == 'accounts':
    sys.exit(ccd.cmd_accounts([]))
sys.argv = [mode]
ccd.main()
