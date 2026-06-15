"""Test UIA snapshot directly"""
import sys, os, traceback

# Init COM
try:
    import pythoncom
    pythoncom.CoInitialize()
except:
    pass

try:
    from pywinauto import Desktop as PyWinDesktop
    print("pywinauto imported OK")
    
    desktop = PyWinDesktop(backend="uia")
    print("Desktop created OK")
    
    root = desktop.wrapper_object()
    print(f"Root: {root}")
    
    # Get element info
    info = {
        "control_type": root.element_info.control_type or "",
        "automation_id": root.element_info.automation_id or "",
        "class_name": root.element_info.class_name or "",
        "name": root.element_info.name or "",
    }
    print(f"Root info: {info}")
    
    # Count children
    count = 0
    try:
        for child in root.children():
            count += 1
        print(f"Root has {count} children")
    except Exception as e:
        print(f"Children error: {e}")
    
    # Try finding a window
    wins = list(desktop.windows())
    print(f"Desktop has {len(wins)} windows")
    if wins:
        for w in wins[:5]:
            print(f"  - {w.element_info.name or '(unnamed)'}: {w.element_info.control_type}")
            
except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()
