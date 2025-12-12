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

def add_tooltip(widget, text):
    tip = tk.Toplevel(widget)
    tip.withdraw()
    tip.overrideredirect(True)

    label = tk.Label(
        tip,
        text=text,
        bg="lightyellow",
        relief="solid",
        borderwidth=1,
        padx=6,
        pady=3
    )
    label.pack()

    def show(event):
        tip.geometry(f"+{event.x_root + 10}+{event.y_root + 10}")
        tip.deiconify()

    def hide(event):
        tip.withdraw()

    widget.bind("<Enter>", show)
    widget.bind("<Leave>", hide)



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
        style = ttk.Style()
        style.theme_use("clam")

        # ------------------ BREADCRUMB BAR ------------------
        self.breadcrumb_frame = tk.Frame(self.window, pady=6)
        self.breadcrumb_frame.pack(fill="x")

        # FILE LIST TREE
        self.tree = ttk.Treeview(self.window)
        # Alternate row colors
        self.tree.tag_configure("even", background="#f7f7f7")
        self.tree.tag_configure("odd", background="#ffffff")

        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        # ------------------ RIGHT CLICK MENU ------------------
        self.menu = tk.Menu(self.window, tearoff=0)
        self.menu.add_command(label="Download", command=self.download_file)
        self.menu.add_command(label="Delete", command=self.delete_item)

        def update_breadcrumbs(self):
            # Clear old breadcrumbs
            for widget in self.breadcrumb_frame.winfo_children():
                widget.destroy()

            path = self.current_path.strip("/")

            # Root button
            root_btn = tk.Button(
                self.breadcrumb_frame,
                text="/",
                relief="flat",
                command=lambda p="/": self.navigate_to(p)
            )
            root_btn.pack(side="left")
            add_tooltip(root_btn, "Go to root")

            if not path:
                return

            parts = path.split("/")
            current = ""

            for part in parts:
                current += "/" + part

                sep = tk.Label(self.breadcrumb_frame, text=" > ")
                sep.pack(side="left")

                btn = tk.Button(
                    self.breadcrumb_frame,
                    text=part,
                    relief="flat",
                    command=lambda p=current: self.navigate_to(p)
                )
                btn.pack(side="left")

                add_tooltip(btn, f"Go to {current}")

        def navigate_to(self, path):
            self.current_path = path
            self.preview_label.config(image="", text="Select a file for preview")
            self.refresh()

        def show_menu(event):
            try:
                self.tree.selection_set(self.tree.identify_row(event.y))
                self.menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.menu.grab_release()

        self.tree.bind("<Button-3>", show_menu)

        # PREVIEW AREA
        self.preview_label = tk.Label(self.window, text="Select a file for preview", pady=10)
        self.preview_label.pack()

        # BUTTON BAR
        btn_frame = tk.Frame(self.window, pady=8)
        btn_frame.pack(fill="x")

        up_btn = tk.Button(btn_frame, text="↑ Up", command=self.go_up)
        up_btn.pack(side="left")

        upload_btn = tk.Button(btn_frame, text="Upload", command=self.upload_file)
        upload_btn.pack(side="left")

        download_btn = tk.Button(btn_frame, text="Download", command=self.download_file)
        download_btn.pack(side="left")

        delete_btn = tk.Button(btn_frame, text="Delete", command=self.delete_item)
        delete_btn.pack(side="left")

        refresh_btn = tk.Button(btn_frame, text="Refresh", command=self.refresh)
        refresh_btn.pack(side="left")

        wifi_btn = tk.Button(
            btn_frame,
            text="📡 Connect Hotspot",
            command=self.connect_hotspot
        )
        wifi_btn.pack(side="left")

        add_tooltip(wifi_btn, "Connect LUCI Pin to a Wi-Fi hotspot")
        add_tooltip(up_btn, "Go to parent directory")
        add_tooltip(upload_btn, "Upload a file to this folder")
        add_tooltip(download_btn, "Download selected file")
        add_tooltip(delete_btn, "Delete selected file")
        add_tooltip(refresh_btn, "Reload folder contents")

        # keep reference to PhotoImage to avoid GC
        self.tk_img = None

        self.window.bind("<F5>", lambda e: self.refresh())
        self.window.bind("<Delete>", lambda e: self.delete_item())



        # ------------------ STATUS BAR ------------------
        self.status_var = tk.StringVar(value="Ready")

        self.status_bar = tk.Label(
            self.window,
            textvariable=self.status_var,
            anchor="w",
            bg="#f0f0f0",
            padx=8,
            pady=4
        )
        self.status_bar.pack(fill="x", side="bottom")

        self.refresh()

    def connect_hotspot(self):
        dialog = tk.Toplevel(self.window)
        dialog.title("Connect to Hotspot")
        dialog.geometry("300x180")
        dialog.transient(self.window)
        dialog.grab_set()

        tk.Label(dialog, text="Hotspot SSID:").pack(pady=(10, 0))
        ssid_entry = tk.Entry(dialog)
        ssid_entry.pack(fill="x", padx=20)

        tk.Label(dialog, text="Password:").pack(pady=(10, 0))
        pass_entry = tk.Entry(dialog, show="*")
        pass_entry.pack(fill="x", padx=20)

        def submit():
            ssid = ssid_entry.get().strip()
            password = pass_entry.get().strip()

            if not ssid or not password:
                messagebox.showerror("Error", "SSID and password are required")
                return

            dialog.destroy()
            self.run_hotspot_script(ssid, password)

        tk.Button(dialog, text="Connect", command=submit).pack(pady=15)

    def run_hotspot_script(self, ssid, password):
        self.status_var.set("Connecting to hotspot...")
        self.window.update_idletasks()

        # usb_adb_client.py is in:
        # project_root/setup_connection/USB_connection/
        # We need to go up one level, then into Wireless_connection
        script_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "Wireless_connection",
                "setup_hotspot_connection.py"
            )
        )

        try:
            result = subprocess.run(
                ["python", script_path, ssid, password],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            if result.returncode == 0:
                messagebox.showinfo(
                    "Hotspot Connection",
                    "LUCI Pin successfully connected to hotspot.\n\n"
                    "You can now access the RTSP stream."
                )
                self.status_var.set("Hotspot connected")
            else:
                messagebox.showerror(
                    "Hotspot Connection Failed",
                    result.stderr or result.stdout
                )
                self.status_var.set("Hotspot connection failed")

        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.status_var.set("Hotspot connection error")

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

    def update_breadcrumbs(self):
        # Clear old breadcrumbs
        for widget in self.breadcrumb_frame.winfo_children():
            widget.destroy()

        path = self.current_path.strip("/")

        # Root button
        root_btn = tk.Button(
            self.breadcrumb_frame,
            text="/",
            relief="flat",
            command=lambda p="/": self.navigate_to(p)
        )
        root_btn.pack(side="left")

        if not path:
            return

        parts = path.split("/")
        current = ""

        for part in parts:
            current += "/" + part

            sep = tk.Label(self.breadcrumb_frame, text=" > ")
            sep.pack(side="left")

            btn = tk.Button(
                self.breadcrumb_frame,
                text=part,
                relief="flat",
                command=lambda p=current: self.navigate_to(p)
            )
            btn.pack(side="left")

    def navigate_to(self, path):
        self.current_path = path
        self.preview_label.config(image="", text="Select a file for preview")
        self.refresh()

    # ======================================================
    #  FILE LISTING AND NAVIGATION
    # ======================================================
    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        files = self.conn.list_files(self.current_path)

        for i, f in enumerate(files):
            full_path = f"{self.current_path.rstrip('/')}/{f}".replace("//", "/")
            tag = "dir" if self.conn.is_dir(full_path) else "file"
            icon = "📁" if tag == "dir" else "📄"
            row_tag = "even" if i % 2 == 0 else "odd"
            self.tree.insert("", "end", text=f, values=[full_path], tags=(tag, row_tag))

        self.update_breadcrumbs()

        self.status_var.set("Ready")

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
        self.status_var.set("Uploading file...")
        self.window.update_idletasks()
        filepath = filedialog.askopenfilename()
        if not filepath:
            return
        if self.conn.push(filepath, f"{self.current_path}/"):
            messagebox.showinfo("Upload", "Upload successful")
        else:
            messagebox.showerror("Upload", "Upload failed")
        self.refresh()
        self.status_var.set("Upload complete")

    def download_file(self):
        self.status_var.set("Downloading file...")
        self.window.update_idletasks()
        item = self.tree.selection()
        if not item:
            return

        full_path = self.tree.item(item[0], "values")[0]
        savepath = filedialog.asksaveasfilename(initialfile=os.path.basename(full_path))

        if not savepath:
            return

        if self.conn.pull_file(full_path, savepath):
            messagebox.showinfo("Download", "Download successful")
            self.status_var.set("Download complete")
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