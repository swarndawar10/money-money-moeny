#include <iostream>
#include <string>
#include <nlohmann/json.hpp>
#include "StrategyEngine.h"
#include "RiskManager.h"

using json = nlohmann::json;

int main() {
    std::cout << "[CPP ENGINE] Starting Indian Market Momentum Engine..." << std::endl;
    
    StrategyEngine strategy;
    RiskManager riskManager(1.0); // 1% stop loss

    std::string line;
    // Read from standard input line by line
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        
        try {
            json j = json::parse(line);
            
            std::string type = j.value("type", "");
            
            if (type == "info") {
                std::cout << "[INFO] " << j.value("message", "") << std::endl;
            } else if (type == "trade") {
                std::string ticker = j["ticker"];
                double price = j["price"];
                long volume = j["volume"];
                long timestamp = j["timestamp"];
                
                // 1. Process tick in strategy engine to get signal
                Signal sig = strategy.processTick(ticker, price, volume, timestamp);
                
                // 2. Risk manager acts on signals
                riskManager.processSignal(ticker, price, sig);
                
                // 3. Risk manager updates trailing stops for active positions
                riskManager.updatePositions(ticker, price);
            }
        } catch (const std::exception& e) {
            std::cerr << "[ERROR] JSON parse error: " << e.what() << " on line: " << line << std::endl;
        }
    }
    
    std::cout << "[CPP ENGINE] Data stream ended. Shutting down." << std::endl;
    return 0;
}
