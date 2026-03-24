#!/usr/bin/env python3
"""Gera test/result/test_report.html a partir dos ficheiros gerados por test/run_tests.sh."""
from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "test" / "result"


def main() -> None:
    RES.mkdir(parents=True, exist_ok=True)
    out_log = RES / "unittest_output.txt"
    cov_txt = RES / "coverage_report.txt"
    log_body = (
        out_log.read_text(encoding="utf-8", errors="replace")
        if out_log.exists()
        else "(corre test/run_tests.sh para gerar unittest_output.txt)"
    )
    cov_body = (
        cov_txt.read_text(encoding="utf-8", errors="replace")
        if cov_txt.exists()
        else "(sem coverage_report.txt)"
    )
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    page = f"""<!DOCTYPE html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <title>Resultados de testes — factor-router</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 1.5rem; max-width: 56rem; line-height: 1.45; }}
    pre {{ background: #f6f8fa; padding: 1rem; overflow: auto; font-size: 0.85rem; border-radius: 6px; }}
    a {{ color: #0b57d0; }}
    h2 {{ margin-top: 1.75rem; }}
  </style>
</head>
<body>
  <h1>Resultados de testes</h1>
  <p>Gerado em: {html.escape(ts)}</p>
  <p><a href="htmlcov/index.html">Cobertura (HTML)</a> ·
     <a href="unittest_output.txt">unittest_output.txt</a> ·
     <a href="coverage_report.txt">coverage_report.txt</a></p>
  <h2>Saída do unittest</h2>
  <pre>{html.escape(log_body)}</pre>
  <h2>Resumo coverage (texto)</h2>
  <pre>{html.escape(cov_body)}</pre>
</body>
</html>
"""
    (RES / "test_report.html").write_text(page, encoding="utf-8")
    print(f"Escrito {RES / 'test_report.html'}")


if __name__ == "__main__":
    main()
