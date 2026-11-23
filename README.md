# ccd

Run Claude Code on all your Claude accounts, with dangerously mode always on.

<img src="docs/install.png" width="760" alt="The welcome after installing: what ccd does, the accounts it found, and an offer to add another account">

ccd does three main things:

1. **It always starts Claude Code in dangerously mode.** No permission prompts. Claude doesn't stop to ask you before it runs a command or changes a file.
2. **You can add all your Claude subscriptions.** You never have to worry about swapping tokens by hand again. ccd starts every chat on the account with the most usage left.
3. **When one account runs out, ccd moves your chat to another one by itself.** You don't start a new chat. Claude still has the whole conversation, in the same window.

It also gives you a bunch of customisations. They're all below.

## Install

```
curl -fsSL https://raw.githubusercontent.com/udayanwalvekar/ccd/main/ccd.sh | bash
```

Or ask Claude Code to do it for you:

> Install ccd for me by running `curl -fsSL https://raw.githubusercontent.com/udayanwalvekar/ccd/main/ccd.sh | bash`, then tell me how to add my other Claude accounts.

You need a Mac, [Claude Code](https://claude.com/claude-code) and Python 3.9 or newer.

ccd already knows the account you use in Claude Code. To add your other accounts, run `ccd add` once for each one and sign in with it in your browser.

## Why I made this

It started as a simple alias. I always run Claude Code with `--dangerously-skip-permissions`, so `ccd` was just short for that: **C**laude **C**ode, **d**angerously.

Then I needed more usage, so I added more Claude accounts. Every switch meant taking one token out of my `~/.zshrc` and putting the next one in, again and again. So I made ccd do it for me: it checks every account and starts the chat on the one with the most usage left.

Then came the next problem. A long chat would run out on its account, and I had two bad options: wait for that account to reset, or ask another Claude to read the old chat and start over. So I automated that too. Now when a chat hits its limit, ccd reopens the same chat on another account, in the same window, with nothing summarised.

Some tasks are really long and need the usage of a $200 plan, not a $100 one. So `ccd 200` only uses my $200 accounts.

And sometimes I just want to pick the account myself. So I added `ccdm` (m = manual).

<img src="docs/ccdm.png" width="760" alt="ccdm: your accounts with their 5-hour and weekly limits; the one with the most room is highlighted, a full one is greyed out">

For the rare time I want to move a chat by hand, there's `ccdr` (r = resume): pick the chat, then the account.

<img src="docs/ccdr.png" width="760" alt="ccdr: your recent chats, the one that stopped at its limit on top">

## Customisations

| Type | What it does |
|---|---|
| `ccd` | Starts a chat on the account with the most usage left. |
| `ccdm` | Shows all your accounts and how much is left on each. You pick one. |
| `ccdr` | Shows your recent chats. You pick a chat, then an account, and it carries on there. |
| `ccd 200` | Only uses your $200 accounts. `ccd 100` only uses your $100 ones. Works with `ccdm` and `ccdr` too. |
| `ccd accounts` | Shows how much is left on every account. |
| `ccd add` | Adds another account. |
| `ccd remove <name>` | Forgets an account. |
| `ccd update` | Gets the newest ccd. Your accounts stay. |
| `ccd uninstall` | Removes ccd and the accounts you added. |
| `CCD_AUTO=0 ccd` | Starts a chat that won't move by itself. |

Anything else you type goes straight to Claude Code, like `ccd --model opus` (except `--help` and `--version`, which ccd answers itself). A chat started that way won't move by itself.

Want the permission prompts back? Open `~/.config/ccd/config.json` and add this line next to what's already there. Don't replace the file: your accounts are in it.

```json
"claude_args": []
```

## How the move works

- ccd waits 20 seconds first, so you can read the limit message.
- If the chat has a command still working, like a build, it waits until that's done. Something that just sits there, like a preview server, isn't waited for: it stops with the move, and Claude is told to restart it.
- If no account has room, the chat stays as it is, and ccd checks again every 5 minutes.
- Every automatic move is written to `~/.config/ccd/moves.log`.

Use ccd only with your own Claude accounts. Sharing a login with someone else is against Anthropic's [terms](https://www.anthropic.com/legal/consumer-terms).
