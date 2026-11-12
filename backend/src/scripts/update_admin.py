#!/usr/bin/env python3
"""
Forwarder to root update_admin.py
"""
import os
import sys

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
root_script = os.path.join(root_dir, "update_admin.py")
if os.path.exists(root_script):
    with open(root_script, "r", encoding="utf-8") as f:
        exec(f.read(), globals())
else:
    print(f"Error: Could not find {root_script}")
    sys.exit(1)
