# Implementation Notes & Second-Pass Hardening Audit

## 1. Root Cause of Backtest Circuit Breaker Trips
During the previous backtest, the circuit breaker tripped on Day 2 and repeatedly thereafter:
* **The Root Bug:** The circuit breaker was evaluating `capital` (cash-in-hand), NOT `equity` (cash + open positions market value).
* When the strategy deployed ₹437,000 into initial positions, cash dropped from ₹500,000 to ~₹63,000.
* The system evaluated `if (cash <= peak_cash * 0.90)` and immediately concluded there was an 87% "drawdown", locking the circuit breaker.
* **The Fix:** We strictly separated `cash`, `positions`, and `equity = cash + sum(qty * current_price)`. Circuit breakers and daily loss limits now exclusively evaluate `equity`. Buying positions decreases cash and increases position market value while total equity remains approximately unchanged.

## 2. Daily Loss Limit — Actually Daily
* **Previous Flaw:** `daily_starting_capital` was initialized once at program startup and never reset.
* **The Fix:** Implemented `onTimestamp(unix_ts)`. It converts the market event timestamp into calendar date in `Asia/Kolkata` (UTC+5:30). When a new trading day is detected:
  * `daily_starting_equity` is captured from current equity.
  * `daily_loss_locked` is cleared.
  * The daily lock persists throughout that day regardless of market regime changes, and only clears on the next calendar trading day.

## 3. Separate Lock States
* **Previous Flaw:** A single boolean `trading_enabled` was used. Calling `updateRegime("NORMAL")` inadvertently cleared risk locks.
* **The Fix:** Independent state flags:
  ```
  entries_allowed = manual_enabled
                 && market_allows_entries
                 && !daily_loss_locked
                 && !drawdown_locked
  ```
  `updateRegime()` only alters `market_allows_entries`. It is structurally incapable of clearing `daily_loss_locked` or `drawdown_locked`.

## 4. Market Regime & ELEVATED_RISK
* Regimes: `LOW_RISK`, `NORMAL`, `ELEVATED_RISK`, `HIGH_RISK`, `MISSING_DATA`, `TRADING_DISABLED`.
* `LOW_RISK` and `NORMAL` allow new entries.
* `ELEVATED_RISK` disables new entries while allowing existing position exits to continue.
* `MISSING_DATA` fails closed. Never substitutes US VIX for India VIX.

## 5. Invalid ATR Fails Closed
* All synthetic fallbacks (`price * 0.01`) were removed from Python and C++.
* If ATR is missing, NaN, zero, or negative:
  * Python data feeder omits the ATR field or logs an alert.
  * C++ `RiskManager::processSignal()` rejects the trade with `ATR_INVALID`.

## 6. Sector and Portfolio Exposure
* Both are computed from **market value as a percentage of total portfolio equity**:
  * `sector_exposure = (existing_sector_mval + new_pos_val) / equity <= max_sector_exposure` (20%)
  * `portfolio_exposure = (total_invested_mval + new_pos_val) / equity <= max_portfolio_exposure` (50%)
* Positions track their `sector` label directly.
