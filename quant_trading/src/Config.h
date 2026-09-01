#ifndef CONFIG_H
#define CONFIG_H

struct Config {
    double atr_initial_multiplier = 2.0;
    double atr_trailing_multiplier = 2.5;
    double max_risk_per_trade = 0.01;
    double max_portfolio_exposure = 0.50;
    double max_sector_exposure = 0.20;
    int max_positions = 5;
    double max_daily_loss = 0.03;
    double max_drawdown = 0.10;
    double momentum_threshold = 0.005;
    double volume_multiplier = 1.5;
    double vix_high_risk_threshold = 22.0;
};

#endif
