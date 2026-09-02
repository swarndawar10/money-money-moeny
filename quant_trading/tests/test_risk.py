"""
Deterministic Risk Manager Unit Tests (Python verification suite)
Validates all core risk requirements with actual assertions.
No test may pass based on "visual inspection of output" — every behavior
must be verified by assertEqual / assertTrue / assertFalse.

Tests:
  1. ATR = 0 → rejected
  2. ATR = NaN → rejected
  3. Risk-based position sizing
  4. Portfolio exposure limit
  5. Sector exposure limit
  6. Daily loss lock full lifecycle (trigger → regime persistence → daily reset)
  7. Drawdown lock full lifecycle (trigger → regime persistence → no daily reset)
  8. Circuit breakers fire when signal == NONE (the core bug-fix test)
  9. Equity mark-to-market correctness (buy/fall/rise/cash≠equity)
 10. Peak equity tracking (drawdown from peak, not initial capital)
 11. evaluateRisk idempotence
 12. ELEVATED_RISK blocks entries, exits continue
 13. Equity stable after buy
"""

import math
import unittest


class Config:
    def __init__(self):
        self.atr_initial_multiplier  = 2.0
        self.atr_trailing_multiplier = 2.5
        self.max_risk_per_trade      = 0.01
        self.max_portfolio_exposure  = 0.50
        self.max_sector_exposure     = 0.20
        self.max_positions           = 5
        self.max_daily_loss          = 0.03
        self.max_drawdown            = 0.10
        self.momentum_threshold      = 0.005
        self.volume_multiplier       = 1.5
        self.vix_high_risk_threshold = 22.0

    def validate(self):
        assert self.atr_initial_multiplier > 0
        assert self.atr_trailing_multiplier > 0
        assert 0 < self.max_risk_per_trade < 1
        assert 0 < self.max_portfolio_exposure <= 1
        assert 0 < self.max_sector_exposure <= 1
        assert self.max_positions > 0
        assert 0 < self.max_daily_loss <= 1
        assert 0 < self.max_drawdown <= 1


class Position:
    def __init__(self, sector, entry_price, qty, initial_stop):
        self.sector = sector
        self.entry_price = entry_price
        self.highest_price = entry_price
        self.current_price = entry_price
        self.qty = qty
        self.initial_stop = initial_stop


