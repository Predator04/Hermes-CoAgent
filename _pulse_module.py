# === CURSOR PULSE — visual ring before every AI action ===
# Draws a colored ring at the cursor position to show "AI is doing something"

def _cursor_pulse(x, y, color=None, radius=25):
    """Flash a colored ring at (x, y) to indicate AI action about to happen."""
    if color is None:
        color = 0x00FF00  # green
    r = (color >> 16) & 0xFF
    g = (color >> 8) & 0xFF
    b = color & 0xFF
    try:
        ps(f'''
Add-Type @"
using System;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;
public class Overlay {{
    public static void Flash(int x, int y, int r, int g, int b, int radius) {{
        var f = new Form();
        f.FormBorderStyle = FormBorderStyle.None;
        f.BackColor = Color.FromArgb(128, r, g, b);
        f.TopLevel = true;
        f.TopMost = true;
        f.ShowInTaskbar = false;
        f.StartPosition = FormStartPosition.Manual;
        f.Location = new Point(x - radius, y - radius);
        f.Size = new Size(radius * 2, radius * 2);
        f.Opacity = 0.6;
        f.Show();
        System.Threading.Thread.Sleep(120);
        for (int i = 0; i < 8; i++) {{
            f.Opacity -= 0.075;
            System.Threading.Thread.Sleep(10);
        }}
        f.Close();
    }}
}}
"@
[Overlay]::Flash({x}, {y}, {r}, {g}, {b}, {radius})
''', timeout=5)
    except:
        pass  # pulse is cosmetic, don't block the action
