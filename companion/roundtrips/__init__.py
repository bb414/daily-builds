"""Round trips: turn fills exports from a broker or trading-challenge platform into round-trip trades and an honest weekly review.

The package mirrors the browser app's model (src/model.js) so both give the same trades, statistics,
breaches and files. On top of that it adds jobs the app cannot do: a team review across a folder of
exports, a weekly command-line job that merges new exports into a running journal and writes a dated
HTML review with CSVs, and printable HTML reports.
"""

from .common import (DAY, PRICE_SCALE, QTY_SCALE, VERSION, civil, cmp, detect_date_order, date_shape, fmt_date, fmt_day_month_year, fmt_duration,
                     fmt_num, fmt_pct, fmt_price, fmt_qty, fmt_r, fmt_short, fmt_time, from_iso, iso_stamp, money, parse_cents, parse_date_time,
                     parse_float_text, parse_micro, parse_time, plain_money, plural, read_number, rnd, scaled, to_iso, week_label, week_start, weekday)
from .matching import (RULES, account_settings, analyse, check_rules, default_rules, default_settings, empty_state, fx_rate, import_files,
                       journal_entry, make_carry, match_trades, multiplier_for, piece_pnl, rule_label, set_journal, trade_risk)
from .outputs import breaches_csv, csv_cell, fills_csv, position_size, project_file, read_project, template_csv, trades_csv
from .parsing import classify_side, clean_account_name, norm_header, parse_delimited, read_export, sniff_delimiter, symbol_root
from .days import day_detail, day_ledger, days_csv
from .jobs import discover_members, team_csv, team_review, weekly_job
from .report import equity_svg, team_report, weekly_report
from .review import review_text, trade_name, week_review
from .stats import BREAKDOWNS, HOLD_BUCKETS, breakdown, filter_trades, hold_bucket, r_histogram, start_balance, stats, usable, weekly

__all__ = [name for name in dir() if not name.startswith('_')]