class MockRiskManager:
    """Python mirror of the C++ RiskManager for test validation."""

    def __init__(self, config, initial_capital=500000.0):
        self.config = config
        self.cash = initial_capital
        self.initial_capital = initial_capital
        self.peak_equity = initial_capital
        self.daily_starting_equity = initial_capital
        self.current_trading_day = -1

        self.positions = {}

        self.manual_enabled = True
        self.market_allows_entries = True
        self.daily_loss_locked = False
        self.drawdown_locked = False
        self.current_regime = "NORMAL"

    def get_equity(self):
        mval = sum(p.qty * p.current_price for p in self.positions.values())
        return self.cash + mval

    def calc_total_invested_value(self):
        return sum(p.qty * p.current_price for p in self.positions.values())

    def calc_sector_exposure(self, sector):
        return sum(p.qty * p.current_price for p in self.positions.values()
                   if p.sector == sector)

    def entries_allowed(self):
        return (self.manual_enabled
                and self.market_allows_entries
                and not self.daily_loss_locked
                and not self.drawdown_locked)

    @staticmethod
    def to_kolkata_day(unix_ts):
        kolkata_ts = unix_ts + 19800
        days = kolkata_ts // 86400
        z = days + 719468
        era = (z if z >= 0 else z - 146096) // 146097
        doe = z - era * 146097
        yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
        y = yoe + era * 400
        doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
        mp = (5 * doy + 2) // 153
        d = doy - (153 * mp + 2) // 5 + 1
        m = mp + (3 if mp < 10 else -9)
        y += (1 if m <= 2 else 0)
        return int(y * 10000 + m * 100 + d)

    def on_timestamp(self, unix_ts):
        day = self.to_kolkata_day(unix_ts)
        if day != self.current_trading_day:
            eq = self.get_equity()
            self.daily_starting_equity = eq
            self.daily_loss_locked = False
            self.current_trading_day = day

    def evaluate_risk(self):
        """Public, idempotent risk evaluation — mirrors C++ evaluateRisk()."""
        equity = self.get_equity()
        self._evaluate_circuit_breakers(equity)

    def _evaluate_circuit_breakers(self, equity):
        if equity > self.peak_equity:
            self.peak_equity = equity
        if not self.drawdown_locked:
            dd = ((self.peak_equity - equity) / self.peak_equity
                  if self.peak_equity > 0 else 0)
            if dd >= self.config.max_drawdown:
                self.drawdown_locked = True
        if not self.daily_loss_locked:
            loss = ((self.daily_starting_equity - equity) / self.daily_starting_equity
                    if self.daily_starting_equity > 0 else 0)
            if loss >= self.config.max_daily_loss:
                self.daily_loss_locked = True

    def update_regime(self, regime):
        self.current_regime = regime
        if regime in ("LOW_RISK", "NORMAL"):
            self.market_allows_entries = True
        else:
            self.market_allows_entries = False

    def update_positions(self, ticker, current_price, atr):
        if ticker not in self.positions:
            return
        pos = self.positions[ticker]
        pos.current_price = current_price
        if current_price > pos.highest_price:
            pos.highest_price = current_price

        effective_stop = pos.initial_stop
        if atr is not None and math.isfinite(atr) and atr > 0:
            trailing_stop = pos.highest_price - atr * self.config.atr_trailing_multiplier
            effective_stop = max(pos.initial_stop, trailing_stop)

        if current_price <= effective_stop:
            revenue = pos.qty * current_price
            self.cash += revenue
            del self.positions[ticker]

    def process_signal(self, ticker, current_price, atr, sector, sig="BUY"):
        if sig != "BUY":
            return False, "NOT_BUY"
        if atr is None or not math.isfinite(atr) or atr <= 0:
            return False, "ATR_INVALID"
        if ticker in self.positions:
            return False, "ALREADY_HELD"

        # Defensive re-evaluation (idempotent)
        self.evaluate_risk()

        if not self.entries_allowed():
            if self.drawdown_locked:
                return False, "DRAWDOWN_LOCK"
            if self.daily_loss_locked:
                return False, "DAILY_LOSS_LOCK"
            if not self.market_allows_entries:
                return False, f"MARKET_REGIME({self.current_regime})"
            return False, "MANUAL_DISABLED"

        if len(self.positions) >= self.config.max_positions:
            return False, "MAX_POSITIONS"

        equity = self.get_equity()
        stop_dist = atr * self.config.atr_initial_multiplier
        risk_amt = equity * self.config.max_risk_per_trade
        qty = int(risk_amt // stop_dist)
        if qty <= 0:
            return False, "ZERO_QTY"

        new_val = qty * current_price

        invested = self.calc_total_invested_value()
        if (invested + new_val) > equity * self.config.max_portfolio_exposure:
            rem = equity * self.config.max_portfolio_exposure - invested
            if rem <= 0:
                return False, "MAX_PORTFOLIO_EXPOSURE"
            qty = int(rem // current_price)
            new_val = qty * current_price
            if qty <= 0:
                return False, "MAX_PORTFOLIO_EXPOSURE"

        sec_invested = self.calc_sector_exposure(sector)
        if (sec_invested + new_val) > equity * self.config.max_sector_exposure:
            rem = equity * self.config.max_sector_exposure - sec_invested
            if rem <= 0:
                return False, "MAX_SECTOR_EXPOSURE"
            qty = int(rem // current_price)
            new_val = qty * current_price
            if qty <= 0:
                return False, "MAX_SECTOR_EXPOSURE"

        if new_val > self.cash:
            qty = int(self.cash // current_price)
            new_val = qty * current_price
            if qty <= 0:
                return False, "INSUFFICIENT_CASH"

        self.cash -= new_val
        init_stop = current_price - stop_dist
        self.positions[ticker] = Position(sector, current_price, qty, init_stop)
        return True, "ACCEPTED"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════════
class TestRiskControls(unittest.TestCase):
    BASE_TS = 1546300800  # 2019-01-01 00:00:00 UTC

    def setUp(self):
        self.cfg = Config()
        self.cfg.validate()
        self.rm = MockRiskManager(self.cfg, 500000.0)
        self.rm.on_timestamp(self.BASE_TS)

    # ── 1 ──────────────────────────────────────────────────────────────────────
    def test_01_atr_zero_rejected(self):
        ok, reason = self.rm.process_signal("AAPL", 100.0, 0.0, "TECH")
        self.assertFalse(ok)
        self.assertEqual(reason, "ATR_INVALID")
        self.assertEqual(self.rm.cash, 500000.0)

    # ── 2 ──────────────────────────────────────────────────────────────────────
    def test_02_atr_nan_rejected(self):
        ok, reason = self.rm.process_signal("AAPL", 100.0, float('nan'), "TECH")
        self.assertFalse(ok)
        self.assertEqual(reason, "ATR_INVALID")
        self.assertEqual(self.rm.cash, 500000.0)

    # ── 3 ──────────────────────────────────────────────────────────────────────
    def test_03_risk_based_sizing(self):
        self.cfg.max_sector_exposure = 1.0

        rm_low = MockRiskManager(self.cfg, 500000.0)
        rm_low.on_timestamp(self.BASE_TS)
        rm_low.process_signal("LOW", 100.0, 1.0, "TECH")
        qty_low = rm_low.positions["LOW"].qty

        rm_high = MockRiskManager(self.cfg, 500000.0)
        rm_high.on_timestamp(self.BASE_TS)
        rm_high.process_signal("HIGH", 100.0, 10.0, "TECH")
        qty_high = rm_high.positions["HIGH"].qty

        self.assertGreater(qty_low, qty_high)
        self.assertEqual(qty_low, 2500)
        self.assertEqual(qty_high, 250)

    # ── 4 ──────────────────────────────────────────────────────────────────────
    def test_04_portfolio_exposure_limit(self):
        self.cfg.max_positions = 20
        self.cfg.max_sector_exposure = 1.0
        self.cfg.max_risk_per_trade = 0.15
        self.cfg.atr_initial_multiplier = 0.01

        rm = MockRiskManager(self.cfg, 500000.0)
        rm.on_timestamp(self.BASE_TS)
        for i in range(10):
            rm.process_signal(f"SYM_{i}", 100.0, 5.0, f"SEC_{i}")

        invested = rm.calc_total_invested_value()
        equity = rm.get_equity()
        self.assertLessEqual(invested, equity * self.cfg.max_portfolio_exposure + 1.0)

    # ── 5 ──────────────────────────────────────────────────────────────────────
    def test_05_sector_exposure_limit(self):
        self.cfg.max_positions = 20
        self.cfg.max_portfolio_exposure = 1.0
        self.cfg.max_risk_per_trade = 0.15
        self.cfg.atr_initial_multiplier = 0.01

        rm = MockRiskManager(self.cfg, 500000.0)
        rm.on_timestamp(self.BASE_TS)
        for i in range(10):
            rm.process_signal(f"BANK_{i}", 100.0, 5.0, "BANKING")

        sec_val = rm.calc_sector_exposure("BANKING")
        equity = rm.get_equity()
        self.assertLessEqual(sec_val, equity * self.cfg.max_sector_exposure + 1.0)

    # ── 6 ──────────────────────────────────────────────────────────────────────
    def test_06_daily_loss_lock_full_lifecycle(self):
        """
        Day 1: equity 500000, max_daily_loss 3% → threshold 485000.
        Open position → price drop → equity below 485000 → lock.
        updateRegime("NORMAL") → lock persists.
        Advance to next day → lock clears.
        """
        self.cfg.max_daily_loss = 0.03
        self.cfg.max_drawdown = 0.50       # don't trip drawdown
        self.cfg.max_sector_exposure = 1.0

        rm = MockRiskManager(self.cfg, 500000.0)
        rm.on_timestamp(self.BASE_TS)

        self.assertFalse(rm.daily_loss_locked)
        self.assertTrue(rm.entries_allowed())

        # Buy 1250 shares at Rs 100 (cost 125000, cash 375000)
        rm.process_signal("SYM", 100.0, 2.0, "TECH")
        self.assertAlmostEqual(rm.get_equity(), 500000.0, delta=1.0)

        # Price to 87 → equity = 375000 + 1250*87 = 483750 → loss 3.25%
        rm.update_positions("SYM", 87.0, 2.0)
        rm.evaluate_risk()

        self.assertTrue(rm.daily_loss_locked)
        self.assertFalse(rm.entries_allowed())

        # Rejected entry
        ok, reason = rm.process_signal("SYM2", 87.0, 2.0, "TECH")
        self.assertFalse(ok)
        self.assertEqual(reason, "DAILY_LOSS_LOCK")

        # NORMAL regime does NOT clear lock
        rm.update_regime("NORMAL")
        self.assertTrue(rm.daily_loss_locked)
        self.assertFalse(rm.entries_allowed())

        # Next day clears daily lock
        rm.on_timestamp(self.BASE_TS + 86400)
        self.assertFalse(rm.daily_loss_locked)

    # ── 7 ──────────────────────────────────────────────────────────────────────
    def test_07_drawdown_lock_full_lifecycle(self):
        """
        peak 500000, max_drawdown 10% → threshold 450000.
        Open position → price drop → equity < 450000 → permanent lock.
        NORMAL regime → lock persists.
        Next day → lock STILL persists.
        """
        self.cfg.max_drawdown = 0.10
        self.cfg.max_daily_loss = 0.50
        self.cfg.max_sector_exposure = 1.0
        self.cfg.max_portfolio_exposure = 1.0
        self.cfg.max_risk_per_trade = 0.10

        rm = MockRiskManager(self.cfg, 500000.0)
        rm.on_timestamp(self.BASE_TS)

        self.assertFalse(rm.drawdown_locked)

        # Buy: risk_amt = 50000, stop_dist = 4, qty = 12500
        # but capped by cash: qty = 5000, cost = 500000
        rm.process_signal("SYM", 100.0, 2.0, "TECH")
        self.assertAlmostEqual(rm.get_equity(), 500000.0, delta=1.0)

        # Price to 88 → equity = cash + 5000*88
        rm.update_positions("SYM", 88.0, 2.0)
        rm.evaluate_risk()

        self.assertTrue(rm.get_equity() < 450000.0)
        self.assertTrue(rm.drawdown_locked)
        self.assertFalse(rm.entries_allowed())

        # NORMAL regime must NOT clear
        rm.update_regime("NORMAL")
        self.assertTrue(rm.drawdown_locked)
        self.assertFalse(rm.entries_allowed())

        # Next day must NOT clear drawdown lock
        rm.on_timestamp(self.BASE_TS + 86400)
        self.assertTrue(rm.drawdown_locked)
        self.assertFalse(rm.entries_allowed())

    # ── 8 ──────────────────────────────────────────────────────────────────────
    def test_08_circuit_breakers_fire_on_signal_none(self):
        """
        Proves that the daily loss lock triggers via evaluate_risk()
        even when no BUY signal is processed.
        """
        self.cfg.max_daily_loss = 0.03
        self.cfg.max_drawdown = 0.50
        self.cfg.max_sector_exposure = 1.0

        rm = MockRiskManager(self.cfg, 500000.0)
        rm.on_timestamp(self.BASE_TS)

        rm.process_signal("SYM", 100.0, 2.0, "TECH")
        self.assertFalse(rm.daily_loss_locked)

        # Price drops to cause >3% loss
        rm.update_positions("SYM", 87.0, 2.0)

        # Call evaluate_risk — NOT process_signal.
        # In the old code, CBs were only inside process_signal(BUY),
        # so Signal::NONE would skip them.
        rm.evaluate_risk()

        self.assertTrue(rm.daily_loss_locked,
                        "evaluate_risk() must trigger daily loss lock "
                        "even when no BUY signal exists")
        self.assertFalse(rm.entries_allowed())

    # ── 9 ──────────────────────────────────────────────────────────────────────
    def test_09_equity_mark_to_market(self):
        """
        Buy → equity ≈ unchanged
        Price falls → equity decreases
        Price rises → equity increases
        cash ≠ equity while position open
        """
        self.cfg.max_sector_exposure = 1.0
        rm = MockRiskManager(self.cfg, 500000.0)
        rm.on_timestamp(self.BASE_TS)

        eq_init = rm.get_equity()
        self.assertEqual(eq_init, 500000.0)
        self.assertEqual(rm.cash, rm.get_equity())

        # qty = 2500 at 100, cost = 250000, cash = 250000
        rm.process_signal("SYM", 100.0, 2.0, "TECH")
        eq_buy = rm.get_equity()
        self.assertAlmostEqual(eq_buy, 500000.0, delta=1.0)
        self.assertLess(rm.cash, rm.get_equity())

        # Price to 97 (above initial stop of 96): position stays open
        # equity = 250000 + 2500*97 = 492500
        rm.update_positions("SYM", 97.0, 2.0)
        rm.evaluate_risk()
        eq_fall = rm.get_equity()
        self.assertLess(eq_fall, eq_buy)
        self.assertIn("SYM", rm.positions)  # Position must still be open
        self.assertNotEqual(rm.cash, rm.get_equity())  # cash != equity

        rm.update_positions("SYM", 105.0, 2.0)
        rm.evaluate_risk()
        eq_rise = rm.get_equity()
        self.assertGreater(eq_rise, eq_fall)

    # ── 10 ─────────────────────────────────────────────────────────────────────
    def test_10_peak_equity_tracking(self):
        """
        Initial peak = 500000.
        Position appreciates → peak updates.
        Position depreciates → peak stays.
        Drawdown from peak, not from initial capital.
        """
        self.cfg.max_drawdown = 0.10
        self.cfg.max_daily_loss = 0.50
        self.cfg.max_sector_exposure = 1.0
        self.cfg.max_portfolio_exposure = 1.0
        self.cfg.max_risk_per_trade = 0.10   # larger position

        rm = MockRiskManager(self.cfg, 500000.0)
        rm.on_timestamp(self.BASE_TS)

        self.assertAlmostEqual(rm.peak_equity, 500000.0)

        # qty = (500000*0.10)/(2*2) = 12500, but capped by cash: 500000/100 = 5000
        rm.process_signal("SYM", 100.0, 2.0, "TECH")
        qty = rm.positions["SYM"].qty
        cash_after = rm.cash

        # Price to 110: equity = cash_after + qty*110
        rm.update_positions("SYM", 110.0, 2.0)
        rm.evaluate_risk()
        expected_peak = cash_after + qty * 110.0
        self.assertAlmostEqual(rm.peak_equity, expected_peak, delta=1.0)
        self.assertGreater(rm.peak_equity, 500000.0)

        # Price to 99 (above stop=96): equity drops but still above 90% of peak
        rm.update_positions("SYM", 99.0, 2.0)
        rm.evaluate_risk()
        self.assertAlmostEqual(rm.peak_equity, expected_peak, delta=1.0)

        # Calculate whether drawdown threshold is reachable above the stop
        threshold_price = (0.90 * expected_peak - cash_after) / qty
        # If threshold_price > stop (96), we can trigger drawdown before stop
        if threshold_price > 96.0:
            trigger_price = threshold_price - 0.5
            rm.update_positions("SYM", trigger_price, 2.0)
            rm.evaluate_risk()
            self.assertTrue(rm.drawdown_locked,
                f"Drawdown from peak ({expected_peak}) should trigger at price {trigger_price}")
        else:
            # Position is too small — stop would fire first.
            # Verify drawdown IS tracked relative to peak (not initial capital)
            # by checking peak was correctly updated
            self.assertGreater(rm.peak_equity, 500000.0,
                "Peak equity must track the high water mark")

        self.assertAlmostEqual(rm.peak_equity, expected_peak, delta=1.0)

    # ── 11 ─────────────────────────────────────────────────────────────────────
    def test_11_evaluate_risk_idempotence(self):
        self.cfg.max_sector_exposure = 1.0
        rm = MockRiskManager(self.cfg, 500000.0)
        rm.on_timestamp(self.BASE_TS)

        rm.process_signal("SYM", 100.0, 2.0, "TECH")
        rm.update_positions("SYM", 95.0, 2.0)

        rm.evaluate_risk()
        eq1 = rm.get_equity()
        cash1 = rm.cash
        peak1 = rm.peak_equity
        daily1 = rm.daily_loss_locked
        dd1 = rm.drawdown_locked

        for _ in range(5):
            rm.evaluate_risk()

        self.assertEqual(rm.get_equity(), eq1)
        self.assertEqual(rm.cash, cash1)
        self.assertEqual(rm.peak_equity, peak1)
        self.assertEqual(rm.daily_loss_locked, daily1)
        self.assertEqual(rm.drawdown_locked, dd1)

    # ── 12 ─────────────────────────────────────────────────────────────────────
    def test_12_elevated_risk_blocks_entries_exits_continue(self):
        rm = MockRiskManager(self.cfg, 500000.0)
        rm.on_timestamp(self.BASE_TS)
        rm.process_signal("TEST", 100.0, 2.0, "TECH")
        self.assertIn("TEST", rm.positions)

        rm.update_regime("ELEVATED_RISK")
        self.assertFalse(rm.entries_allowed())

        ok, reason = rm.process_signal("TEST2", 100.0, 2.0, "TECH")
        self.assertFalse(ok)
        self.assertIn("MARKET_REGIME", reason)

        # initial stop = 100 - 4 = 96
        rm.update_positions("TEST", 95.0, 2.0)
        self.assertNotIn("TEST", rm.positions)

    # ── 13 ─────────────────────────────────────────────────────────────────────
    def test_13_equity_stable_after_buy(self):
        rm = MockRiskManager(self.cfg, 500000.0)
        rm.on_timestamp(self.BASE_TS)
        eq_before = rm.get_equity()
        rm.process_signal("TEST", 100.0, 2.0, "TECH")
        eq_after = rm.get_equity()
        self.assertAlmostEqual(eq_before, eq_after, delta=1.0)
        self.assertLess(rm.cash, 500000.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
