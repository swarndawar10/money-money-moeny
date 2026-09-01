#ifndef RISK_MANAGER_H
#define RISK_MANAGER_H

#include <string>
#include <unordered_map>
#include "StrategyEngine.h"
#include "Config.h"

struct Position {
    double entryPrice;
    double highestPrice;
    long qty;
    double initialStop;
};

class RiskManager {
public:
    RiskManager(const Config& cfg, double initial_capital);
    
    // Updates master kill switches based on portfolio value and market regime
    void updateRegime(const std::string& regime_status);
    
    // Process new buy signals
    void processSignal(const std::string& ticker, double currentPrice, double atr, Signal sig);
    
    // Monitor and exit existing positions
    void updatePositions(const std::string& ticker, double currentPrice, double atr);
    
    double getCapital() const { return capital; }

private:
    Config config;
    std::unordered_map<std::string, Position> positions;
    
    double initial_capital;
    double capital;
    double peak_capital;
    double daily_starting_capital;
    
    bool trading_enabled;
    std::string current_regime;
    
    void enforceCircuitBreakers();
};

#endif
