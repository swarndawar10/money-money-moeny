#include "RiskManager.h"
#include <iostream>
#include <cmath>
#include <algorithm>
#include <iomanip>
#include <limits>
#include <stdexcept>

// ──────────────────────────────────────────────────────────────────────────────
// Helper: Convert Unix timestamp to YYYYMMDD in Asia/Kolkata (UTC+5:30)
// Uses the event timestamp, NOT the wall clock. This makes the daily-reset
// deterministic in backtests that replay historical data.
// ──────────────────────────────────────────────────────────────────────────────
int RiskManager::toKolkataDay(long unix_ts) {
    // Kolkata = UTC + 5h 30m = +19800 seconds
    long kolkata_ts = unix_ts + 19800;
    long days_since_epoch = kolkata_ts / 86400;
    // Convert days since epoch to YYYYMMDD using Gregorian calendar
    long z = days_since_epoch + 719468;
    long era = (z >= 0 ? z : z - 146096) / 146097;
    long doe = z - era * 146097;
    long yoe = (doe - doe/1460 + doe/36524 - doe/146096) / 365;
    long y = yoe + era * 400;
    long doy = doe - (365*yoe + yoe/4 - yoe/100);
    long mp = (5*doy + 2) / 153;
    long d = doy - (153*mp + 2)/5 + 1;
    long m = mp + (mp < 10 ? 3 : -9);
    y += (m <= 2 ? 1 : 0);
    return (int)(y * 10000 + m * 100 + d);
}

// ──────────────────────────────────────────────────────────────────────────────
// Constructor
// ──────────────────────────────────────────────────────────────────────────────
RiskManager::RiskManager(const Config& cfg, double initial_cap)
    : config(cfg),
      cash(initial_cap),
      initial_capital(initial_cap),
      peak_equity(initial_cap),
      daily_starting_equity(initial_cap),
      current_trading_day(-1),
      manual_enabled(true),
      market_allows_entries(true),
      daily_loss_locked(false),
      drawdown_locked(false),
      current_regime("NORMAL")
{}

// ──────────────────────────────────────────────────────────────────────────────
// Equity = cash + market value of every open position at its most recent price
// ──────────────────────────────────────────────────────────────────────────────
double RiskManager::getEquity() const {
    double mval = 0.0;
    for (const auto& kv : positions)
        mval += kv.second.qty * kv.second.currentPrice;
    return cash + mval;
}

double RiskManager::calcTotalInvestedValue() const {
    double mval = 0.0;
    for (const auto& kv : positions)
        mval += kv.second.qty * kv.second.currentPrice;
    return mval;
}

double RiskManager::calcSectorExposure(const std::string& sector) const {
    double mval = 0.0;
    for (const auto& kv : positions)
        if (kv.second.sector == sector)
            mval += kv.second.qty * kv.second.currentPrice;
    return mval;
}

// ──────────────────────────────────────────────────────────────────────────────
// entries_allowed = manual && market && !daily_loss_locked && !drawdown_locked
// ──────────────────────────────────────────────────────────────────────────────
bool RiskManager::entriesAllowed() const {
    return manual_enabled && market_allows_entries && !daily_loss_locked && !drawdown_locked;
}

