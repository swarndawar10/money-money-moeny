#ifndef CONFIG_H
#define CONFIG_H

#include <stdexcept>
#include <string>

struct Config {
    double atr_initial_multiplier  = 2.0;
    double atr_trailing_multiplier = 2.5;
    double max_risk_per_trade      = 0.01;  // fraction of equity per trade
    double max_portfolio_exposure  = 0.50;  // max fraction of equity in all positions
    double max_sector_exposure     = 0.20;  // max fraction of equity in any one sector
    int    max_positions           = 5;
    double max_daily_loss          = 0.03;  // fraction of daily starting equity
    double max_drawdown            = 0.10;  // fraction of peak equity
    double momentum_threshold      = 0.005;
    double volume_multiplier       = 1.5;
    double vix_high_risk_threshold = 22.0;

    // Validate at startup. Throws std::invalid_argument if configuration is bad.
    void validate() const {
        if (atr_initial_multiplier  <= 0) throw std::invalid_argument("atr_initial_multiplier must be > 0");
        if (atr_trailing_multiplier <= 0) throw std::invalid_argument("atr_trailing_multiplier must be > 0");
        if (max_risk_per_trade      <= 0) throw std::invalid_argument("max_risk_per_trade must be > 0");
        if (max_risk_per_trade      >= 1) throw std::invalid_argument("max_risk_per_trade must be < 1");
        if (max_portfolio_exposure  <= 0) throw std::invalid_argument("max_portfolio_exposure must be > 0");
        if (max_portfolio_exposure  >  1) throw std::invalid_argument("max_portfolio_exposure must be <= 1");
        if (max_sector_exposure     <= 0) throw std::invalid_argument("max_sector_exposure must be > 0");
        if (max_sector_exposure     >  1) throw std::invalid_argument("max_sector_exposure must be <= 1");
        if (max_positions           <= 0) throw std::invalid_argument("max_positions must be > 0");
        if (max_daily_loss          <= 0) throw std::invalid_argument("max_daily_loss must be > 0");
        if (max_daily_loss          >  1) throw std::invalid_argument("max_daily_loss must be <= 1");
        if (max_drawdown            <= 0) throw std::invalid_argument("max_drawdown must be > 0");
        if (max_drawdown            >  1) throw std::invalid_argument("max_drawdown must be <= 1");
        if (momentum_threshold      <= 0) throw std::invalid_argument("momentum_threshold must be > 0");
        if (volume_multiplier       <= 0) throw std::invalid_argument("volume_multiplier must be > 0");
        if (vix_high_risk_threshold <= 0) throw std::invalid_argument("vix_high_risk_threshold must be > 0");
    }
};

#endif
