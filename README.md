# ccd

ccd does three main things:

1. **It always starts in dangerously mode.** No permission prompts. Claude doesn't stop to ask you before it runs a command or changes a file.
2. **You can add all your Claude subscriptions.** ccd already knows the account you use in Claude Code. Add your other accounts once with `ccd add`, and you never have to swap tokens by hand again. ccd starts every chat on the account with the most usage left.
3. **When one account runs out, ccd moves your chat to another one by itself.** You don't start a new chat, and Claude still has the whole conversation.

It also has a bunch of customisations. I explain them in the story below.

## Install

```
curl -fsSL https://raw.githubusercontent.com/udayanwalvekar/ccd/main/ccd.sh | bash
```

You need a Mac, [Claude Code](https://claude.com/claude-code) and Python 3.9 or newer.

To see the main commands, type `ccd help`. To remove ccd and the accounts you added, type `ccd uninstall`.

## Why I made this

It started as a simple alias. I always run Claude Code with `--dangerously-skip-permissions`, so `ccd` was just short for that: **C**laude **C**ode, **d**angerously.

Then I needed more usage, so I added more Claude accounts. Every time I switched, I had to take one token out of my `~/.zshrc` and put the next one in. Again and again. So I made ccd do it for me. It checks all my accounts and starts the chat on the one with the most usage left.

Then came the next problem. A long chat would run out of usage. I could wait for that account to reset, or ask another Claude to read the old chat and start again. Both were bad. So I automated that too. Now when a chat runs out, ccd moves it to another account by itself. Same chat, same window.

Some tasks are really long and need a $200 plan, not a $100 one. So `ccd 200` only uses my $200 accounts.

Sometimes I just want to pick the account myself. So I made `ccdm`. The m is for manual.

<img src="docs/ccdm.png" width="760" alt="ccdm: your accounts with their 5-hour and weekly limits; the one with the most room is highlighted, a full one is greyed out">

And if I want to move a chat by hand, there's `ccdr`. The r is for resume. You pick the chat, then the account.

<img src="docs/ccdr.png" width="760" alt="ccdr: your recent chats, the one that stopped at its limit on top">
