import py_compile, glob, sys
errors = []
py_files = glob.glob('protoforge/**/*.py', recursive=True)
for f in py_files:
    try:
        py_compile.compile(f, doraise=True)
    except py_compile.PyCompileError as e:
        errors.append(str(e))
if errors:
    for e in errors:
        print(f'ERROR: {e}')
    sys.exit(1)
else:
    print(f'ALL OK - {len(py_files)} files checked')
