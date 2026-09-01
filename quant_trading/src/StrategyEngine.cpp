#include "StrategyEngine.h"
#include <iostream>

StrategyEngine::StrategyEngine() {}

Signal StrategyEngine::processTick(const std::string& ticker, double price, long volume, long timestamp) {
    auto& tickerHistory = history[ticker];
    
    tickerHistory.push_back({price, volume, timestamp});
    
    if (tickerHistory.size() > WINDOW_SIZE) {
        tickerHistory.pop_front();
    }
    
    if (tickerHistory.size() == WINDOW_SIZE) {
        // Calculate unusual momentum: Price up + Volume up
        double firstPrice = tickerHistory.front().price;
        double currentPrice = tickerHistory.back().price;
        
        long sumVolume = 0;
        for(size_t i=0; i < WINDOW_SIZE - 1; ++i) {
            sumVolume += tickerHistory[i].volume;
        }
        double avgVolume = sumVolume / (double)(WINDOW_SIZE - 1);
        double currentVolume = tickerHistory.back().volume;
        
        // Avoid division by zero
        if (avgVolume == 0) avgVolume = 1;
        
        // Define momentum: Price increased by > 0.05% in this window AND Volume is 1.5x average
        double priceChange = (currentPrice - firstPrice) / firstPrice;
        
        if (priceChange > 0.0005 && currentVolume > (avgVolume * 1.5)) {
            std::cout << "[STRATEGY] UNUSUAL MOMENTUM DETECTED for " << ticker 
                      << " | Price Change: " << (priceChange * 100) << "%" 
                      << " | Vol Spike: " << (currentVolume / avgVolume) << "x" << std::endl;
            // Clear history so we don't spam buy signals
            tickerHistory.clear();
            return Signal::BUY;
        }
    }
    
    return Signal::NONE;
}
