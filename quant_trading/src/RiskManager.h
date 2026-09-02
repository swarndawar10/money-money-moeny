#ifndef RISK_MANAGER_H
#define RISK_MANAGER_H

#include <string>
#include <unordered_map>
#include <cstdint>
#include "StrategyEngine.h"
#include "Config.h"

// ──────────────────────────────────────────────────────────────────────────────
// Position record
// ──────────────────────────────────────────────────────────────────────────────
struct Position {
    std::string sector;       // sector label passed with the BUY tick
    double entryPrice;
    double highestPrice;      // tracks the highest close since entry
    double currentPrice;      // most recently seen price (for equity calc)
    long   qty;
    double initialStop;       // entry_price - ATR * atr_initial_multiplier
};

// ──────────────────────────────────────────────────────────────────────────────
// RiskManager
//
// Separate state flags prevent a regime update from clearing a risk lock.
//
//  entries_allowed = manual_enabled
//                 && market_allows_entries
//                 && !daily_loss_locked
//                 && !drawdown_locked
// ──────────────────────────────────────────────────────────────────────────────
class RiskManager {
public:
    RiskManager(const Config& cfg, double initial_capital);

    // ── Timestamp ─────────────────────────────────────────────────────────────
    // Must be called with the Unix timestamp (seconds, Asia/Kolkata is UTC+5:30)
    // for EVERY incoming tick. Handles daily reset internally.
    void onTimestamp(long unix_ts);

    // ── Market regime ─────────────────────────────────────────────────────────
    // LOW_RISK / NORMAL    → entries allowed
    // ELEVATED_RISK        → new entries disabled; exits continue
    // HIGH_RISK / MISSING_DATA / TRADING_DISABLED → entries disabled; exits continue
    // This call NEVER clears daily_loss_locked or drawdown_locked.
    void updateRegime(const std::string& regime_status);

    // ── Position management ───────────────────────────────────────────────────
    // Update an open position with the latest price/ATR. Fires exit if stop hit.
    void updatePositions(const std::string& ticker, double currentPrice, double atr);

    // ── Risk state evaluation ─────────────────────────────────────────────────
    // Must be called on EVERY tick, regardless of whether a strategy signal
    // exists. Calculates current equity, updates peak equity, and evaluates
    // drawdown and daily-loss circuit breakers.
    // Idempotent: calling multiple times with no state change is safe.
    void evaluateRisk();

    // ── Entry signal ──────────────────────────────────────────────────────────
    // Called AFTER updatePositions and evaluateRisk for the same tick.
    // atr == 0 or NaN → rejected with ATR_INVALID.
    void processSignal(const std::string& ticker,
                       double currentPrice,
                       double atr,
                       const std::string& sector,
                       Signal sig);

    // ── Read-only accessors ───────────────────────────────────────────────────
    double getCash()       const { return cash; }
    double getEquity()     const;  // cash + sum(qty * currentPrice)
    double getPeakEquity() const { return peak_equity; }
    bool isDailyLossLocked() const { return daily_loss_locked; }
    bool isDrawdownLocked()  const { return drawdown_locked; }
    bool areEntriesAllowed() const { return entriesAllowed(); }

private:
    Config config;

    // ── Account state ─────────────────────────────────────────────────────────
    std::unordered_map<std::string, Position> positions;
    double cash;
    double initial_capital;
    double peak_equity;           // highest equity observed so far
    double daily_starting_equity; // equity at start of today's session
    int    current_trading_day;   // YYYYMMDD integer in Asia/Kolkata

    // ── Separate lock flags ───────────────────────────────────────────────────
    bool manual_enabled;          // hard kill-switch (default true)
    bool market_allows_entries;   // set by updateRegime
    bool daily_loss_locked;       // set when daily loss limit exceeded; cleared at new day
    bool drawdown_locked;         // set when peak drawdown exceeded; never auto-cleared

    std::string current_regime;

    // ── Internal helpers ──────────────────────────────────────────────────────
    bool entriesAllowed() const;
    void evaluateCircuitBreakers(double equity);
    double calcSectorExposure(const std::string& sector) const;
    double calcTotalInvestedValue() const;

    // Convert Unix timestamp to YYYYMMDD integer in Asia/Kolkata (UTC+5:30)
    static int toKolkataDay(long unix_ts);
};

#endif
