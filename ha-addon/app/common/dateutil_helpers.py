from datetime import date, datetime, timedelta


def today_str() -> str:
    return date.today().isoformat()


def now_str() -> str:
    return datetime.now().isoformat(timespec="seconds")


def current_month() -> str:
    return date.today().strftime("%Y-%m")


def month_bounds(month: str) -> tuple[str, str]:
    """month is 'YYYY-MM'. Returns (first_day, last_day) as 'YYYY-MM-DD'."""
    year, mon = (int(x) for x in month.split("-"))
    first = date(year, mon, 1)
    if mon == 12:
        next_first = date(year + 1, 1, 1)
    else:
        next_first = date(year, mon + 1, 1)
    last = next_first - timedelta(days=1)
    return first.isoformat(), last.isoformat()


def year_bounds(year: str) -> tuple[str, str]:
    return f"{year}-01-01", f"{year}-12-31"


def add_months(month: str, delta: int) -> str:
    """month is 'YYYY-MM'. delta may be negative."""
    year, mon = (int(x) for x in month.split("-"))
    total = (year * 12 + (mon - 1)) + delta
    return f"{total // 12}-{(total % 12) + 1:02d}"


def previous_month(month: str) -> str:
    return add_months(month, -1)


def last_n_months(month: str, n: int) -> list[str]:
    """Returns n months ending at (and including) `month`, oldest first."""
    return [add_months(month, -i) for i in range(n - 1, -1, -1)]
