# ccd

Claude Code, dangerously, on all your Claude accounts.

<img src="docs/ccdm.png" width="760" alt="ccdm: your accounts with their 5-hour and weekly limits; the one with the most room is highlighted, a full one is greyed out">

- Dangerously mode is always on.
- Add all your Claude subscriptions once. Never swap tokens by hand again.
- When one account runs out, your chat moves to another one by itself. Same chat. No new chat.

```
curl -fsSL https://raw.githubusercontent.com/udayanwalvekar/ccd/main/ccd.sh | bash
```

Mac only.

## Why I made this

It started as an alias. I always run Claude Code with `--dangerously-skip-permissions`, so ccd was short for that: Claude Code, dangerously.

Then I needed more usage, so I added more accounts. Every switch meant swapping tokens in my `~/.zshrc`. Again and again. So now ccd picks the account with the most usage left.

Then my long chats started running out. I could wait for the reset, or ask another Claude to read the old chat and start over. Both were bad. So now ccd moves the chat to another account by itself.

Some tasks need a $200 plan. `ccd 200` only uses those accounts.

Sometimes I want to pick the account myself. That's `ccdm`, the picture above.

And sometimes I want to move a chat by hand. That's `ccdr`.

<img src="docs/ccdr.png" width="760" alt="ccdr: your recent chats, the one that stopped at its limit on top">
