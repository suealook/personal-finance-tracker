from dataclasses import dataclass


@dataclass
class Category:
    name: str
    type: str  # Expense | Income | Savings | Debt
    active: bool
    notes: str = ""


@dataclass
class PlannedBudget:
    month: str  # YYYY-MM
    category: str
    planned_amount: float
    notes: str = ""


@dataclass
class Transaction:
    transaction_id: str
    date: str  # YYYY-MM-DD
    amount: float
    category: str
    note: str
    source: str  # telegram | web
    logged_at: str
    telegram_msg_id: str = ""
    status: str = "active"  # active | undone


@dataclass
class RawLogEntry:
    timestamp: str
    telegram_user_id: str
    telegram_username: str
    raw_text: str
    parse_status: str  # pending | parsed | failed
    linked_transaction_id: str = ""


@dataclass
class Report:
    month: str
    generated_at: str
    report_text: str
    model_used: str
