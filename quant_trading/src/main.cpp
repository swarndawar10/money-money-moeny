#include <iostream>
#include <string>
#include <fstream>
#include <nlohmann/json.hpp>
#include "StrategyEngine.h"
#include "RiskManager.h"
#include "Config.h"

using json = nlohmann::json;

Config loadConfig(const std::string& path) {
    Config cfg;
    std::ifstream file(path);
    if (file.is_open()) {
        try {
            json j;
            file >> j;
            cfg.atr_initial_multiplier = j.value("atr_initial_multiplier", 2.0);
            cfg.atr_trailing_multiplier = j.value("atr_trailing_multiplier", 2.5);
            cfg.max_risk_per_trade = j.value("max_risk_per_trade", 0.01);
            cfg.max_portfolio_exposure = j.value("max_portfolio_exposure", 0.50);
            cfg.max_sector_exposure = j.value("max_sector_exposure", 0.20);
            cfg.max_positions = j.value("max_positions", 5);
            cfg.max_daily_loss = j.value("max_daily_loss", 0.03);
            cfg.max_drawdown = j.value("max_drawdown", 0.10);
            cfg.momentum_threshold = j.value("momentum_threshold", 0.005);
            cfg.volume_multiplier = j.value("volume_multiplier", 1.5);
            cfg.vix_high_risk_threshold = j.value("vix_high_risk_threshold", 22.0);
            std::cout << "[SYSTEM] Loaded config from " << path << std::endl;
        } catch (const std::exception& e) {
            std::cerr << "[WARNING] Failed to parse config JSON: " << e.what() << ". Using defaults." << std::endl;
        }
    } else {
        std::cout << "[WARNING] Could not open " << path << ". Using defaults." << std::endl;
    }
    return cfg;
}

int main() {
    std::cout << "[CPP ENGINE] Starting Risk-First Momentum Engine..." << std::endl;
    
    Config cfg = loadConfig("config.json");
    StrategyEngine strategy(cfg);
    RiskManager riskManager(cfg, 500000.0);

    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        
        try {
            json j = json::parse(line);
            std::string type = j.value("type", "");
            
            if (type == "info") {
                std::cout << "[INFO] " << j.value("message", "") << std::endl;
            } else if (type == "regime") {
                std::string regime = j.value("status", "NORMAL");
                riskManager.updateRegime(regime);
            } else if (type == "trade") {
                std::string ticker = j["ticker"];
                double price = j["price"];
                long volume = j["volume"];
                double atr = j.value("atr", 0.0); // Now required
                long timestamp = j["timestamp"];
                
                // Monitor open position exits FIRST
                riskManager.updatePositions(ticker, price, atr);
                
                // Then check for new entry signals
                Signal sig = strategy.processTick(ticker, price, volume, atr, timestamp);
                riskManager.processSignal(ticker, price, atr, sig);
            }
        } catch (const std::exception& e) {
            std::cerr << "[ERROR] JSON parse error: " << e.what() << " on line: " << line << std::endl;
        }
    }
    
    std::cout << "[CPP ENGINE] Stream ended. Final Capital: " << riskManager.getCapital() << std::endl;
    return 0;
}
