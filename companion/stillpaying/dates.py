"""Dates as day numbers, month arithmetic and England and Wales bank holidays.

A day number counts the days since 1 January 1970, as the browser model does,
so dates in saved reviews, summaries and calendars line up exactly.
"""

import calendar
import datetime as _dt
import functools
import math

from .common import js_regex, pad2, text_or

_EPOCH_ORDINAL = 719163

MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
               'October', 'November', 'December']
DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']


def day_from_ymd(y, m, d):
    """The day number of a calendar date."""
    return _dt.date(y, m, d).toordinal() - _EPOCH_ORDINAL


@functools.lru_cache(maxsize=None)
def _ymd(day):
    dt = _dt.date.fromordinal(day + _EPOCH_ORDINAL)
    return dt.year, dt.month, dt.day


def ymd(day):
    """(year, month, day of month) for a day number."""
    return _ymd(math.floor(day))


def iso(day):
    """A day number as YYYY-MM-DD."""
    y, m, d = ymd(day)
    return str(y) + '-' + pad2(m) + '-' + pad2(d)


_ISO = js_regex(r'^(\d{4})-(\d{2})-(\d{2})$')


def from_iso(s):
    """YYYY-MM-DD as a day number, or None if it is not a real date."""
    m = _ISO.search(text_or(s))
    if not m:
        return None
    return valid_day(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def weekday(day):
    """0 for Sunday up to 6 for Saturday."""
    return (day + 4) % 7


def days_in_month(y, m):
    """How many days a month has."""
    return calendar.monthrange(y, m)[1]


def valid_day(y, m, d):
    """The day number of a date between 1900 and 2200, or None if the date does not exist."""
    if not (1900 <= y <= 2200) or not (1 <= m <= 12) or not (1 <= d <= days_in_month(y, m)):
        return None
    return day_from_ymd(y, m, d)


@functools.lru_cache(maxsize=None)
def nominal_in_month(y, m, anchor):
    """The nominal due day in a month.

    An anchor is a day of the month (31 means the last day) or a rule: 'LW'
    for the last working day, or 'L1' to 'L5' for the last Monday to Friday
    of the month, moved back a working day if that is a bank holiday.
    """
    if isinstance(anchor, str):
        if anchor[0] == 'B':
            b = day_from_ymd(y, m, min(int(anchor[1:]), days_in_month(y, m)))
            while not is_working_day(b):
                b -= 1
            return b
        d = day_from_ymd(y, m, days_in_month(y, m))
        if anchor == 'LW':
            while not is_working_day(d):
                d -= 1
            return d
        wd = int(anchor[1:])
        while weekday(d) != wd:
            d -= 1
        while not is_working_day(d):
            d -= 1
        return d
    return day_from_ymd(y, m, min(anchor, days_in_month(y, m)))


def add_months(day, months, anchor=None):
    """Move a day forward by whole months, landing on the nominal day of that month."""
    y, m, d = ymd(day)
    total = y * 12 + (m - 1) + months
    return nominal_in_month(total // 12, total % 12 + 1, anchor if anchor else d)


def short_date(day):
    """14 Dec"""
    y, m, d = ymd(day)
    return str(d) + ' ' + MONTH_NAMES[m - 1][:3]


def long_date(day):
    """14 Dec 2026"""
    y, m, d = ymd(day)
    return str(d) + ' ' + MONTH_NAMES[m - 1][:3] + ' ' + str(y)


def ordinal(n):
    """1st, 2nd, 3rd, 4th, 11th, 21st ..."""
    s = n % 100
    if 11 <= s <= 13:
        return str(n) + 'th'
    return str(n) + (['th', 'st', 'nd', 'rd'][n % 10] if n % 10 < 4 else 'th')


# England and Wales bank holidays, including the one-off changes since 2012.
HOLIDAY_MOVES = {
    2012: {'remove': ['2012-05-28'], 'add': ['2012-06-04', '2012-06-05']},
    2020: {'remove': ['2020-05-04'], 'add': ['2020-05-08']},
    2022: {'remove': ['2022-05-30'], 'add': ['2022-06-02', '2022-06-03', '2022-09-19']},
    2023: {'remove': [], 'add': ['2023-05-08']},
}


def easter_sunday(y):
    """Easter Day in a year (the Western church's date)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    dd = (h + l - 7 * m + 114) % 31 + 1
    return day_from_ymd(y, month, dd)


def first_monday(y, m):
    """The first Monday of a month."""
    d = day_from_ymd(y, m, 1)
    while weekday(d) != 1:
        d += 1
    return d


def last_monday(y, m):
    """The last Monday of a month."""
    d = day_from_ymd(y, m, days_in_month(y, m))
    while weekday(d) != 1:
        d -= 1
    return d


@functools.lru_cache(maxsize=None)
def _holidays(y):
    days = []
    ny = day_from_ymd(y, 1, 1)
    if weekday(ny) == 6:
        ny += 2
    elif weekday(ny) == 0:
        ny += 1
    days.append(ny)
    easter = easter_sunday(y)
    days += [easter - 2, easter + 1]
    days += [first_monday(y, 5), last_monday(y, 5), last_monday(y, 8)]
    xmas = day_from_ymd(y, 12, 25)
    wd = weekday(xmas)
    if wd == 6:
        days += [xmas + 2, xmas + 3]
    elif wd == 0:
        days += [xmas + 1, xmas + 2]
    elif wd == 5:
        days += [xmas, xmas + 3]
    else:
        days += [xmas, xmas + 1]
    moves = HOLIDAY_MOVES.get(y)
    if moves:
        days = [d for d in days if iso(d) not in moves['remove']]
        days += [from_iso(s) for s in moves['add']]
    return tuple(sorted(days))


def bank_holidays(y):
    """England and Wales bank holidays in a year, as sorted day numbers."""
    return list(_holidays(y))


@functools.lru_cache(maxsize=None)
def _holiday_set(y):
    return frozenset(_holidays(y))


def is_working_day(day):
    """Monday to Friday and not a bank holiday."""
    wd = weekday(day)
    if wd == 0 or wd == 6:
        return False
    return day not in _holiday_set(ymd(day)[0])


def next_working_day(day):
    """The day itself if it is a working day, otherwise the next one."""
    while not is_working_day(day):
        day += 1
    return day
