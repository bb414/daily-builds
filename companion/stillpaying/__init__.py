"""Still paying? companion: finds regular payments in bank exports, the same way the browser app does.

The package is a faithful port of the browser model (src/model.js). Records
are plain dicts whose keys match the browser model's field names (nextDue,
confidenceLabel and so on), so summaries and saved reviews are interchangeable
between the two. Money is held in whole pence and dates as day numbers (days
since 1 January 1970).
"""

from .common import money, plain_money, round_half_up
from .dates import add_months, bank_holidays, day_from_ymd, from_iso, is_working_day, iso, long_date, \
    next_working_day, nominal_in_month, short_date
from .detect import CADENCE_BY_ID, CADENCES, find_regulars, fit_cadence
from .merging import link_same_accounts, merge_statements
from .model import analyse, summary
from .outputs import DECISION_LABELS, budget_csv, build_ics, project_file, read_project, register_csv, \
    template_csv, to_csv
from .parsing import date_shape, default_account, detect_date_order, parse_amount, parse_csv, parse_date, \
    parse_delimited, parse_statement, sniff_delimiter
from .payees import CATEGORIES, CATEGORY_BY_ID, categorise, clean_description, display_name, payee_key, \
    payment_method
from .planning import DECISIONS, forecast, how_to_stop, month_totals, plan, since_last_review, suggest

VERSION = '1.0'
