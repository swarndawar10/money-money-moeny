#ifndef STRATEGY_ENGINE_H
#define STRATEGY_ENGINE_H

#include <string>
#include <unordered_map>
#include <deque>
#include "Config.h"

enum class Signal {
    NONE,
    BUY,
    SELL
};

struct Tick {
    double price;
    long volume;
    double atr;
    long timestamp;
};

class StrategyEngine {
public:
    StrategyEngine(const Config& cfg);
    Signal processTick(const std::string& ticker, double price, long volume, double atr, long timestamp);

private:
    Config config;
    std::unordered_map<std::string, std::deque<Tick>> history;
    const int WINDOW_SIZE = 5; // Lookback period for momentum
};

#endif
