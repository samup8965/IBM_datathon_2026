#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
check_dir=$(mktemp -d)
trap 'rm -rf "$check_dir"' EXIT
xcrun swiftc -parse-as-library OutageAlert/Models/Prediction.swift OutageAlert/Models/ADM1Region.swift OutageAlert/Data/PredictionProvider.swift OutageAlert/Data/MockRegionalPredictionProvider.swift OutageAlert/DashboardModel.swift Tests/DemoChecks.swift -o "$check_dir/demo-checks"
"$check_dir/demo-checks"
