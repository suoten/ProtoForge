#!/usr/bin/env python
"""Check asyncua 1.1.8 API compatibility."""
import asyncio
from asyncua import Server, ua

async def check():
    s = Server()
    await s.init()
    node = await s.nodes.objects.add_variable(2, 'Test', ua.Variant(1.0, ua.VariantType.Float))

    # Check historize-related methods
    hist_methods = [m for m in dir(node) if 'hist' in m.lower()]
    print(f"History methods on Node: {hist_methods}")

    # Check if set_writable exists
    write_methods = [m for m in dir(node) if 'writ' in m.lower() or 'access' in m.lower()]
    print(f"Write/Access methods on Node: {write_methods}")

    # Check DataValue construction
    try:
        dv = ua.DataValue(
            ua.Variant(42.0, ua.VariantType.Float),
            StatusCode_=ua.StatusCode(0),
            SourceTimestamp=None,
        )
        print(f"DataValue with StatusCode_ OK: {dv.Value} {dv.StatusCode_}")
    except Exception as e:
        print(f"DataValue with StatusCode_ FAILED: {e}")

    # Check server method for historize
    server_hist = [m for m in dir(s) if 'hist' in m.lower()]
    print(f"Server history methods: {server_hist}")

    # Check set_attribute methods
    attr_methods = [m for m in dir(node) if 'set' in m.lower()]
    print(f"Node set methods: {attr_methods}")

asyncio.run(check())
