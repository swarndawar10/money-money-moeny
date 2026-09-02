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
    long   volume;
    double atr;
    long   timestamp;
};

class StrategyEngine {
public:
    explicit StrategyEngine(const Config& cfg);

    // Returns BUY signal if momentum + volume criteria are met.
    // atr is passed through for reference; validation happens in RiskManager.
    // sector is passed through so it travels with the signal to the RiskManager.
    Signal processTick(const std::string& ticker,
                       double price,
                       long   volume,
                       double atr,
                       long   timestamp,
                       const std::string& sector);

private:
    Config config;
    std::unordered_map<std::string, std::deque<Tick>> history;
    static constexpr int WINDOW_SIZE = 5;
};

#endif
