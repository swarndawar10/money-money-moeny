#include <iostream>
#include <string>
#include <fstream>
#include <stdexcept>
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
            cfg.atr_initial_multiplier  = j.value("atr_initial_multiplier",  2.0);
            cfg.atr_trailing_multiplier = j.value("atr_trailing_multiplier", 2.5);
            cfg.max_risk_per_trade      = j.value("max_risk_per_trade",       0.01);
            cfg.max_portfolio_exposure  = j.value("max_portfolio_exposure",   0.50);
            cfg.max_sector_exposure     = j.value("max_sector_exposure",      0.20);
            cfg.max_positions           = j.value("max_positions",            5);
            cfg.max_daily_loss          = j.value("max_daily_loss",           0.03);
            cfg.max_drawdown            = j.value("max_drawdown",             0.10);
            cfg.momentum_threshold      = j.value("momentum_threshold",       0.005);
            cfg.volume_multiplier       = j.value("volume_multiplier",        1.5);
            cfg.vix_high_risk_threshold = j.value("vix_high_risk_threshold",  22.0);
            std::cout << "[SYSTEM] Loaded config from " << path << std::endl;
        } catch (const std::exception& e) {
            std::cerr << "[FATAL] Failed to parse config: " << e.what()
                      << ". Halting — fix the config file." << std::endl;
            std::exit(1);
        }
    } else {
        std::cout << "[WARNING] Could not open " << path << ". Using defaults." << std::endl;
    }

    // Validate — throws if any value is obviously wrong
    try {
        cfg.validate();
    } catch (const std::invalid_argument& e) {
        std::cerr << "[FATAL] Invalid configuration: " << e.what() << std::endl;
        std::exit(1);
    }

    return cfg;
}

int main() {
    std::cout << "[CPP ENGINE] Risk-First Momentum Engine v2 starting..." << std::endl;

    Config cfg = loadConfig("config.json");
    StrategyEngine strategy(cfg);
    RiskManager    riskManager(cfg, 500000.0);

    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;

        try {
            json j = json::parse(line);
            std::string type = j.value("type", "");

            if (type == "info") {
                std::cout << "[INFO] " << j.value("message", "") << std::endl;

            } else if (type == "regime") {
                std::string regime = j.value("status", "MISSING_DATA");
                riskManager.updateRegime(regime);

            } else if (type == "trade") {
                std::string ticker = j.at("ticker");
                double price       = j.at("price");
                long   volume      = j.at("volume");
                long   timestamp   = j.at("timestamp");
                double atr         = j.value("atr", 0.0);
                std::string sector = j.value("sector", "UNKNOWN");

                // ── Deterministic tick processing order ───────────────────────
                // 1. Advance the clock / handle daily reset
                riskManager.onTimestamp(timestamp);

                // 2. Update open position prices & evaluate exits
                riskManager.updatePositions(ticker, price, atr);

                // 3. Evaluate circuit breakers against current equity
                //    (done inside processSignal; also triggered in updatePositions
                //     implicitly via equity after closing positions)

                // 4. Generate strategy signal
                Signal sig = strategy.processTick(ticker, price, volume, atr, timestamp, sector);

                // 5. Risk manager makes the final entry decision
                riskManager.processSignal(ticker, price, atr, sector, sig);
            }

        } catch (const json::exception& e) {
            std::cerr << "[ERROR] JSON error: " << e.what() << " | line: " << line << std::endl;
        } catch (const std::exception& e) {
            std::cerr << "[ERROR] Unexpected: " << e.what() << std::endl;
        }
    }

    std::cout << "[CPP ENGINE] Stream ended."
              << " | Cash: " << riskManager.getCash()
              << " | Equity: " << riskManager.getEquity()
              << std::endl;
    return 0;
}
