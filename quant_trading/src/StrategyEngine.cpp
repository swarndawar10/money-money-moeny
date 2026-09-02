#include "StrategyEngine.h"
#include <iostream>

StrategyEngine::StrategyEngine(const Config& cfg) : config(cfg) {}

Signal StrategyEngine::processTick(const std::string& ticker,
                                   double price,
                                   long   volume,
                                   double atr,
                                   long   timestamp,
                                   const std::string& /*sector*/)
{
    auto& tickerHistory = history[ticker];

    tickerHistory.push_back({price, volume, atr, timestamp});
    if (tickerHistory.size() > WINDOW_SIZE)
        tickerHistory.pop_front();

    if (tickerHistory.size() == WINDOW_SIZE) {
        double firstPrice   = tickerHistory.front().price;
        double currentPrice = tickerHistory.back().price;

        // Compute average volume over the WINDOW_SIZE-1 preceding bars (not the current one)
        long sumVolume = 0;
        for (size_t i = 0; i < WINDOW_SIZE - 1; ++i)
            sumVolume += tickerHistory[i].volume;
        double avgVolume    = (double)sumVolume / (WINDOW_SIZE - 1);
        double currentVolume = tickerHistory.back().volume;

        if (avgVolume <= 0) avgVolume = 1.0;

        double priceChange = (currentPrice - firstPrice) / firstPrice;

        // Signals only use information in the historical window — no future bars.
        if (priceChange > config.momentum_threshold &&
            currentVolume > (avgVolume * config.volume_multiplier))
        {
            std::cout << "[STRATEGY] BUY SIGNAL: " << ticker
                      << " | PxChg: " << (priceChange * 100) << "%"
                      << " | VolSpike: " << (currentVolume / avgVolume) << "x"
                      << std::endl;
            // History is NOT cleared here; RiskManager handles position de-duplication.
            return Signal::BUY;
        }
    }

    return Signal::NONE;
}
