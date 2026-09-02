"""
Deterministic Risk Manager Unit Tests (Python verification suite)
Validates all 11 core risk requirements:
 1. ATR = 0 / negative -> rejected (fail closed)
 2. ATR = NaN / infinite -> rejected
 3. Risk-based position sizing (higher ATR -> smaller quantity)
 4. Portfolio exposure limit (total invested market value / equity <= max_portfolio_exposure)
 5. Sector exposure limit (sector market value / equity <= max_sector_exposure)
 6. Daily loss lock triggers when loss >= max_daily_loss
 7. Daily loss lock persists on same day despite NORMAL regime
 8. Daily loss lock resets on next calendar day (Asia/Kolkata)
 9. Drawdown lock is permanent and NOT cleared by NORMAL regime
10. ELEVATED_RISK regime blocks new entries while exits continue
11. Equity accounting: purchasing a position decreases cash but equity stays unchanged
"""

import math
import unittest

class Config:
    def __init__(self):
        self.atr_initial_multiplier  = 2.0
        self.atr_trailing_multiplier = 2.5
        self.max_risk_per_trade      = 0.01  # 1%
        self.max_portfolio_exposure  = 0.50  # 50%
        self.max_sector_exposure     = 0.20  # 20%
        self.max_positions           = 5
        self.max_daily_loss          = 0.03  # 3%
        self.max_drawdown            = 0.10  # 10%
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
    def __init__(self, config, initial_capital=500000.0):
        self.config = config
        self.cash = initial_capital
        self.initial_capital = initial_capital
        self.peak_equity = initial_capital
        self.daily_starting_equity = initial_capital
        self.current_trading_day = -1
        
        self.positions = {}  # ticker -> Position
        
        # Separate lock flags
        self.manual_enabled = True
        self.market_allows_entries = True
        self.daily_loss_locked = False
        self.drawdown_locked = False
        self.current_regime = "NORMAL"

    def get_equity(self):
        mval = sum(pos.qty * pos.current_price for pos in self.positions.values())
        return self.cash + mval

    def calc_total_invested_value(self):
        return sum(pos.qty * pos.current_price for pos in self.positions.values())

    def calc_sector_exposure(self, sector):
        return sum(pos.qty * pos.current_price for pos in self.positions.values() if pos.sector == sector)

    def entries_allowed(self):
        return (self.manual_enabled and 
                self.market_allows_entries and 
                not self.daily_loss_locked and 
                not self.drawdown_locked)

    @staticmethod
    def to_kolkata_day(unix_ts):
        kolkata_ts = unix_ts + 19800  # +5:30
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

    def evaluate_circuit_breakers(self):
        equity = self.get_equity()
        if equity > self.peak_equity:
            self.peak_equity = equity

        if not self.drawdown_locked:
            dd = (self.peak_equity - equity) / self.peak_equity if self.peak_equity > 0 else 0
            if dd >= self.config.max_drawdown:
                self.drawdown_locked = True

        if not self.daily_loss_locked:
            loss = (self.daily_starting_equity - equity) / self.daily_starting_equity if self.daily_starting_equity > 0 else 0
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
            trailing_stop = pos.highest_price - (atr * self.config.atr_trailing_multiplier)
            effective_stop = max(pos.initial_stop, trailing_stop)

        if current_price <= effective_stop:
            revenue = pos.qty * current_price
            self.cash += revenue
            del self.positions[ticker]

        self.evaluate_circuit_breakers()

    def process_signal(self, ticker, current_price, atr, sector, sig="BUY"):
        if sig != "BUY":
            return False, "NOT_BUY"

        if atr is None or not math.isfinite(atr) or atr <= 0:
            return False, "ATR_INVALID"

        if ticker in self.positions:
            return False, "ALREADY_HELD"

        self.evaluate_circuit_breakers()

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

        # Portfolio exposure
        invested = self.calc_total_invested_value()
        if (invested + new_val) > equity * self.config.max_portfolio_exposure:
            rem = equity * self.config.max_portfolio_exposure - invested
            if rem <= 0:
                return False, "MAX_PORTFOLIO_EXPOSURE"
            qty = int(rem // current_price)
            new_val = qty * current_price
            if qty <= 0:
                return False, "MAX_PORTFOLIO_EXPOSURE"

        # Sector exposure
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


class TestRiskControls(unittest.TestCase):
    BASE_TS = 1546300800  # 2019-01-01 00:00:00 UTC = 2019-01-01 05:30:00 IST

    def setUp(self):
        self.cfg = Config()
        self.cfg.validate()
        self.rm = MockRiskManager(self.cfg, 500000.0)
        self.rm.on_timestamp(self.BASE_TS)

    def test_1_atr_zero_rejected(self):
        ok, reason = self.rm.process_signal("AAPL", 100.0, 0.0, "TECH")
        self.assertFalse(ok)
        self.assertEqual(reason, "ATR_INVALID")
        self.assertEqual(self.rm.cash, 500000.0)

    def test_2_atr_nan_rejected(self):
        ok, reason = self.rm.process_signal("AAPL", 100.0, float('nan'), "TECH")
        self.assertFalse(ok)
        self.assertEqual(reason, "ATR_INVALID")
        self.assertEqual(self.rm.cash, 500000.0)

    def test_3_risk_based_sizing(self):
        # Allow sufficient sector exposure so risk sizing determines quantity
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
        self.assertEqual(qty_low, 2500)   # 5000 / (1 * 2) = 2500
        self.assertEqual(qty_high, 250)   # 5000 / (10 * 2) = 250

    def test_4_portfolio_exposure_limit(self):
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

    def test_5_sector_exposure_limit(self):
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

    def test_6_daily_loss_lock(self):
        self.cfg.max_daily_loss = 0.02  # 2% loss threshold = 10,000 on 500,000
        rm = MockRiskManager(self.cfg, 500000.0)
        rm.on_timestamp(self.BASE_TS)

        rm.process_signal("TEST", 100.0, 2.0, "TECH")
        # Entry qty is 1000 (capped by 20% sector exposure on 500k = 100k / 100)
        # Drop price to 85.0 (loss of 15 * 1000 = 15,000 > 10,000)
        # Position exits via stop, returning cash = 85,000, equity = 485,000 (-3%)
        rm.update_positions("TEST", 85.0, 2.0)
        self.assertTrue(rm.daily_loss_locked)

        ok, reason = rm.process_signal("TEST2", 85.0, 2.0, "TECH")
        self.assertFalse(ok)
        self.assertEqual(reason, "DAILY_LOSS_LOCK")

    def test_7_daily_lock_persists_same_day_despite_normal_regime(self):
        self.cfg.max_daily_loss = 0.02
        rm = MockRiskManager(self.cfg, 500000.0)
        rm.on_timestamp(self.BASE_TS)

        rm.process_signal("TEST", 100.0, 2.0, "TECH")
        rm.update_positions("TEST", 85.0, 2.0)
        self.assertTrue(rm.daily_loss_locked)

        # Updating to NORMAL must NOT clear daily_loss_locked
        rm.update_regime("NORMAL")
        self.assertTrue(rm.daily_loss_locked)

        ok, reason = rm.process_signal("TEST2", 100.0, 2.0, "TECH")
        self.assertFalse(ok)
        self.assertEqual(reason, "DAILY_LOSS_LOCK")

    def test_8_daily_lock_clears_next_day(self):
        self.cfg.max_daily_loss = 0.02
        rm = MockRiskManager(self.cfg, 500000.0)
        rm.on_timestamp(self.BASE_TS)

        rm.process_signal("TEST", 100.0, 2.0, "TECH")
        rm.update_positions("TEST", 85.0, 2.0)
        self.assertTrue(rm.daily_loss_locked)

        # Advance timestamp to next trading day (+86400 seconds)
        rm.on_timestamp(self.BASE_TS + 86400)
        self.assertFalse(rm.daily_loss_locked)

    def test_9_drawdown_lock_persists_despite_normal_regime(self):
        self.cfg.max_drawdown = 0.02  # 2% drawdown threshold
        rm = MockRiskManager(self.cfg, 500000.0)
        rm.on_timestamp(self.BASE_TS)

        rm.process_signal("TEST", 100.0, 2.0, "TECH")
        # Drop price to cause > 2% drawdown (15,000 loss)
        rm.update_positions("TEST", 85.0, 2.0)
        self.assertTrue(rm.drawdown_locked)

        # Regime update to NORMAL must NOT clear drawdown lock
        rm.update_regime("NORMAL")
        self.assertTrue(rm.drawdown_locked)

        ok, reason = rm.process_signal("TEST2", 100.0, 2.0, "TECH")
        self.assertFalse(ok)
        self.assertEqual(reason, "DRAWDOWN_LOCK")

    def test_10_elevated_risk_blocks_entries_but_exits_continue(self):
        rm = MockRiskManager(self.cfg, 500000.0)
        rm.on_timestamp(self.BASE_TS)
        rm.process_signal("TEST", 100.0, 2.0, "TECH")
        self.assertIn("TEST", rm.positions)

        # Switch to ELEVATED_RISK
        rm.update_regime("ELEVATED_RISK")
        self.assertFalse(rm.entries_allowed())

        # New entries must be rejected
        ok, reason = rm.process_signal("TEST2", 100.0, 2.0, "TECH")
        self.assertFalse(ok)
        self.assertIn("MARKET_REGIME", reason)

        # Existing position exits must still execute
        # initial stop = 100 - (2 * 2) = 96.0
        rm.update_positions("TEST", 95.0, 2.0)
        self.assertNotIn("TEST", rm.positions)  # Position was exited!

    def test_11_equity_unchanged_after_buy(self):
        rm = MockRiskManager(self.cfg, 500000.0)
        rm.on_timestamp(self.BASE_TS)
        eq_before = rm.get_equity()
        self.assertEqual(eq_before, 500000.0)

        rm.process_signal("TEST", 100.0, 2.0, "TECH")
        eq_after = rm.get_equity()
        self.assertAlmostEqual(eq_before, eq_after, delta=1.0)
        self.assertLess(rm.cash, 500000.0)  # Cash decreased


if __name__ == "__main__":
    unittest.main(verbosity=2)
