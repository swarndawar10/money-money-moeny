#include "StrategyEngine.h"
#include <iostream>

StrategyEngine::StrategyEngine(const Config& cfg) : config(cfg) {}

Signal StrategyEngine::processTick(const std::string& ticker, double price, long volume, double atr, long timestamp) {
    auto& tickerHistory = history[ticker];
    
    tickerHistory.push_back({price, volume, atr, timestamp});
    
    if (tickerHistory.size() > WINDOW_SIZE) {
        tickerHistory.pop_front();
    }
    
    if (tickerHistory.size() == WINDOW_SIZE) {
        double firstPrice = tickerHistory.front().price;
        double currentPrice = tickerHistory.back().price;
        
        long sumVolume = 0;
        for(size_t i = 0; i < WINDOW_SIZE - 1; ++i) {
            sumVolume += tickerHistory[i].volume;
        }
        double avgVolume = sumVolume / (double)(WINDOW_SIZE - 1);
        double currentVolume = tickerHistory.back().volume;
        
        if (avgVolume == 0) avgVolume = 1;
        
        double priceChange = (currentPrice - firstPrice) / firstPrice;
        
        // Ensure NO future info used: calculation strictly on historical window
        if (priceChange > config.momentum_threshold && currentVolume > (avgVolume * config.volume_multiplier)) {
            std::cout << "[STRATEGY] BUY SIGNAL GENERATED: " << ticker 
                      << " | Px Chg: " << (priceChange * 100) << "%" 
                      << " | Vol Spike: " << (currentVolume / avgVolume) << "x" << std::endl;
            
            // Note: Responsibility for position limits and checking if we already own it 
            // is shifted to RiskManager. We do NOT clear tickerHistory here anymore.
            return Signal::BUY;
        }
    }
    
    return Signal::NONE;
}
