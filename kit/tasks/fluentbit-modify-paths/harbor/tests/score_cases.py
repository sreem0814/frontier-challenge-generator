"""Compare harness results with frozen expectations.

case_passes(case, result) -> bool. A case passes when the filter's verdict on the configuration matches
(accepted / refused) and, when accepted, every output body equals the expected body exactly: same map
entries in the same order (duplicates included), same array elements, same value types.
"""
from mpcodec import canon, unpackb


def case_passes(case, result):
    status, outs = result
    if case["status"] == "init_fail":
        return status == "init_fail"
    if status != "ok" or outs is None:
        return False
    exp = case["outputs"]
    if len(outs) != len(exp):
        return False
    for got, want in zip(outs, exp):
        try:
            if canon(unpackb(got)) != canon(unpackb(bytes.fromhex(want))):
                return False
        except Exception:
            return False
    return True
