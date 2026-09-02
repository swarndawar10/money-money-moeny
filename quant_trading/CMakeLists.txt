cmake_minimum_required(VERSION 3.10)
project(QuantTradingEngine)

set(CMAKE_CXX_STANDARD 17)

include(FetchContent)
FetchContent_Declare(
  json
  URL https://github.com/nlohmann/json/releases/download/v3.11.2/json.tar.xz
)
FetchContent_MakeAvailable(json)

# Main engine
add_executable(QuantTradingEngine
    src/main.cpp
    src/StrategyEngine.cpp
    src/RiskManager.cpp
)
target_link_libraries(QuantTradingEngine PRIVATE nlohmann_json::nlohmann_json)

# Test harness (no external framework — self-contained)
add_executable(RunTests
    src/tests/test_risk.cpp
    src/StrategyEngine.cpp
    src/RiskManager.cpp
)
target_link_libraries(RunTests PRIVATE nlohmann_json::nlohmann_json)
target_include_directories(RunTests PRIVATE src)
