# Risk Architecture & Model Documentation (Hardened v2)

This document describes the complete risk-control hierarchy implemented in the Quantitative Trading Engine. The foundational principle is:

$$\text{Capital Protection} > \text{Avoiding Bad Trades} > \text{Taking Good Trades} > \text{Profit Maximization}$$

---

## 1. Risk Control Hierarchy

Every trade decision passes through a multi-stage deterministic hierarchy where the `RiskManager` retains absolute authority:

```
Market Data (Tick)
      ↓
Clock / Timestamp (Asia/Kolkata Day Detection)
      ↓
Position Pricing & Exits (Initial / Trailing Stops)
      ↓
Equity Recalculation (Cash + Open Position Market Values)
      ↓
Peak & Daily Loss Circuit Breakers
      ↓
Market Regime Filter (India VIX + Nifty 50 Trend)
      ↓
Strategy Signal Evaluation (Momentum + Volume Confirmation)
      ↓
RiskManager Entry Approval:
  ├── Check Separate Lock Flags
  ├── Check Max Positions
  ├── Check ATR Validity (Fail-Closed)
  ├── Position Sizing (Risk / Stop Distance)
  ├── Portfolio Exposure Cap (Invested MVal / Equity <= 50%)
  └── Sector Exposure Cap (Sector MVal / Equity <= 20%)
      ↓
Order Execution & Cash Accounting
```

---

## 2. Equity & Drawdown Accounting

### Equity Definition
$$\text{Equity} = \text{Cash} + \sum_{i \in \text{positions}} (\text{Quantity}_i \times \text{Current Price}_i)$$

* Purchasing a stock reduces Cash and increases Position Market Value; **Equity remains unchanged**.
* Comparing cash against peak cash is invalid. All drawdown and risk calculations exclusively use **Equity**.

### Maximum Drawdown Circuit Breaker
$$\text{Drawdown} = \frac{\text{Peak Equity} - \text{Current Equity}}{\text{Peak Equity}}$$

* If $\text{Drawdown} \ge \text{max\_drawdown}$ (default 10%), `drawdown_locked = true`.
* **Lock Persistence:** This lock is permanent and **cannot** be cleared by a market regime update.

---

## 3. Daily Loss Limit & Session Reset

### Daily Loss Definition
$$\text{Daily Loss} = \frac{\text{Daily Starting Equity} - \text{Current Equity}}{\text{Daily Starting Equity}}$$

* If $\text{Daily Loss} \ge \text{max\_daily\_loss}$ (default 3%), `daily_loss_locked = true`.
* **Session Reset:** Driven by the event timestamp in `Asia/Kolkata` (UTC+5:30). When a new calendar day arrives:
  $$\text{daily\_starting\_equity} \leftarrow \text{current\_equity}, \quad \text{daily\_loss\_locked} \leftarrow \text{false}$$
* A change in market regime to `NORMAL` will **never** clear `daily_loss_locked` within the same day.

---

## 4. Market Regime States

| Regime | Condition | Entry Permission | Open Position Exits |
| :--- | :--- | :--- | :--- |
| `LOW_RISK` | VIX low, Nifty > EMA20 | **Allowed** | Monitored |
| `NORMAL` | VIX normal, Nifty > EMA20 | **Allowed** | Monitored |
| `ELEVATED_RISK` | VIX approaching limit OR Nifty < EMA20 | **Disabled** | Monitored |
| `HIGH_RISK` | VIX $\ge$ threshold (22.0) | **Disabled** | Monitored |
| `MISSING_DATA` | VIX or Nifty fetch failure | **Disabled** (Fail Closed) | Monitored |
| `TRADING_DISABLED` | Manual kill switch | **Disabled** | Monitored |

---

## 5. Volatility Stops & Dynamic Position Sizing

### Fail-Closed ATR
* If ATR $\le 0$, NaN, infinite, or missing: **Trade Rejected (`ATR_INVALID`)**. No synthetic fallback values (`price * 0.01`) are permitted.

### Stop Distance & Sizing
$$\text{Stop Distance} = \text{ATR} \times \text{atr\_initial\_multiplier} \quad (\text{default } 2.0)$$
$$\text{Risk Amount} = \text{Equity} \times \text{max\_risk\_per\_trade} \quad (\text{default } 1\%)$$
$$\text{Quantity} = \left\lfloor \frac{\text{Risk Amount}}{\text{Stop Distance}} \right\rfloor$$

### Trailing Stop
$$\text{Trailing Stop} = \text{Highest Price Since Entry} - (\text{ATR} \times \text{atr\_trailing\_multiplier}) \quad (\text{default } 2.5)$$
$$\text{Effective Stop} = \max(\text{Initial Stop}, \text{Trailing Stop})$$

---

## 6. Exposure Controls

* **Portfolio Exposure:** $\frac{\sum \text{Position Market Values} + \text{New Position Value}}{\text{Equity}} \le \text{max\_portfolio\_exposure} \quad (\text{default } 50\%)$
* **Sector Exposure:** $\frac{\sum_{\text{sector}} \text{Position Market Values} + \text{New Position Value}}{\text{Equity}} \le \text{max\_sector\_exposure} \quad (\text{default } 20\%)$
* If a new order would breach an exposure cap, the quantity is automatically scaled down to fit within the remaining allowance. If the scaled quantity is 0, the trade is rejected.
