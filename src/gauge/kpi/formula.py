"""Safe evaluator for the KPI formulas in config/indicators.yaml.

The formulas are executed, not just documented, so config and computation cannot drift apart.
Only +, -, *, /, parentheses, unary minus, integer constants and indicator names are allowed; the
text is parsed with `ast` and walked, never passed to eval. Arithmetic uses decimal.Decimal in a
fixed context (50 digits, half-even), so results do not depend on the thread's global context.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Context, Decimal, DivisionByZero, InvalidOperation, Overflow

CONTEXT = Context(
    prec=50, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, DivisionByZero, Overflow]
)


def percent_change(new: Decimal, old: Decimal) -> Decimal | None:
    """100 * (new - old) / old, or None when old is zero (the change is undefined)."""
    if old == 0:
        return None
    return CONTEXT.divide(CONTEXT.multiply(Decimal(100), CONTEXT.subtract(new, old)), old)


class FormulaError(ValueError):
    """The formula text uses something outside the allowed arithmetic."""


class Formula:
    def __init__(self, text: str) -> None:
        self.text = text
        try:
            self._tree = ast.parse(text, mode="eval").body
        except SyntaxError as exc:
            raise FormulaError(f"cannot parse formula {text!r}: {exc.msg}") from exc
        self.names: tuple[str, ...] = tuple(sorted(self._check(self._tree)))

    def _check(self, node: ast.AST) -> set[str]:
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
        ):
            return self._check(node.left) | self._check(node.right)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return self._check(node.operand)
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return set()
        if isinstance(node, ast.Name):
            return {node.id}
        raise FormulaError(f"formula {self.text!r}: unsupported element {type(node).__name__}")

    def evaluate(self, env: Mapping[str, Decimal]) -> Decimal:
        """Evaluate with the given indicator values. KeyError if an input is missing;
        ZeroDivisionError if a denominator is zero (including 0/0)."""
        return self._eval(self._tree, env)

    def _eval(self, node: ast.AST, env: Mapping[str, Decimal]) -> Decimal:
        if isinstance(node, ast.Constant):
            return Decimal(node.value)
        if isinstance(node, ast.Name):
            return env[node.id]
        if isinstance(node, ast.UnaryOp):
            return CONTEXT.minus(self._eval(node.operand, env))
        left, right = self._eval(node.left, env), self._eval(node.right, env)
        if isinstance(node.op, ast.Add):
            return CONTEXT.add(left, right)
        if isinstance(node.op, ast.Sub):
            return CONTEXT.subtract(left, right)
        if isinstance(node.op, ast.Mult):
            return CONTEXT.multiply(left, right)
        # 0/0 is InvalidOperation in decimal, not DivisionByZero; callers get one exception type
        if right == 0:
            raise ZeroDivisionError("division by zero")
        return CONTEXT.divide(left, right)
