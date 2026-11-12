#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root/backend"
command -v java >/dev/null || { echo '请先安装 JDK 21'; exit 1; }
command -v mvn >/dev/null || { echo '请先安装 Maven 3.9+'; exit 1; }
mvn -B -DskipTests package
exec java -jar target/mini-insurance-api-1.0.0.jar --spring.profiles.active=demo

