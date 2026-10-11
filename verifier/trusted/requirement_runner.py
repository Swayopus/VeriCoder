"""Execute reviewed assertion code and attest normal completion or failure."""

from __future__ import annotations

import ast
import json
import os
import sys
import traceback
from pathlib import Path


def main() -> int:
    code_path, report_path, nonce = sys.argv[1:]
    receipt = {
        "protocol": 1, "nonce": nonce, "completed": False,
        "assertions_declared": 0, "assertions_started": 0, "assertions_passed": 0,
        "passed": False, "valid": False, "message": "",
    }
    try:
        source = Path(code_path).read_text(encoding="utf-8")
        tree = ast.parse(source, filename="<reviewed requirement>")
        receipt["assertions_declared"] = sum(isinstance(node, ast.Assert) for node in ast.walk(tree))
        if not receipt["assertions_declared"]:
            raise ValueError("Requirement code contains no assertions")

        def observe(kind):
            receipt["assertions_" + kind] += 1

        callback_name = "__vericoder_observe_" + nonce

        class InstrumentAssertions(ast.NodeTransformer):
            def visit_Assert(self, node):
                def event(kind):
                    return ast.copy_location(ast.Expr(ast.Call(
                        ast.Name(callback_name, ast.Load()), [ast.Constant(kind)], [],
                    )), node)
                return [event("started"), node, event("passed")]

        tree = ast.fix_missing_locations(InstrumentAssertions().visit(tree))
        namespace = {"__name__": "__main__", callback_name: observe}
        sys.path.insert(0, os.getcwd())
        try:
            exec(compile(tree, "<reviewed requirement>", "exec", optimize=0), namespace)
        except SystemExit as exc:
            receipt["message"] = f"Requirement exited before completion: {exc}"
        except Exception as exc:
            receipt["valid"] = True
            receipt["message"] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        else:
            receipt["valid"] = receipt["assertions_started"] > 0
            receipt["passed"] = receipt["valid"]
            if not receipt["valid"]:
                receipt["message"] = "No assertion was executed"
    except Exception as exc:
        receipt["message"] = f"Invalid reviewed requirement: {type(exc).__name__}: {exc}"
    receipt["completed"] = True
    Path(report_path).write_text(json.dumps(receipt), encoding="utf-8")
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
