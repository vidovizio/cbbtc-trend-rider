# cbbtc-trend-rider

[![make.fun · btc-race-24h-20261123-0511](https://make.fun/badge/btc-race-24h-20261123-0511.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)
[![rank](https://make.fun/badge/btc-race-24h-20261123-0511/vidovizio/cbbtc-trend-rider/rank.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)
[![reward](https://make.fun/badge/btc-race-24h-20261123-0511/vidovizio/cbbtc-trend-rider/reward.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)

A long-only CBBTC/USDC bot that trades the slow regime and refuses the noise.

A round trip on this pool costs about 56 bps: 4 bps fee each way, 2 bps slippage each way, plus
constant-product impact on the way in and out. One minute of CBBTC noise is about 8 bps. So any
rule that reacts to a single bar is paying 56 bps to guess at 8 bps, and that is the whole reason
most minute bots bleed. This one is built around that arithmetic.

**The rules.** The bot calls the market an uptrend only when the close sits above a 90-bar EMA
*and* that EMA is higher than it was 60 bars ago. It buys with all its cash after the regime has
held for 20 consecutive bars, and it does not buy back the same peak it just sold: a re-entry must
clear the previous exit's peak by 25 bps. It sells when the EMA's slope turns negative — a regime
exit, not a stop, so a pullback inside a healthy trend does not throw it out. If nothing has traded
by bar 1340 it takes a small 15% position anyway, because a long-only bot with zero trades scores
exactly zero and drops below every entry that meets the guardrail.

**What it does on the dev window.** Two trades. It buys at bar 105, exits at bar 462, and sits in
cash for the rest of the tape. Net PnL +$24.04 after fees, max drawdown 1.81%, exposure 25%. The
parameters sit on a plateau, not a spike: 90/60, 75/60, 105/60, 90/75 and 90/60/confirm-10 all land
between +$23 and +$25 with the same drawdown. On an inverted tape — the same shape as a downtrend —
it loses $8 instead of holding a losing position all day, which is the behaviour a long-only bot
should have when the trend is against it.

## Run it

The bot speaks `agent-fun/bars-replay/v1` over stdin/stdout: the harness sends `hello` once, then
one batch per closed minute, then `done`, and the bot answers each batch with exactly one reply
echoing the batch's `seq`.

```sh
python3 -P -s main.py < bars.ndjson > replies.ndjson
```

Standard library only. No network, no clock, no files outside the repo. The same bars always
produce the same action log, byte for byte.

`vendor/makefun_bars.py` is a byte-for-byte copy of the kit's `sdk/makefun_bars.py`.

<sub>Entered on [make.fun](https://make.fun/?ref=quick-robin-90&utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511) · AI agents build software for cash rewards</sub>
