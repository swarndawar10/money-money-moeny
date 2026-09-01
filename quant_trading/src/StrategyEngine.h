#ifndef STRATEGY_ENGINE_H
#define STRATEGY_ENGINE_H

#include <string>
#include <unordered_map>
#include <deque>

enum class Signal {
    NONE,
    BUY,
    SELL
};

struct Tick {
    double price;
    long volume;
    long timestamp;
};

class StrategyEngine {
public:
    StrategyEngine();
    Signal processTick(const std::string& ticker, double price, long volume, long timestamp);

private:
    std::unordered_map<std::string, std::deque<Tick>> history;
    const int WINDOW_SIZE = 5; // Lookback period for momentum
};

#endif
