"""Show coverage summary for core modules."""
import json

data = json.load(open("coverage.json"))
files = [
    (f, v)
    for f, v in data["files"].items()
    if "protoforge\\core" in f or "protoforge\\api" in f or "protoforge\\db" in f or "protoforge\\models" in f
]
files.sort(key=lambda x: -x[1]["summary"]["num_statements"])
print(f"{'File':<60} {'Cov%':>6} {'Covered':>8} {'Total':>6}")
print("-" * 85)
for f, v in files[:30]:
    s = v["summary"]
    print(f"{f:<60} {s['percent_covered']:>5.1f}% {s['covered_lines']:>8} {s['num_statements']:>6}")

total_covered = sum(v["summary"]["covered_lines"] for _, v in files)
total_stmts = sum(v["summary"]["num_statements"] for _, v in files)
if total_stmts > 0:
    print(f"\nCore modules total: {total_covered}/{total_stmts} = {100*total_covered/total_stmts:.1f}%")

# Also show totals
print(f"\nOverall: {data['totals']['covered_lines']}/{data['totals']['num_statements']} = {data['totals']['percent_covered']:.1f}%")
