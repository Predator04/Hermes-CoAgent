import sys, traceback
sys.argv = ["coagent_tray.py"]
script = r"C:\Users\Admin\Desktop\Hermes CoAgent\coagent_tray.py"
try:
    exec(open(script, encoding="utf-8").read())
except SystemExit:
    pass
except Exception:
    traceback.print_exc()
    input("Press Enter to exit...")
