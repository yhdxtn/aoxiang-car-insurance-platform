$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $taskRoot 'backend')
if (-not (Get-Command java -ErrorAction SilentlyContinue)) { throw '请先安装 JDK 21 并配置 PATH。' }
if (-not (Get-Command mvn -ErrorAction SilentlyContinue)) { throw '请先安装 Maven 3.9+ 并配置 PATH。' }
& mvn -B -DskipTests package
if ($LASTEXITCODE -ne 0) { throw '后端构建失败，请查看 Maven 输出。' }
& java -jar target/mini-insurance-api-1.0.0.jar --spring.profiles.active=demo
exit $LASTEXITCODE

