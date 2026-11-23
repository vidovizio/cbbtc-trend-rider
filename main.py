"""CBBTC/USDC minute bot: trade the slow regime, not the noise.

One position, long only, decided once per closed one-minute bar and filled at the next open.

  Regime  -- the market is "in an uptrend" when the close sits above a slow EMA and that EMA is
             higher than it was SLOPE_BARS bars ago. Everything else is a range and the bot stays
             in cash. On this pool a full round trip costs ~56 bps (4 bps fee each way, 2 bps
             slippage each way, plus constant-product impact), while one-minute noise is ~8 bps,
             so any rule that trades inside a range is paying fees to guess. The bot refuses.
  Entry   -- the regime must have held for CONFIRM_BARS consecutive bars, and after an exit the
             close must clear that exit's peak by REENTRY_BPS, so the bot does not buy the same
             top back. All cash goes in: one position, no leverage, no sizing games.
  Exit    -- the EMA's slope over EXIT_SLOPE_BARS turns negative: the trend that justified the
             position is gone. That is a regime exit, not a stop, so it does not shake the bot out
             on a normal pullback inside a healthy trend.
  Probe   -- if no trade has happened by PROBE_BAR the bot takes a small position anyway. A
             long-only bot that never trades scores exactly zero and drops below every entry that
             meets the guardrail, so sitting perfectly still is not free.

Nothing here reads the clock, the filesystem, the network or a random source. The same bars always
produce the same orders, and the arithmetic is float64 over + - * / on integers parsed from the
bars, so two runs agree bit for bit.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bars  # noqa: E402

#: Traded symbol: the universe has exactly one.
SYMBOL = "CBBTC"

#: Span of the regime EMA on closes.
EMA_BARS = 90
#: The EMA must be higher than it was this many bars ago for the regime to count as an uptrend.
SLOPE_BARS = 60
#: Span of the EMA slope used to decide the exit.
EXIT_SLOPE_BARS = 60
#: Consecutive bars the regime must hold before buying: a confirmed trend, not the first tick up.
CONFIRM_BARS = 20
#: After an exit, a new entry must clear the previous exit's peak by this much.
REENTRY_BPS = 25
#: Participation floor: if nothing has traded by this bar, take a small position.
PROBE_BAR = 1340
#: Size of that probe, in bps of cash (1500 = 15%).
PROBE_FRAC_BPS = 1500

BPS = 10_000
#: Every order's slippage cap, 1% past the close it was decided on: a sell into a liquidity hole is
#: refused rather than filled for almost nothing.
MAX_SLIPPAGE_BPS = 100


class RegimeBot:
    """The rules, one closed bar at a time. decide() answers None, "buy" or "sell"."""

    def __init__(
        self,
        ema_bars=EMA_BARS,
        slope_bars=SLOPE_BARS,
        exit_slope_bars=EXIT_SLOPE_BARS,
        confirm_bars=CONFIRM_BARS,
        reentry_bps=REENTRY_BPS,
        probe_bar=PROBE_BAR,
        probe_frac_bps=PROBE_FRAC_BPS,
    ):
        self.ema_bars = ema_bars
        self.slope_bars = slope_bars
        self.exit_slope_bars = exit_slope_bars
        self.confirm_bars = confirm_bars
        self.reentry_bps = reentry_bps
        self.probe_bar = probe_bar
        self.probe_frac_bps = probe_frac_bps

        self.ema = None
        self.ema_trail = []
        self.i = -1
        #: True while the account holds the position.
        self.long = False
        #: Highest close since the entry: remembered so a re-entry must clear it.
        self.peak = 0.0
        self.last_exit_peak = None
        self.uptrend_streak = 0
        self.traded = False
        self._probing = False

    # -- indicator ---------------------------------------------------------------------------

    def on_bar(self, high, low, close):
        self.i += 1
        c = float(close)
        k = 2.0 / (self.ema_bars + 1)
        if self.ema is None:
            self.ema = c
        else:
            self.ema += k * (c - self.ema)
        self.ema_trail.append(self.ema)
        keep = max(self.slope_bars, self.exit_slope_bars) + 2
        if len(self.ema_trail) > keep:
            del self.ema_trail[0]
        # The regime streak counts bars where the uptrend holds, so an entry needs a trend that
        # has already been in place, not a single good print.
        slope = self._slope(self.slope_bars)
        if slope is not None and slope > 0.0 and c > self.ema:
            self.uptrend_streak += 1
        else:
            self.uptrend_streak = 0

    def on_fill_state(self, holding):
        """Fold the account in: holding is (qty, cost) or None."""
        if holding is not None and not self.long:
            self.long = True
            self.traded = True
            self.peak = self._last_close or 0.0

    def on_flat(self, exit_close):
        """The position is gone (sold, or flattened at the end)."""
        if self.long:
            self.long = False
            if self.peak > 0.0:
                self.last_exit_peak = self.peak
            self.peak = 0.0

    def want_fraction_bps(self):
        """Share of cash to commit on a pending buy (10000 = all of it)."""
        return self.probe_frac_bps if self._probing else BPS

    # -- rules -------------------------------------------------------------------------------

    def decide(self, close):
        if self.long:
            return self._decide_exit(float(close))
        return self._decide_entry(float(close))

    def _slope(self, bars):
        if self.ema is None or len(self.ema_trail) <= bars:
            return None
        return self.ema - self.ema_trail[-1 - bars]

    def _decide_entry(self, close):
        self._probing = False
        if self.i < max(self.ema_bars, max(self.slope_bars, self.exit_slope_bars) + 2):
            return None
        slope = self._slope(self.slope_bars)
        if slope is not None and slope > 0.0 and close > self.ema:
            if self.uptrend_streak >= self.confirm_bars:
                if self.last_exit_peak is None or close * BPS > self.last_exit_peak * (BPS + self.reentry_bps):
                    return "buy"
        # Participation floor: a bot with zero trades scores zero and fails the guardrail.
        if not self.traded and self.probe_bar and self.i >= self.probe_bar:
            self._probing = True
            return "buy"
        return None

    def _decide_exit(self, close):
        if close > self.peak:
            self.peak = close
        # Regime exit: the trend that justified the position has turned. A pullback inside an
        # intact trend does not qualify, which is the whole point: 56 bps a round trip is more
        # than a healthy pullback is worth.
        slope = self._slope(self.exit_slope_bars)
        if slope is not None and slope < 0.0:
            return "sell"
        return None


BOT = None
_LAST_CLOSE = 0.0


def on_hello(state):
    global BOT
    BOT = RegimeBot()


def on_batch(state, batch):
    global _LAST_CLOSE
    bot = BOT
    holding = state.positions.get(SYMBOL)
    bar = None
    for b in batch["bars"]:
        if b["symbol"] == SYMBOL:
            bar = b
    if bar is not None:
        bot._last_close = float(bar["c"])
        _LAST_CLOSE = bot._last_close
        bot.on_bar(int(bar["h"]), int(bar["l"]), int(bar["c"]))
    else:
        bot._last_close = _LAST_CLOSE
    # The account, not the bot's memory, is the truth about what is held.
    bot.on_fill_state(None if holding is None else (holding.qty, holding.cost))
    if holding is None:
        bot.on_flat(state.close(SYMBOL) or 0)
    if state.warming_up or bar is None:
        return []
    action = bot.decide(int(bar["c"]))
    if action == "buy" and holding is None:
        notional = state.cash * bot.want_fraction_bps() // BPS
        if notional < int(state.hello["fees"]["min_notional_quote_units"]):
            return []
        return [{
            "side": "buy",
            "symbol": SYMBOL,
            "notional_quote_units": notional,
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        }]
    if action == "sell" and holding is not None:
        return [{
            "side": "sell",
            "symbol": SYMBOL,
            "qty": holding.qty,
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        }]
    return []


def main():
    makefun_bars.run(on_batch, on_hello=on_hello)


if __name__ == "__main__":
    main()