// ──────────────────────────────────────────────────────────────────────────────
// Timestamp handling — daily reset logic.
// Called for EVERY incoming tick before anything else.
// ──────────────────────────────────────────────────────────────────────────────
void RiskManager::onTimestamp(long unix_ts) {
    int day = toKolkataDay(unix_ts);
    if (day != current_trading_day) {
        // New trading day: reset daily fields.
        // Note: drawdown_locked is intentionally NOT cleared here.
        double eq = getEquity();
        daily_starting_equity = eq;
        daily_loss_locked     = false;
        current_trading_day   = day;
        std::cout << "[RISK] New trading day: " << day
                  << " | Equity at open: " << std::fixed << std::setprecision(2) << eq << std::endl;
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// Circuit breakers — called AFTER positions are updated so equity is accurate.
// ──────────────────────────────────────────────────────────────────────────────
void RiskManager::evaluateCircuitBreakers(double equity) {
    // Update peak equity
    if (equity > peak_equity) peak_equity = equity;

    // Drawdown lock (permanent until restart)
    if (!drawdown_locked) {
        double dd = (peak_equity - equity) / peak_equity;
        if (dd >= config.max_drawdown) {
            drawdown_locked = true;
            std::cout << "[RISK] 🚨 DRAWDOWN CIRCUIT BREAKER TRIPPED!"
                      << " | Equity: " << equity
                      << " | Peak: " << peak_equity
                      << " | DD: " << std::setprecision(2) << (dd * 100) << "%"
                      << " | New entries PERMANENTLY DISABLED until restart." << std::endl;
        }
    }

    // Daily loss lock (clears at start of next trading day)
    if (!daily_loss_locked) {
        double daily_pct_loss = (daily_starting_equity - equity) / daily_starting_equity;
        if (daily_pct_loss >= config.max_daily_loss) {
            daily_loss_locked = true;
            std::cout << "[RISK] 🚨 DAILY LOSS LIMIT HIT!"
                      << " | Equity: " << equity
                      << " | Day start: " << daily_starting_equity
                      << " | Loss: " << std::setprecision(2) << (daily_pct_loss * 100) << "%"
                      << " | New entries DISABLED for today." << std::endl;
        }
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// Market regime update.
// LOW_RISK / NORMAL    → entries allowed
// ELEVATED_RISK and above → entries disabled; exits always continue.
// This NEVER touches daily_loss_locked or drawdown_locked.
// ──────────────────────────────────────────────────────────────────────────────
void RiskManager::updateRegime(const std::string& regime_status) {
    current_regime = regime_status;
    bool was_allowed = market_allows_entries;

    if (regime_status == "LOW_RISK" || regime_status == "NORMAL") {
        market_allows_entries = true;
    } else {
        // ELEVATED_RISK, HIGH_RISK, MISSING_DATA, TRADING_DISABLED all block entries
        market_allows_entries = false;
    }

    if (market_allows_entries != was_allowed) {
        std::cout << "[RISK] Regime changed to " << regime_status
                  << " | market_allows_entries=" << (market_allows_entries ? "true" : "false") << std::endl;
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// Update a position with the latest price and ATR.
// Fires the appropriate stop if triggered.
// Exits continue regardless of any lock flag.
// ──────────────────────────────────────────────────────────────────────────────
void RiskManager::updatePositions(const std::string& ticker, double currentPrice, double atr) {
    auto it = positions.find(ticker);
    if (it == positions.end()) return;

    Position& pos = it->second;
    pos.currentPrice = currentPrice; // always update for equity calculations

    if (currentPrice > pos.highestPrice)
        pos.highestPrice = currentPrice;

    // ATR validation for trailing stop: if ATR is invalid, we fall back to
    // using ONLY the initial stop (which was set at entry with a valid ATR).
    double effectiveStop = pos.initialStop;
    if (std::isfinite(atr) && atr > 0.0) {
        double trailingStop = pos.highestPrice - (atr * config.atr_trailing_multiplier);
        effectiveStop = std::max(pos.initialStop, trailingStop);
    }

    if (currentPrice <= effectiveStop) {
        std::string reason = (effectiveStop <= pos.initialStop + 1e-9) ? "INITIAL_STOP_HIT" : "TRAILING_STOP_HIT";
        double revenue = pos.qty * currentPrice;
        double pnl     = revenue - (pos.qty * pos.entryPrice);
        cash += revenue;

        std::cout << "[EXECUTION] <<< SELL " << ticker
                  << " @ " << currentPrice
                  << " | Stop: " << effectiveStop
                  << " | Reason: " << reason
                  << " | PnL: " << std::fixed << std::setprecision(2) << pnl << std::endl;
        positions.erase(it);
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// Process an entry signal.
// Sequence: validate ATR → check locks → check limits → size position → open.
// ──────────────────────────────────────────────────────────────────────────────
void RiskManager::processSignal(const std::string& ticker,
                                double currentPrice,
                                double atr,
                                const std::string& sector,
                                Signal sig)
{
    if (sig != Signal::BUY) return;

    // ── 1. ATR validation — fail closed ──────────────────────────────────────
    if (!std::isfinite(atr) || atr <= 0.0) {
        std::cout << "[RISK] REJECTED BUY " << ticker << " | Reason: ATR_INVALID (atr=" << atr << ")" << std::endl;
        return;
    }

    // ── 2. Already holding this ticker? ──────────────────────────────────────
    if (positions.count(ticker)) return;

    // ── 3. Evaluate circuit breakers AFTER positions are current ─────────────
    //    (Called before processSignal in main.cpp, but call again to be safe)
    double equity = getEquity();
    evaluateCircuitBreakers(equity);

    // ── 4. Check all entry locks ──────────────────────────────────────────────
    if (!entriesAllowed()) {
        std::string reason;
        if (drawdown_locked)      reason = "DRAWDOWN_LOCK";
        else if (daily_loss_locked) reason = "DAILY_LOSS_LOCK";
        else if (!market_allows_entries) reason = "MARKET_REGIME(" + current_regime + ")";
        else                       reason = "MANUAL_DISABLED";
        std::cout << "[RISK] REJECTED BUY " << ticker << " | Reason: " << reason << std::endl;
        return;
    }

    // ── 5. Max positions ──────────────────────────────────────────────────────
    if ((int)positions.size() >= config.max_positions) {
        std::cout << "[RISK] REJECTED BUY " << ticker << " | Reason: MAX_POSITIONS" << std::endl;
        return;
    }

    // ── 6. ATR-based stop distance and position sizing ────────────────────────
    double stop_distance = atr * config.atr_initial_multiplier;
    double risk_amount   = equity * config.max_risk_per_trade;
    long   qty           = static_cast<long>(std::floor(risk_amount / stop_distance));

    if (qty <= 0) {
        std::cout << "[RISK] REJECTED BUY " << ticker << " | Reason: ZERO_QTY (risk=" << risk_amount << ", stop_dist=" << stop_distance << ")" << std::endl;
        return;
    }

    double new_position_value = qty * currentPrice;

    // ── 7. Portfolio exposure — uses total invested market value ──────────────
    double invested = calcTotalInvestedValue();
    if ((invested + new_position_value) > equity * config.max_portfolio_exposure) {
        // Reduce qty to respect portfolio exposure
        double remaining_exposure = equity * config.max_portfolio_exposure - invested;
        if (remaining_exposure <= 0) {
            std::cout << "[RISK] REJECTED BUY " << ticker << " | Reason: MAX_PORTFOLIO_EXPOSURE" << std::endl;
            return;
        }
        qty = static_cast<long>(std::floor(remaining_exposure / currentPrice));
        new_position_value = qty * currentPrice;
        if (qty <= 0) {
            std::cout << "[RISK] REJECTED BUY " << ticker << " | Reason: MAX_PORTFOLIO_EXPOSURE (zero qty after cap)" << std::endl;
            return;
        }
    }

    // ── 8. Sector exposure — uses sector market value / equity ────────────────
    double sector_invested = calcSectorExposure(sector);
    if ((sector_invested + new_position_value) > equity * config.max_sector_exposure) {
        double remaining = equity * config.max_sector_exposure - sector_invested;
        if (remaining <= 0) {
            std::cout << "[RISK] REJECTED BUY " << ticker << " | Reason: MAX_SECTOR_EXPOSURE (sector=" << sector << ")" << std::endl;
            return;
        }
        qty = static_cast<long>(std::floor(remaining / currentPrice));
        new_position_value = qty * currentPrice;
        if (qty <= 0) {
            std::cout << "[RISK] REJECTED BUY " << ticker << " | Reason: MAX_SECTOR_EXPOSURE (zero qty after cap)" << std::endl;
            return;
        }
    }

    // ── 9. Sufficient cash? ───────────────────────────────────────────────────
    if (new_position_value > cash) {
        qty = static_cast<long>(std::floor(cash / currentPrice));
        new_position_value = qty * currentPrice;
        if (qty <= 0) {
            std::cout << "[RISK] REJECTED BUY " << ticker << " | Reason: INSUFFICIENT_CASH" << std::endl;
            return;
        }
    }

    // ── 10. Execute ───────────────────────────────────────────────────────────
    cash -= new_position_value;
    double initial_stop = currentPrice - stop_distance;
    positions[ticker] = {sector, currentPrice, currentPrice, currentPrice, qty, initial_stop};

    std::cout << "[RISK] BUY ACCEPTED " << ticker
              << " | Sector: " << sector
              << " | Qty: " << qty
              << " | Price: " << currentPrice
              << " | Stop: " << initial_stop
              << " | RiskAmt: " << std::fixed << std::setprecision(2) << (qty * stop_distance)
              << " | Equity: " << getEquity() << std::endl;
}
