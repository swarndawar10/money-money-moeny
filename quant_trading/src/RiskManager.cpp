#include "RiskManager.h"
#include <iostream>

RiskManager::RiskManager(double slPercent) : stopLossPercent(slPercent / 100.0) {}

void RiskManager::processSignal(const std::string& ticker, double currentPrice, Signal sig) {
    if (sig == Signal::BUY) {
        if (positions.find(ticker) == positions.end()) {
            std::cout << "[EXECUTION] >>> BUY " << ticker << " @ " << currentPrice << std::endl;
            positions[ticker] = {currentPrice, currentPrice};
        }
    }
}

void RiskManager::updatePositions(const std::string& ticker, double currentPrice) {
    auto it = positions.find(ticker);
    if (it != positions.end()) {
        Position& pos = it->second;
        
        // Update highest price for trailing stop
        if (currentPrice > pos.highestPrice) {
            pos.highestPrice = currentPrice;
        }
        
        // 1. Hard Stop Loss (1%) from entry price
        double hardStopPrice = pos.entryPrice * (1.0 - stopLossPercent);
        if (currentPrice <= hardStopPrice) {
            std::cout << "[EXECUTION] <<< HARD STOP LOSS HIT! SELL " << ticker << " @ " << currentPrice << " (Entry: " << pos.entryPrice << ")" << std::endl;
            positions.erase(it);
            return;
        }
        
        // 2. Trailing Stop (Momentum loss) - Sells if it ticks down from highest price
        // This exactly matches the condition: "second the stock goes down program sells it"
        if (currentPrice < pos.highestPrice) {
            std::cout << "[EXECUTION] <<< MOMENTUM REVERSAL! SELL " << ticker << " @ " << currentPrice << " (Highest: " << pos.highestPrice << ")" << std::endl;
            positions.erase(it);
            return;
        }
    }
}
