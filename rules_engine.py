import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


def _coerce_finite_float(value, label):
    try:
        coerced = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a finite number.") from None

    if not math.isfinite(coerced):
        raise ValueError(f"{label} must be a finite number.")

    return coerced


# A single allocation rule describing how much of a sale should go to a category.
@dataclass(frozen=True)
class Rule:
    name: str
    percent: float

    def __post_init__(self):
        # Every rule must be named so the result dictionary is explicit and readable.
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Rule name must be a non-empty string.")

        normalized_name = self.name.strip()
        if normalized_name.lower() == "profit":
            raise ValueError("Rule name 'profit' is reserved for the remaining business profit.")

        # Percentages are stored as floats so values like 2, 3.5, or 10 are supported.
        percent = _coerce_finite_float(self.percent, f"Rule '{normalized_name}' percentage")
        if percent < 0:
            raise ValueError(f"Rule '{normalized_name}' cannot have a negative percentage.")

        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "percent", percent)


class RulesEngine:
    """Evaluate a set of percentage-based allocation rules."""

    def __init__(self, rules):
        # Normalize all incoming rule shapes into a consistent list of Rule objects.
        self.rules = self._normalize_rules(rules)

        # Business rule: the total allocation must never exceed 100% of the sale.
        total_percent = sum(rule.percent for rule in self.rules)
        if total_percent > 100:
            raise ValueError("The total split percentage cannot exceed 100%.")

    @staticmethod
    def _normalize_rules(rules):
        # Allow either a dict of name -> percent or a list of rules/tuples.
        if isinstance(rules, dict):
            rules = list(rules.items())

        normalized = []
        seen_names = set()

        for rule in rules:
            if isinstance(rule, Rule):
                current = rule
            elif isinstance(rule, tuple) and len(rule) == 2:
                current = Rule(rule[0], rule[1])
            else:
                raise TypeError("Each rule must be a Rule instance or a (name, percent) tuple.")

            # Prevent duplicate categories from being evaluated twice.
            if current.name in seen_names:
                raise ValueError(f"Duplicate rule name '{current.name}' is not allowed.")

            seen_names.add(current.name)
            normalized.append(current)

        return normalized

    def evaluate(self, total_amount):
        total_amount = _coerce_finite_float(total_amount, "Total amount")
        if total_amount < 0:
            raise ValueError("Total amount cannot be negative.")

        total = Decimal(str(total_amount))
        remaining = total
        allocations = {}
        for rule in self.rules:
            exact_amount = total * (Decimal(str(rule.percent)) / Decimal("100"))
            # Rounded expense allocations must never spend more than the sale.
            rounded_amount = min(exact_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), remaining)
            allocations[rule.name] = float(rounded_amount)
            remaining -= rounded_amount

        allocations["profit"] = float(remaining.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        return allocations
