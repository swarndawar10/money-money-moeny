#ifndef RISK_MANAGER_H
#define RISK_MANAGER_H

#include <string>
#include <unordered_map>
#include "StrategyEngine.h"

struct Position {
    double entryPrice;
    double highestPrice;
};

class RiskManager {
public:
    RiskManager(double stopLossPercent);
    void processSignal(const std::string& ticker, double currentPrice, Signal sig);
    void updatePositions(const std::string& ticker, double currentPrice);

private:
    double stopLossPercent;
    std::unordered_map<std::string, Position> positions;
};

#endif
