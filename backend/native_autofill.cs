using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

namespace VortexNativeAutofill
{
    class Program
    {
        [DllImport("user32.dll")]
        static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

        [DllImport("user32.dll")]
        static extern bool SetForegroundWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        static extern bool SetFocus(IntPtr hWnd);

        [DllImport("user32.dll")]
        static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

        [DllImport("user32.dll")]
        static extern bool IsWindowVisible(IntPtr hWnd);

        [DllImport("user32.dll")]
        static extern IntPtr FindWindow(string lpClassName, string lpWindowName);

        [DllImport("user32.dll")]
        static extern bool GetCursorPos(out POINT lpPoint);

        [DllImport("user32.dll")]
        static extern bool SetCursorPos(int X, int Y);

        [DllImport("user32.dll")]
        static extern void mouse_event(uint dwFlags, int dx, int dy, uint dwData, UIntPtr dwExtraInfo);

        [DllImport("user32.dll")]
        static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);

        [DllImport("user32.dll")]
        static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);

        [StructLayout(LayoutKind.Sequential)]
        public struct RECT
        {
            public int Left;
            public int Top;
            public int Right;
            public int Bottom;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct POINT
        {
            public int X;
            public int Y;
        }

        const int SW_RESTORE = 9;
        const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
        const uint MOUSEEVENTF_LEFTUP = 0x0004;
        const uint KEYEVENTF_KEYUP = 0x0002;
        const byte VK_TAB = 0x09;
        const byte VK_RETURN = 0x0D;
        const byte VK_CONTROL = 0x11;
        const byte VK_BACK = 0x08;
        const byte VK_MENU = 0x12; // Alt
        static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
        static readonly IntPtr HWND_NOTOPMOST = new IntPtr(-2);

        [STAThread]
        static void Main(string[] args)
        {
            if (args.Length < 2) return;

            string username = args[0];
            string password = args[1];

            IntPtr riotHwnd = IntPtr.Zero;
            RECT rect = new RECT();

            // 1. Wait for Riot Client window
            for (int i = 0; i < 50; i++)
            {
                riotHwnd = FindRiotWindow(out rect);
                if (riotHwnd != IntPtr.Zero) break;
                Thread.Sleep(100);
            }

            if (riotHwnd == IntPtr.Zero) return;

            Thread.Sleep(400);

            // 2. Bring window to absolute foreground
            ShowWindow(riotHwnd, SW_RESTORE);
            keybd_event(VK_MENU, 0, 0, UIntPtr.Zero);
            keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
            SetWindowPos(riotHwnd, HWND_TOPMOST, 0, 0, 0, 0, 0x0001 | 0x0002);
            SetWindowPos(riotHwnd, HWND_NOTOPMOST, 0, 0, 0, 0, 0x0001 | 0x0002);
            SetForegroundWindow(riotHwnd);
            SetFocus(riotHwnd);

            Thread.Sleep(200);

            GetWindowRect(riotHwnd, out rect);
            int width = rect.Right - rect.Left;
            int height = rect.Bottom - rect.Top;

            // 3. Attempt In-Client Sign Out if on Games Dashboard
            ClickAt(rect.Right - 35, rect.Top + 25);
            Thread.Sleep(150);

            ClickAt(rect.Right - 65, rect.Top + 105);
            Thread.Sleep(600);

            // 4. Focus Username field on Sign-In screen
            GetWindowRect(riotHwnd, out rect);
            width = rect.Right - rect.Left;
            height = rect.Bottom - rect.Top;
            int userX = rect.Left + (int)(width * 0.165);
            int userY = rect.Top + (int)(height * 0.245);
            ClickAt(userX, userY);
            Thread.Sleep(100);

            // 5. Clear Username & Paste
            SendHotkey(VK_CONTROL, (byte)'A');
            Thread.Sleep(25);
            SendKey(VK_BACK);
            Thread.Sleep(25);

            Clipboard.SetText(username);
            SendHotkey(VK_CONTROL, (byte)'V');
            Thread.Sleep(50);

            // 6. Focus Password field
            int passX = rect.Left + (int)(width * 0.165);
            int passY = rect.Top + (int)(height * 0.335);
            ClickAt(passX, passY);
            Thread.Sleep(50);

            // 7. Clear Password & Paste
            SendHotkey(VK_CONTROL, (byte)'A');
            Thread.Sleep(25);
            SendKey(VK_BACK);
            Thread.Sleep(25);

            Clipboard.SetText(password);
            SendHotkey(VK_CONTROL, (byte)'V');
            Thread.Sleep(50);

            // 8. Check "Stay signed in" checkbox
            int stayX = rect.Left + (int)(width * 0.082);
            int stayY = rect.Top + (int)(height * 0.405);
            ClickAt(stayX, stayY);
            Thread.Sleep(50);

            // 9. Submit Login (Click red arrow + Enter)
            int signinX = rect.Left + (int)(width * 0.165);
            int signinY = rect.Top + (int)(height * 0.585);
            ClickAt(signinX, signinY);
            Thread.Sleep(30);
            SendKey(VK_RETURN);
        }

        static void ClickAt(int screenX, int screenY)
        {
            POINT orig;
            bool hasOrig = GetCursorPos(out orig);
            try
            {
                SetCursorPos(screenX, screenY);
                Thread.Sleep(20);
                mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, UIntPtr.Zero);
                Thread.Sleep(20);
                mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
                Thread.Sleep(20);
            }
            finally
            {
                if (hasOrig)
                {
                    SetCursorPos(orig.X, orig.Y);
                }
            }
        }

        static IntPtr FindRiotWindow(out RECT outRect)
        {
            outRect = new RECT();
            
            IntPtr h = FindWindow(null, "Riot Client");
            if (h != IntPtr.Zero && IsWindowVisible(h))
            {
                GetWindowRect(h, out outRect);
                if ((outRect.Right - outRect.Left) >= 300) return h;
            }

            Process[] procs = Process.GetProcesses();
            foreach (var p in procs)
            {
                try
                {
                    string name = p.ProcessName.ToLower();
                    if (name.Contains("riotclient") || name.Contains("riot client"))
                    {
                        IntPtr hwnd = p.MainWindowHandle;
                        if (hwnd != IntPtr.Zero && IsWindowVisible(hwnd))
                        {
                            GetWindowRect(hwnd, out outRect);
                            if ((outRect.Right - outRect.Left) >= 300) return hwnd;
                        }
                    }
                }
                catch { }
            }
            return IntPtr.Zero;
        }

        static void SendKey(byte vk)
        {
            keybd_event(vk, 0, 0, UIntPtr.Zero);
            Thread.Sleep(15);
            keybd_event(vk, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
        }

        static void SendHotkey(byte modifier, byte key)
        {
            keybd_event(modifier, 0, 0, UIntPtr.Zero);
            keybd_event(key, 0, 0, UIntPtr.Zero);
            Thread.Sleep(15);
            keybd_event(key, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
            keybd_event(modifier, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
        }
    }
}
