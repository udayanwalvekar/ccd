# ccd

ccd does three things for Claude Code:

1. **Dangerously mode, always on.** Every chat starts with `--dangerously-skip-permissions`, so there are no permission prompts: Claude runs commands and edits files without asking you first.
2. **All your Claude subscriptions in one place.** Your usual Claude Code login works as it is. Add each other account once with `ccd add` (you sign in through your browser), and never swap tokens by hand again. ccd starts every chat on the account with the most usage left.
3. **A chat that doesn't stop at a limit.** When one account hits its usage limit, ccd carries on the same chat on another account. No new chat, nothing summarised.

It also has a few customisations (`ccd 200`, `ccdm` and `ccdr`), which the story below explains. `ccd help` lists the commands, and `ccd uninstall` removes ccd.

```
curl -fsSL https://raw.githubusercontent.com/udayanwalvekar/ccd/main/ccd.sh | bash
```

Mac only. Needs [Claude Code](https://claude.com/claude-code) and Python 3.9 or newer.

## Why I made this

It started as a simple alias. I always run Claude Code with `--dangerously-skip-permissions`, so `ccd` was just short for that: **C**laude **C**ode, **d**angerously.

Then I needed more usage, so I added more Claude accounts. Every switch meant taking one token out of my `~/.zshrc` and putting the next one in, again and again. So I made ccd do the routing: it checks every account and starts the chat on the one with the most room left.

Then came the next problem. A long chat would run out on its account, and I had two bad options: wait for that account to reset, or ask another Claude to read the old chat and start over. So I automated that too. Now when a chat hits its limit, ccd reopens it on another account by itself.

Some tasks are really long and need the usage of a $200 plan, not a $100 one. So `ccd 200` only uses my $200 accounts.

And sometimes I just want to pick the account myself. So I added `ccdm` (m = manual).

<img src="docs/ccdm.png" width="760" alt="ccdm: your accounts with their 5-hour and weekly limits; the one with the most room is highlighted, a full one is greyed out">

For the rare time I want to move a chat by hand, there's `ccdr` (r = resume): pick the chat, then the account.

<img src="docs/ccdr.png" width="760" alt="ccdr: your recent chats, the one that stopped at its limit on top">
