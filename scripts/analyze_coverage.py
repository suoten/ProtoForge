"""Analyze coverage and show least-covered modules."""
import json

with open("coverage.json") as f:
    data = json.load(f)

files = [(f, v) for f, v in data["files"].items() if "protoforge" in f]
files.sort(key=lambda x: -x[1]["summary"]["num_statements"])

print(f"{'File':<65} {'Total':>6} {'Covered':>8} {'Cov%':>6}")
print("-" * 90)
for f, v in files[:30]:
    s = v["summary"]
    print(f"{f:<65} {s['num_statements']:>6} {s['covered_lines']:>8} {s['percent_covered']:>5.1f}%")

total_covered = sum(v["summary"]["covered_lines"] for _, v in files)
total_stmts = sum(v["summary"]["num_statements"] for _, v in files)
if total_stmts > 0:
    print(f"\nProtoForge total: {total_covered}/{total_stmts} = {100*total_covered/total_stmts:.1f}%")

# Show modules with most uncovered lines (biggest impact opportunities)
print(f"\n{'--- Top uncovered modules (by uncovered lines) ---':^90}")
print(f"{'File':<65} {'Uncovered':>10}")
print("-" * 90)
uncovered = [(f, v["summary"]["num_statements"] - v["summary"]["covered_lines"]) for f, v in files]
uncovered.sort(key=lambda x: -x[1])
for f, unc in uncovered[:15]:
    print(f"{f:<65} {unc:>10}")
