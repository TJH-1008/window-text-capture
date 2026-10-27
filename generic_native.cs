using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public static class GenericNativeText {
    [DllImport("user32.dll", CharSet=CharSet.Unicode)]
    static extern int GetClassName(IntPtr handle, StringBuilder name, int count);
    [DllImport("user32.dll")]
    static extern int GetWindowLong(IntPtr handle, int index);
    [DllImport("user32.dll", CharSet=CharSet.Unicode, EntryPoint="SendMessageTimeoutW")]
    static extern IntPtr SendValue(IntPtr handle, uint message, IntPtr w, IntPtr l,
                                  uint flags, uint timeout, out IntPtr result);
    [DllImport("user32.dll", CharSet=CharSet.Unicode, EntryPoint="SendMessageTimeoutW")]
    static extern IntPtr SendText(IntPtr handle, uint message, IntPtr w, StringBuilder l,
                                 uint flags, uint timeout, out IntPtr result);
    public sealed class ReadResult {
        public string Text = "";
        public bool Limited;
    }
    public static string ClassName(IntPtr handle) {
        var name = new StringBuilder(512);
        if (handle != IntPtr.Zero) GetClassName(handle, name, name.Capacity);
        return name.ToString().ToUpperInvariant();
    }
    public static bool IsPassword(IntPtr handle, string className) {
        if (handle == IntPtr.Zero || !className.Contains("EDIT")) return false;
        if ((GetWindowLong(handle, -16) & 0x20) != 0) return true;
        IntPtr character;
        return SendValue(handle, 0xD2, IntPtr.Zero, IntPtr.Zero, 2, 250, out character) != IntPtr.Zero
               && character != IntPtr.Zero;
    }
    public static ReadResult Read(IntPtr handle, string className) {
        var result = new ReadResult();
        if (handle == IntPtr.Zero || IsPassword(handle, className)) return result;
        const int limit = 262144;
        if (className.Contains("LISTBOX")) {
            int style = GetWindowLong(handle, -16);
            if ((style & 0x30) != 0 && (style & 0x40) == 0) return result;
            IntPtr count;
            if (SendValue(handle, 0x18B, IntPtr.Zero, IntPtr.Zero, 2, 250, out count) == IntPtr.Zero) return result;
            long items = count.ToInt64();
            var lines = new List<string>();
            int totalLength = 0;
            result.Limited = items > 200;
            for (int index = 0; index < Math.Min(items, 200); index++) {
                IntPtr length;
                if (SendValue(handle, 0x18A, (IntPtr)index, IntPtr.Zero, 2, 250, out length) == IntPtr.Zero) {
                    result.Limited = true; break;
                }
                if (length.ToInt64() < 0 || length.ToInt64() >= limit) {result.Limited = true; continue;}
                var text = new StringBuilder(limit + 1);
                IntPtr copied;
                if (SendText(handle, 0x189, (IntPtr)index, text, 2, 250, out copied) != IntPtr.Zero) {
                    lines.Add(text.ToString());
                    totalLength += text.Length;
                    if (totalLength >= limit) {result.Limited = true; break;}
                }
                else {result.Limited = true; break;}
            }
            result.Text = String.Join("\n", lines);
        } else if (className.Contains("EDIT") || className.Contains("STATIC")) {
            var text = new StringBuilder(limit + 1);
            IntPtr copied;
            if (SendText(handle, 0xD, (IntPtr)text.Capacity, text, 2, 250, out copied) != IntPtr.Zero) {
                result.Text = text.ToString();
                result.Limited = copied.ToInt64() >= limit;
            }
        }
        return result;
    }
}
