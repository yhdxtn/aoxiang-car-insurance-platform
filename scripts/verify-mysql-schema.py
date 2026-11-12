#!/usr/bin/env python3
"""Execute migration DDL in MySQL initialization mode without opening a port.

Uses a brand-new temporary data directory, never the user's existing database.
This verifies real MySQL DDL compatibility; it is not a JDBC integration test.
Requires a locally installed MySQL 8.4 mysqld binary. Run as an ordinary user.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysqld", required=True, help="Absolute path to MySQL 8.4 mysqld")
    parser.add_argument("--basedir", help="Optional MySQL installation directory")
    parser.add_argument("--report", help="Optional output JSON path")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    files = sorted((root / "backend/src/main/resources/db/migration").glob("V*__*.sql"))
    if not files:
        raise SystemExit("No migration files found")
    statements = []
    for file in files:
        sql = re.sub(r"--[^\n]*", "", file.read_text())
        # The delivered migration contains no SQL procedures or embedded ';'.
        statements.extend(" ".join(part.split()) + ";" for part in sql.split(";") if part.strip())
    version = subprocess.run([args.mysqld, "--version"], check=True, text=True, capture_output=True).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="taikang-mysql-schema-") as temp:
        folder = Path(temp)
        result_file = folder / "table-count.txt"
        init_file = folder / "schema.sql"
        init_file.write_text("CREATE DATABASE taikang_schema_check CHARACTER SET utf8mb4;\n"
            "USE taikang_schema_check;\n" + "\n".join(statements) + "\n"
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='taikang_schema_check' "
            "INTO OUTFILE '" + result_file.as_posix().replace("'", "''") + "';\n")
        command = [args.mysqld, "--no-defaults", "--initialize-insecure",
                   "--datadir=" + str(folder / "data"), "--init-file=" + str(init_file)]
        if args.basedir:
            command.append("--basedir=" + args.basedir)
        result = subprocess.run(command, text=True, capture_output=True, timeout=120)
        if result.returncode or not result_file.exists():
            print(result.stderr[-8000:])
            raise SystemExit("MySQL schema initialization failed")
        count = int(result_file.read_text().strip())
        expected = sum(s.upper().startswith("CREATE TABLE ") for s in statements)
        if count != expected:
            raise SystemExit(f"Expected {expected} tables, got {count}")
        report = {"status": "passed", "mysql": version, "migrationFiles": [f.name for f in files],
                  "ddlStatements": len(statements), "tables": count,
                  "scope": "MySQL initialization-mode DDL execution; no JDBC/server integration"}
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
