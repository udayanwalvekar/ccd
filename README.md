# ccd

Run Claude Code on whichever of your Claude accounts has the most room left. When a chat hits its usage limit, ccd moves that same chat to another of your accounts by itself, in the same window, with nothing summarised.

```
curl -fsSL https://raw.githubusercontent.com/udayanwalvekar/ccd/main/ccd.sh | bash
```

That's the whole install. You can also download [`ccd.sh`](ccd.sh) and run `bash ccd.sh`, or ask Claude Code to do it for you:

> Install ccd for me by running `curl -fsSL https://raw.githubusercontent.com/udayanwalvekar/ccd/main/ccd.sh | bash`, then tell me how to add my other Claude accounts.

**Needs:** a Mac, [Claude Code](https://claude.com/claude-code), and Python 3.9 or newer (it comes with Apple's Command Line Tools: `xcode-select --install`).

The installer puts the program in `~/.local/share/ccd`, puts `ccd`, `ccdm` and `ccdr` in a folder already on your PATH, and opens a short welcome that offers to add your other accounts. It changes nothing else. (Only if no suitable folder is on your PATH does it add `~/.local/bin` to it, in `~/.zshrc`.)

## Commands

| Type | What happens |
|---|---|
| `ccd` | Starts a chat on the account with the most room left. |
| `ccdm` | Lists your accounts with their 5-hour and weekly limits. You pick one, then the chat starts (m = manual). |
| `ccdr` | Lists your recent chats, with the ones that stopped at a limit on top. You pick a chat, then an account, and the same chat reopens there (r = resume). |
| `ccd accounts` | Shows every account and how much is left. |
| `ccd add` | Adds another of your accounts. |
| `ccd remove <name>` | Forgets an account. |
| `ccd 200` / `ccd 100` | Only uses accounts on that plan ($ a month). Works with `ccdm` and `ccdr` too. |
| `ccd update` | Gets the newest ccd. Your accounts stay. |
| `ccd uninstall` | Removes ccd, its settings and the tokens it kept. |

Any other words go to `claude` as they are, for example `ccd --model opus`.

## Adding an account

Your usual Claude Code login needs no setup: ccd finds it. For each other account, run `ccd add`. It runs `claude setup-token`, which opens a sign-in page in your browser. Sign in there with the account you want to add. If the page shows a different account, sign out of claude.ai first, or open the link it prints in a private window. ccd reads the token off the screen, checks that it works, asks what to call the account and which plan it's on, and keeps it.

Already have a token? Choose "Paste a token I already have", or pipe it in: `ccd add Work 200 < token.txt`.

## How the automatic move works

ccd stays running behind each chat it starts. When the chat stops at a usage limit and another account has room, ccd closes the chat and reopens it with `claude --resume` on that account, in the same window. The reopened chat gets a first message saying which account it moved from and to, and asking it to carry on.

- It waits 20 seconds first, so you can read the limit message.
- It waits while a background command of the chat is still busy (a build, a render). An idle one, like a preview server, is not waited for.
- It skips accounts with under 5% left, and keeps away for an hour from an account the chat just stopped on.
- No account has room? The chat is left as it is, and ccd checks again every 5 minutes.
- Background commands and helper agents that were still running end with the move. The reopened chat is told so and restarts what is still needed.
- `CCD_AUTO=0 ccd` switches the automatic move off for one chat. A chat started with extra words for claude (`ccd --model x`) is never moved.
- Every move is written to `~/.config/ccd/moves.log`.

## Permission prompts are off

Chats start with `claude --dangerously-skip-permissions`, so a chat that moves by itself never sits waiting on a question nobody is there to answer. Claude can then run commands and edit files without asking first. To get Claude Code's own prompts back, put this in `~/.config/ccd/config.json`:

```json
{ "claude_args": [] }
```

## Your own accounts only

ccd is for switching between Claude accounts **you** own. Anthropic's [Consumer Terms](https://www.anthropic.com/legal/consumer-terms) don't allow sharing your login with anyone else. Their [Claude Code docs](https://code.claude.com/docs/en/legal-and-compliance) say subscription logins are meant for ordinary use of Claude Code. To read an account's limits, ccd sends a 1-token request with that account's token. Anthropic can change how limits and logins work at any time. Use ccd at your own risk.

## Privacy

- Tokens are kept in the macOS Keychain (service `ccd`). A token goes only into the environment of the chat that uses it (and so of the commands that chat runs). ccd never prints one, but `claude setup-token` shows it on screen once while you add an account, as it always does.
- Your Claude Code login is read from the Keychain, never changed or refreshed. Once it has been unused long enough to expire, ccd can't check its limits; it shows as "not checked", and starting a chat on it lets Claude Code renew it.
- ccd talks only to `api.anthropic.com`, plus GitHub when you run `ccd update`.

## Good to know

- The first message after a move re-reads the whole chat on the new account, once. On a very long chat, that takes a visible bite out of the new account's 5-hour limit.
- Extra words you typed after `ccd` (a model, say) are not carried into the reopened chat. It opens with your defaults.
- Work that barely uses the processor (a download, a slow remote job) can look idle and get cut off by a move. The reopened chat is told to restart it.
- Chats that were already open before you installed ccd, or started with plain `claude`, are not watched. Use `ccdr` for those.
- Mac only for now.

## License

MIT
