import subprocess
from typing import List, Optional
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import tempfile
import os


def _run_adb_command(cmd: List[str]) -> str:
    try:
        result = subprocess.run(
            ["adb"] + cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30
        )
        return result.stdout.strip()
    except Exception as e:
        raise RuntimeError(f"ADB failed: {e}")


# ======================================================
#  ADB CONNECTION CLASS
# ======================================================
class ADBLUCIConnection:
    def __init__(self, device_id: Optional[str] = None):
        self.device_id = device_id

    @staticmethod
    def discover_devices() -> List[str]:
        raw = _run_adb_command(["devices"])
        lines = raw.split("\n")[1:]
        return [line.split("\t")[0] for line in lines if "\tdevice" in line]

    @classmethod
    def auto_connect(cls):
        devices = cls.discover_devices()
        if not devices:
            raise RuntimeError("No LUCI Pin detected via ADB.")
        return cls(devices[0])

    def _shell(self, command: str) -> str:
        return _run_adb_command(["-s", self.device_id, "shell"] + command.split(" "))

    # -------- FILE OPS ----------
    def list_files(self, path: str = "/") -> List[str]:
        out = self._shell(f"ls -1 '{path}'")
        if not out:
            return []
        return [f.strip() for f in out.split("\n") if f.strip()]

    def is_dir(self, path: str) -> bool:
        out = self._shell(f"test -d '{path}' && echo DIR || echo FILE")
        return "DIR" in out

    def pull_file(self, src: str, dst: str) -> bool:
        result = subprocess.run(
            ["adb", "-s", self.device_id, "pull", src, dst],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.returncode == 0 and os.path.exists(dst)

    def push(self, src: str, dst: str) -> bool:
        result = subprocess.run(
            ["adb", "-s", self.device_id, "push", src, dst],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.returncode == 0

    def delete(self, path: str):
        self._shell(f"rm -rf '{path}'")


# ======================================================
#  GUI FILE BROWSER
# ======================================================
class FileBrowserGUI:
    def __init__(self, connection: ADBLUCIConnection):
        self.conn = connection
        self.current_path = "/"

        self.window = tk.Tk()
        self.window.title("LUCI Pin ADB File Browser")
        self.window.geometry("700x650")

        # PATH LABEL
        self.path_label = tk.Label(self.window, text=self.current_path, font=("Arial", 12))
        self.path_label.pack(fill="x")

        # FILE LIST TREE
        self.tree = ttk.Treeview(self.window)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        # PREVIEW AREA
        self.preview_label = tk.Label(self.window, text="Select a file for preview", pady=10)
        self.preview_label.pack()

        # BUTTON BAR
        btn_frame = tk.Frame(self.window)
        btn_frame.pack(fill="x")

        tk.Button(btn_frame, text="↑ Up", command=self.go_up).pack(side="left")
        tk.Button(btn_frame, text="Upload", command=self.upload_file).pack(side="left")
        tk.Button(btn_frame, text="Download", command=self.download_file).pack(side="left")
        tk.Button(btn_frame, text="Delete", command=self.delete_item).pack(side="left")
        tk.Button(btn_frame, text="Refresh", command=self.refresh).pack(side="left")

        # keep reference to PhotoImage to avoid GC
        self.tk_img = None

        self.refresh()

    # ======================================================
    #  THUMBNAIL GENERATION FOR MP4 FILES
    # ======================================================
    def generate_mp4_thumbnail(self, mp4_path: str) -> Optional[str]:
        temp_dir = tempfile.gettempdir()
        local_mp4 = os.path.join(temp_dir, "preview_video.mp4")
        local_jpg = os.path.join(temp_dir, "preview_video.jpg")

        # Clean old files
        for f in [local_mp4, local_jpg]:
            if os.path.exists(f):
                os.remove(f)

        # Pull MP4 file
        if not self.conn.pull_file(mp4_path, local_mp4):
            return None

        # Generate thumbnail using ffmpeg
        cmd = [
            "ffmpeg", "-y",
            "-i", local_mp4,
            "-ss", "00:00:01",
            "-vframes", "1",
            local_jpg
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return local_jpg if os.path.exists(local_jpg) else None

    # ======================================================
    #  PREVIEW FOR JPG/PNG IMAGE FILES
    # ======================================================
    def pull_image(self, img_path: str) -> Optional[str]:
        temp_dir = tempfile.gettempdir()
        local_img = os.path.join(temp_dir, os.path.basename(img_path))

        if os.path.exists(local_img):
            os.remove(local_img)

        if not self.conn.pull_file(img_path, local_img):
            return None

        return local_img if os.path.exists(local_img) else None

    # ======================================================
    #  DISPLAY PREVIEW (VIDEO OR IMAGE)
    # ======================================================
    def preview_file(self, path: str):
        lower = path.lower()

        # VIDEO PREVIEW
        if lower.endswith((".mp4", ".mov", ".m4v")):
            jpg = self.generate_mp4_thumbnail(path)
            if not jpg:
                self.preview_label.config(image="", text="Preview unavailable")
                return

            img = Image.open(jpg)
            img.thumbnail((300, 300))
            self.tk_img = ImageTk.PhotoImage(img)
            self.preview_label.config(image=self.tk_img, text="")
            return

        # IMAGE PREVIEW
        if lower.endswith((".jpg", ".jpeg", ".png", ".bmp", ".gif")):
            local_img = self.pull_image(path)
            if not local_img:
                self.preview_label.config(image="", text="Preview unavailable")
                return

            img = Image.open(local_img)
            img.thumbnail((300, 300))
            self.tk_img = ImageTk.PhotoImage(img)
            self.preview_label.config(image=self.tk_img, text="")
            return

        # OTHER FILES
        self.preview_label.config(image="", text="Select a file for preview")

    # ======================================================
    #  FILE LISTING AND NAVIGATION
    # ======================================================
    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        files = self.conn.list_files(self.current_path)

        for f in files:
            full_path = f"{self.current_path.rstrip('/')}/{f}".replace("//", "/")
            tag = "dir" if self.conn.is_dir(full_path) else "file"
            self.tree.insert("", "end", text=f, values=[full_path], tags=(tag,))

        self.path_label.config(text=self.current_path)

    def on_double_click(self, event):
        item = self.tree.selection()
        if not item:
            return

        full_path = self.tree.item(item[0], "values")[0]

        if self.conn.is_dir(full_path):
            self.current_path = full_path
            self.preview_label.config(image="", text="Select a file for preview")
            self.refresh()
        else:
            self.preview_file(full_path)

    def on_select(self, event):
        item = self.tree.selection()
        if not item:
            return

        full_path = self.tree.item(item[0], "values")[0]
        self.preview_file(full_path)

    def go_up(self):
        if self.current_path == "/":
            return
        self.current_path = "/".join(self.current_path.rstrip("/").split("/")[:-1]) or "/"
        self.preview_label.config(image="", text="Select a file for preview")
        self.refresh()

    # ======================================================
    #  FILE ACTIONS
    # ======================================================
    def upload_file(self):
        filepath = filedialog.askopenfilename()
        if not filepath:
            return
        if self.conn.push(filepath, f"{self.current_path}/"):
            messagebox.showinfo("Upload", "Upload successful")
        else:
            messagebox.showerror("Upload", "Upload failed")
        self.refresh()

    def download_file(self):
        item = self.tree.selection()
        if not item:
            return

        full_path = self.tree.item(item[0], "values")[0]
        savepath = filedialog.asksaveasfilename(initialfile=os.path.basename(full_path))

        if not savepath:
            return

        if self.conn.pull_file(full_path, savepath):
            messagebox.showinfo("Download", "Download successful")
        else:
            messagebox.showerror("Download", "Download failed")

    def delete_item(self):
        item = self.tree.selection()
        if not item:
            return

        full_path = self.tree.item(item[0], "values")[0]

        if messagebox.askyesno("Delete", f"Delete {full_path}?"):
            self.conn.delete(full_path)
            self.refresh()

    def run(self):
        self.window.mainloop()


# ======================================================
# MAIN
# ======================================================
if __name__ == "__main__":
    print("Connecting to LUCI Pin via ADB…")
    conn = ADBLUCIConnection.auto_connect()
    gui = FileBrowserGUI(conn)
    gui.run()
