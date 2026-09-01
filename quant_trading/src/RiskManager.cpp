#include "RiskManager.h"
#include <iostream>
#include <cmath>
#include <algorithm>
#include <iomanip>

RiskManager::RiskManager(const Config& cfg, double initial_cap) 
    : config(cfg), initial_capital(initial_cap), capital(initial_cap), 
      peak_capital(initial_cap), daily_starting_capital(initial_cap),
      trading_enabled(true), current_regime("NORMAL") {}

void RiskManager::enforceCircuitBreakers() {
    // Max Drawdown Circuit Breaker
    if (capital <= peak_capital * (1.0 - config.max_drawdown)) {
        if (trading_enabled) {
            std::cout << "[RISK] 🚨 CIRCUIT BREAKER TRIPPED! Max drawdown exceeded. TRADING DISABLED." << std::endl;
            trading_enabled = false;
        }
    }
    
    // Daily Loss Limit
    if (capital <= daily_starting_capital * (1.0 - config.max_daily_loss)) {
        if (trading_enabled) {
            std::cout << "[RISK] 🚨 DAILY LOSS LIMIT HIT! TRADING DISABLED FOR NEW ENTRIES." << std::endl;
            trading_enabled = false;
        }
    }
}

void RiskManager::updateRegime(const std::string& regime_status) {
    current_regime = regime_status;
    if (current_regime == "HIGH_RISK" || current_regime == "TRADING_DISABLED" || current_regime == "MISSING_DATA") {
        if (trading_enabled) {
            std::cout << "[RISK] 🚨 Market Regime is " << current_regime << ". TRADING DISABLED." << std::endl;
            trading_enabled = false;
        }
    } else {
        // Only re-enable if circuit breakers aren't tripped
        if (capital > peak_capital * (1.0 - config.max_drawdown) && 
            capital > daily_starting_capital * (1.0 - config.max_daily_loss)) {
            trading_enabled = true;
        }
    }
}

void RiskManager::processSignal(const std::string& ticker, double currentPrice, double atr, Signal sig) {
    enforceCircuitBreakers();
    
    if (sig == Signal::BUY) {
        if (!trading_enabled) {
            std::cout << "[RISK] REJECTED BUY " << ticker << " | Reason: TRADING_DISABLED (" << current_regime << ")" << std::endl;
            return;
        }
        
        if (positions.find(ticker) != positions.end()) {
            return; // Already holding
        }
        
        if (positions.size() >= config.max_positions) {
            std::cout << "[RISK] REJECTED BUY " << ticker << " | Reason: MAX_POSITIONS_REACHED" << std::endl;
            return;
        }
        
        // Volatility-aware Stop Distance
        double stop_distance = atr * config.atr_initial_multiplier;
        if (stop_distance <= 0) stop_distance = 0.01 * currentPrice; // Fallback
        
        double risk_amount = capital * config.max_risk_per_trade;
        long qty = std::floor(risk_amount / stop_distance);
        
        if (qty <= 0) {
            std::cout << "[RISK] REJECTED BUY " << ticker << " | Reason: INSUFFICIENT_RISK_CAPITAL" << std::endl;
            return;
        }
        
        double cost = qty * currentPrice;
        if (cost > capital * config.max_portfolio_exposure) {
            // Cap by portfolio exposure limit
            qty = std::floor((capital * config.max_portfolio_exposure) / currentPrice);
            cost = qty * currentPrice;
        }
        
        if (cost > capital) {
            qty = std::floor(capital / currentPrice);
            cost = qty * currentPrice;
        }
        
        if (qty > 0) {
            capital -= cost;
            double initial_stop = currentPrice - stop_distance;
            positions[ticker] = {currentPrice, currentPrice, qty, initial_stop};
            std::cout << "[EXECUTION] >>> BUY " << ticker << " | Qty: " << qty 
                      << " | Price: " << currentPrice << " | Risk Amount: " << (qty * stop_distance)
                      << " | Initial Stop: " << initial_stop << std::endl;
        } else {
             std::cout << "[RISK] REJECTED BUY " << ticker << " | Reason: INSUFFICIENT_CASH" << std::endl;
        }
    }
}

void RiskManager::updatePositions(const std::string& ticker, double currentPrice, double atr) {
    auto it = positions.find(ticker);
    if (it != positions.end()) {
        Position& pos = it->second;
        
        if (currentPrice > pos.highestPrice) {
            pos.highestPrice = currentPrice;
        }
        
        // Dynamic Trailing Stop
        double trailingStop = pos.highestPrice - (atr * config.atr_trailing_multiplier);
        double effectiveStop = std::max(pos.initialStop, trailingStop);
        
        std::string exit_reason = "";
        if (currentPrice <= effectiveStop) {
            if (effectiveStop == pos.initialStop) {
                exit_reason = "INITIAL_STOP_HIT";
            } else {
                exit_reason = "TRAILING_STOP_HIT";
            }
        }
        
        if (!exit_reason.empty()) {
            double revenue = pos.qty * currentPrice;
            capital += revenue;
            if (capital > peak_capital) peak_capital = capital;
            
            std::cout << "[EXECUTION] <<< SELL " << ticker << " @ " << currentPrice 
                      << " | Reason: " << exit_reason 
                      << " | PnL: " << std::fixed << std::setprecision(2) << (revenue - (pos.qty * pos.entryPrice)) << std::endl;
            positions.erase(it);
        }
    }
}
