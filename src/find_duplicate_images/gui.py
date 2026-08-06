import csv
import logging
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from find_duplicate_images.scanner import DuplicateScanner

logger = logging.getLogger(__name__)

# ============ COLOR PALETTE ============
# Dracula (https://draculatheme.com/contribute) — the official 8-color spec,
# extended with tinted hover/soft/border variants derived from those same
# hues. Only the "clam" ttk theme honors custom colors consistently across
# platforms — the native themes (vista, aqua, winnative) ignore most
# style.configure() calls.
BG = "#282A36"  # Dracula background — window background
SURFACE = "#343746"  # elevated card interiors (canvas, listbox, treeview)
ROW_ALT = "#2C2E3B"  # zebra stripe for alternating result groups
INSET = "#1E1F29"  # recessed surfaces (progress trough)
BORDER = "#44475A"  # Dracula "Current Line" — reused as border/divider/hover
TEXT = "#F8F8F2"  # Dracula foreground
TEXT_MUTED = "#9AA3D1"  # lightened Dracula comment — the stock #6272A4 reads
# fine over syntax-highlighted code but is too low-contrast for UI chrome
# (group titles, chip buttons) sitting on the lighter SURFACE tone.
ACCENT = "#BD93F9"  # Dracula purple
ACCENT_TEXT = "#1E1F29"  # dark text for legibility on the pastel accent fill
ACCENT_HOVER = "#CBA6FA"
ACCENT_ACTIVE = "#A177E0"
ACCENT_SOFT = "#3B3856"  # dark purple-tinted panel (selection, chip hover)
ACCENT_DISABLED = "#4B4D5C"
SUCCESS = "#50FA7B"  # Dracula green
WARNING = "#FFB86C"  # Dracula orange
WARNING_BORDER = "#8A6239"
WARNING_SOFT = "#4A3B2A"
DANGER = "#FF5555"  # Dracula red
DANGER_SOFT = "#4A2A2A"
DANGER_BORDER = "#7A3A3A"
SCROLL_ACTIVE = "#565979"

_STATUS_COLORS = {
    "default": TEXT_MUTED,
    "scanning": ACCENT,
    "success": SUCCESS,
    "cancelled": WARNING,
    "error": DANGER,
}


def _pick_font(root):
    """Prefer a clean humanist sans, falling back to whatever the platform has."""
    available = set(tkfont.families(root))
    for name in (
        "Segoe UI",
        "SF Pro Text",
        "Helvetica Neue",
        "Inter",
        "Ubuntu",
        "Noto Sans",
    ):
        if name in available:
            return name
    return "TkDefaultFont"


def _files(count):
    """Pluralize a file count for group labels."""
    return f"{count} file" if count == 1 else f"{count} files"


def _bind_mousewheel(widget, canvas):
    """
    Make the wheel scroll `canvas` while the pointer is anywhere over `widget`
    or its descendants.

    Tk does not bubble events to parents, so every child needs its own binding.
    X11 reports the wheel as Button-4/5; Windows and macOS use MouseWheel.
    """

    def on_wheel(event):
        if event.num == 4:
            canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            canvas.yview_scroll(1, "units")
        else:
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    widget.bind("<MouseWheel>", on_wheel)
    widget.bind("<Button-4>", on_wheel)
    widget.bind("<Button-5>", on_wheel)
    for child in widget.winfo_children():
        _bind_mousewheel(child, canvas)


class DuplicateImageFinderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Duplicate Image Finder")
        self.root.geometry("1150x900")
        # Below this the format panel gets shorter than a single group box.
        self.root.minsize(900, 700)
        self.root.configure(bg=BG)

        self.font_family = _pick_font(root)
        self.font = (self.font_family, 10)
        self.font_bold = (self.font_family, 10, "bold")
        self.font_header = (self.font_family, 11, "bold")
        self.font_small = (self.font_family, 9)
        self.font_small_bold = (self.font_family, 9, "bold")

        self.scanner = DuplicateScanner()
        self.scan_thread = None
        self.selected_paths = []
        self.format_vars = {}

        self._setup_style()
        self.setup_ui()

    # ============ STYLE ============
    def _setup_style(self):
        """Configure a flat, modern ttk theme. 'clam' is the only built-in
        theme that actually applies custom colors on every platform."""
        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure(".", background=BG, foreground=TEXT, font=self.font)
        style.configure("TFrame", background=BG)
        style.configure("Surface.TFrame", background=SURFACE)

        style.configure("TLabel", background=BG, foreground=TEXT, font=self.font)
        style.configure(
            "Muted.TLabel", background=BG, foreground=TEXT_MUTED, font=self.font_small
        )
        style.configure(
            "Header.TLabel", background=BG, foreground=TEXT, font=self.font_header
        )

        style.configure(
            "TLabelframe",
            background=BG,
            bordercolor=BORDER,
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "TLabelframe.Label",
            background=BG,
            foreground=TEXT_MUTED,
            font=self.font_bold,
        )
        style.configure(
            "Surface.TLabelframe",
            background=SURFACE,
            bordercolor=BORDER,
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "Surface.TLabelframe.Label",
            background=SURFACE,
            foreground=TEXT_MUTED,
            font=self.font_small_bold,
        )

        style.configure("TCheckbutton", background=BG, foreground=TEXT, font=self.font)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure(
            "Surface.TCheckbutton", background=SURFACE, foreground=TEXT, font=self.font
        )
        style.map("Surface.TCheckbutton", background=[("active", SURFACE)])

        # Secondary (default) button — used for every non-primary action.
        style.configure(
            "TButton",
            background=SURFACE,
            foreground=TEXT,
            font=self.font,
            borderwidth=1,
            bordercolor=BORDER,
            focuscolor=BG,
            padding=(10, 6),
        )
        style.map(
            "TButton",
            # Hover lightens rather than darkens — the opposite of the light-theme
            # direction, since BORDER is a lighter tone than SURFACE here.
            background=[("active", BORDER), ("disabled", SURFACE)],
            foreground=[("disabled", TEXT_MUTED)],
            bordercolor=[("focus", ACCENT), ("disabled", BORDER)],
        )

        # Primary action — Start Scan. Dracula's accent hues are pastel and
        # light, so a dark foreground reads far better on them than white.
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground=ACCENT_TEXT,
            font=self.font_bold,
            borderwidth=0,
            padding=(14, 7),
        )
        style.map(
            "Accent.TButton",
            background=[
                ("disabled", ACCENT_DISABLED),
                ("pressed", ACCENT_ACTIVE),
                ("active", ACCENT_HOVER),
            ],
            foreground=[("disabled", ACCENT_TEXT)],
        )

        # Stop Scan — a subdued warning tone, not a destructive-red button.
        style.configure(
            "Warning.TButton",
            background=SURFACE,
            foreground=WARNING,
            font=self.font,
            borderwidth=1,
            bordercolor=WARNING_BORDER,
            padding=(10, 6),
        )
        style.map(
            "Warning.TButton",
            background=[("active", WARNING_SOFT), ("disabled", SURFACE)],
            foreground=[("disabled", TEXT_MUTED)],
            bordercolor=[("disabled", BORDER)],
        )

        # Small "chip" buttons for the quick format-select row.
        style.configure(
            "Chip.TButton",
            background=SURFACE,
            foreground=TEXT_MUTED,
            font=self.font_small,
            borderwidth=1,
            bordercolor=BORDER,
            padding=(8, 3),
        )
        style.map(
            "Chip.TButton",
            background=[("active", ACCENT_SOFT)],
            foreground=[("active", ACCENT)],
        )

        style.configure(
            "Horizontal.TProgressbar",
            troughcolor=INSET,
            background=ACCENT,
            bordercolor=INSET,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            thickness=14,
        )

        style.configure(
            "Treeview",
            background=SURFACE,
            fieldbackground=SURFACE,
            foreground=TEXT,
            font=self.font,
            rowheight=26,
            borderwidth=0,
            relief="flat",
        )
        style.configure(
            "Treeview.Heading",
            background=BG,
            foreground=TEXT_MUTED,
            font=self.font_bold,
            relief="flat",
            borderwidth=1,
        )
        style.map("Treeview.Heading", background=[("active", BG)])
        style.map(
            "Treeview",
            background=[("selected", ACCENT_SOFT)],
            foreground=[("selected", TEXT)],
        )

        for orient in ("Vertical", "Horizontal"):
            style.configure(
                f"{orient}.TScrollbar",
                background=BORDER,
                troughcolor=BG,
                bordercolor=BG,
                arrowcolor=TEXT_MUTED,
                relief="flat",
            )
            style.map(f"{orient}.TScrollbar", background=[("active", SCROLL_ACTIVE)])

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="16")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        # Formats (row 1) and results (row 4) both absorb extra height, with the
        # results list getting the larger share.
        main_frame.rowconfigure(1, weight=1)
        main_frame.rowconfigure(4, weight=2)

        path_frame = ttk.LabelFrame(main_frame, text="📁  Scan Locations", padding="12")
        path_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        path_frame.columnconfigure(0, weight=1)

        # Path listbox
        self.path_listbox = tk.Listbox(
            path_frame,
            height=4,
            selectmode=tk.EXTENDED,
            bg=SURFACE,
            fg=TEXT,
            selectbackground=ACCENT,
            selectforeground=ACCENT_TEXT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            font=self.font,
        )
        self.path_listbox.grid(
            row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 8)
        )

        # Scrollbar
        scrollbar = ttk.Scrollbar(
            path_frame, orient=tk.VERTICAL, command=self.path_listbox.yview
        )
        scrollbar.grid(row=0, column=2, sticky=(tk.N, tk.S))
        self.path_listbox.config(yscrollcommand=scrollbar.set)

        # Buttons
        btn_frame = ttk.Frame(path_frame)
        btn_frame.grid(row=1, column=0, columnspan=3, pady=(8, 0), sticky=tk.W)

        ttk.Button(btn_frame, text="➕  Add Drive/Folder", command=self.add_path).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(
            btn_frame, text="➖  Remove Selected", command=self.remove_path
        ).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_frame, text="✕  Clear All", command=self.clear_paths).pack(
            side=tk.LEFT, padx=6
        )

        # ============ FORMAT SELECTION ============
        format_frame = ttk.LabelFrame(
            main_frame, text="🗂️  File Formats to Scan", padding="12"
        )
        format_frame.grid(
            row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 12)
        )
        format_frame.columnconfigure(0, weight=1)
        format_frame.rowconfigure(0, weight=1)

        # Create a scrollable canvas
        format_canvas = tk.Canvas(
            format_frame, height=320, highlightthickness=0, bg=SURFACE
        )
        format_scrollbar = ttk.Scrollbar(
            format_frame, orient="vertical", command=format_canvas.yview
        )
        format_scrollable_frame = ttk.Frame(format_canvas, style="Surface.TFrame")

        canvas_window = format_canvas.create_window(
            (0, 0), window=format_scrollable_frame, anchor="nw"
        )
        format_canvas.configure(yscrollcommand=format_scrollbar.set)

        def sync_scrollregion(_event=None):
            format_canvas.configure(scrollregion=format_canvas.bbox("all"))

        def sync_width(event):
            # Stretch the inner frame to the canvas width, otherwise the columns
            # bunch up on the left and leave the panel looking cramped.
            format_canvas.itemconfigure(canvas_window, width=event.width)
            # Changing the width re-flows the rows, so the scrollregion has to be
            # recomputed after that settles or the last row stays unreachable.
            format_canvas.after_idle(sync_scrollregion)

        format_scrollable_frame.bind("<Configure>", sync_scrollregion)
        format_canvas.bind("<Configure>", sync_width)

        # Define format groups
        format_groups = {
            "Standard": [
                ".jpg",
                ".jpeg",
                ".png",
                ".gif",
                ".bmp",
                ".tiff",
                ".tif",
                ".webp",
            ],
            "RAW - Canon": [".crw", ".cr2", ".cr3"],
            "RAW - Nikon": [".nef", ".nrw"],
            "RAW - Sony": [".arw", ".srf", ".sr2"],
            "RAW - Fuji": [".raf", ".fef"],
            "RAW - Olympus": [".orf", ".ori"],
            "RAW - Panasonic": [".rw2", ".raw"],
            "RAW - Pentax": [".pef", ".ptx"],
            "RAW - Leica": [".dng"],
            "RAW - Hasselblad": [".3fr", ".fff"],
            "RAW - Sigma": [".x3f"],
            "RAW - Phase One": [".iiq"],
            "RAW - Samsung": [".srw"],
            "RAW - Kodak": [".kdc", ".dcr"],
            "RAW - Minolta": [".mrw"],
            "RAW - Epson": [".erf"],
            "RAW - Mamiya": [".mef"],
            "Apple": [".heic", ".heif"],
            "Adobe": [".psd", ".psb"],
            "Vector": [".svg", ".svgz"],
            "Other": [".avif", ".exr", ".hdr", ".ppm", ".pcx", ".ico", ".dcm"],
        }

        # Create checkboxes
        format_columns = 6
        for idx, (group_name, extensions) in enumerate(format_groups.items()):
            group_frame = ttk.LabelFrame(
                format_scrollable_frame,
                text=group_name,
                padding="6",
                style="Surface.TLabelframe",
            )
            # sticky N keeps each box at its natural height instead of stretching
            # short groups to match the tallest one in the row.
            group_frame.grid(
                row=idx // format_columns,
                column=idx % format_columns,
                padx=4,
                pady=4,
                sticky=(tk.N, tk.W, tk.E),
            )

            for ext in extensions:
                var = tk.BooleanVar(value=True)
                self.format_vars[ext] = var
                cb = ttk.Checkbutton(
                    group_frame, text=ext, variable=var, style="Surface.TCheckbutton"
                )
                cb.pack(anchor=tk.W)

        # No uniform= here on purpose: it would pad every column out to the
        # widest group box and push the grid wider than the window.
        for col in range(format_columns):
            format_scrollable_frame.columnconfigure(col, weight=1)

        # Pack the canvas
        format_canvas.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        format_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        # Bind the wheel across the whole subtree: the pointer is usually over a
        # checkbutton, not the canvas, and events do not bubble up in Tk.
        _bind_mousewheel(format_canvas, format_canvas)

        # Quick selection buttons
        quick_btn_frame = ttk.Frame(format_frame)
        quick_btn_frame.grid(row=1, column=0, pady=(8, 0), sticky=tk.W)

        ttk.Button(
            quick_btn_frame,
            text="Select All",
            command=self.select_all_formats,
            style="Chip.TButton",
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            quick_btn_frame,
            text="Select Standard",
            command=self.select_standard_formats,
            style="Chip.TButton",
        ).pack(side=tk.LEFT, padx=6)
        ttk.Button(
            quick_btn_frame,
            text="Select RAW Only",
            command=self.select_raw_formats,
            style="Chip.TButton",
        ).pack(side=tk.LEFT, padx=6)
        ttk.Button(
            quick_btn_frame,
            text="Deselect All",
            command=self.deselect_all_formats,
            style="Chip.TButton",
        ).pack(side=tk.LEFT, padx=6)

        # ============ CONTROL BUTTONS ============
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=2, column=0, pady=12)

        self.scan_btn = ttk.Button(
            control_frame,
            text="▶  Start Scan",
            command=self.start_scan,
            style="Accent.TButton",
        )
        self.scan_btn.pack(side=tk.LEFT, padx=6)

        self.stop_btn = ttk.Button(
            control_frame,
            text="⏹  Stop Scan",
            command=self.stop_scan,
            state=tk.DISABLED,
            style="Warning.TButton",
        )
        self.stop_btn.pack(side=tk.LEFT, padx=6)

        ttk.Button(
            control_frame, text="💾  Export Results", command=self.export_results
        ).pack(side=tk.LEFT, padx=6)

        # ============ PROGRESS BAR ============
        progress_frame = ttk.LabelFrame(main_frame, text="📊  Progress", padding="12")
        progress_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        progress_frame.columnconfigure(0, weight=1)

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            progress_frame, variable=self.progress_var, maximum=100
        )
        self.progress_bar.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 8))

        self.status_label = ttk.Label(progress_frame, text="Ready", font=self.font)
        self.status_label.grid(row=1, column=0, sticky=tk.W)
        self._set_status("Ready", "default")

        self.file_label = ttk.Label(progress_frame, text="", style="Muted.TLabel")
        self.file_label.grid(row=2, column=0, sticky=tk.W, pady=(2, 0))

        # ============ RESULTS AREA ============
        results_frame = ttk.LabelFrame(
            main_frame, text="🔍  Duplicates Found", padding="12"
        )
        results_frame.grid(row=4, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)

        # Treeview
        # The tree column (#0) carries the group label, so it is not repeated here.
        columns = ("Name", "Folder", "Size (MB)")
        self.tree = ttk.Treeview(
            results_frame, columns=columns, show="tree headings", height=12
        )
        self.tree.heading("#0", text="Group")
        self.tree.heading("Name", text="File Name")
        self.tree.heading("Folder", text="Folder")
        self.tree.heading("Size (MB)", text="Size (MB)")
        self.tree.column("#0", width=160)
        self.tree.column("Name", width=220)
        self.tree.column("Folder", width=420)
        self.tree.column("Size (MB)", width=90, anchor=tk.E)

        # Subtle zebra striping between groups, applied in populate_results().
        self.tree.tag_configure("group-odd", background=SURFACE)
        self.tree.tag_configure("group-even", background=ROW_ALT)

        tree_scrollbar = ttk.Scrollbar(
            results_frame, orient=tk.VERTICAL, command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=tree_scrollbar.set)

        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        tree_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

    def _set_status(self, text, kind="default"):
        """Update the status line with a color that reflects scan state."""
        self.status_label.configure(
            text=text, foreground=_STATUS_COLORS.get(kind, TEXT_MUTED)
        )

    # ============ PATH METHODS ============
    def add_path(self):
        """Add a folder/drive to the scan list."""
        path = filedialog.askdirectory(title="Select Drive or Folder to Scan")
        if path and path not in self.selected_paths:
            self.selected_paths.append(path)
            self.path_listbox.insert(tk.END, path)

    def remove_path(self):
        """Remove selected paths from the scan list."""
        selected = self.path_listbox.curselection()
        for index in reversed(selected):
            del self.selected_paths[index]
            self.path_listbox.delete(index)

    def clear_paths(self):
        """Clear all paths from the scan list."""
        self.selected_paths.clear()
        self.path_listbox.delete(0, tk.END)

    # ============ FORMAT METHODS ============
    def get_selected_formats(self):
        """Get list of selected format extensions."""
        return [ext for ext, var in self.format_vars.items() if var.get()]

    def select_all_formats(self):
        """Select all formats."""
        for var in self.format_vars.values():
            var.set(True)

    def deselect_all_formats(self):
        """Deselect all formats."""
        for var in self.format_vars.values():
            var.set(False)

    def select_standard_formats(self):
        """Select only standard formats (JPG, PNG, GIF, etc.)."""
        self.deselect_all_formats()
        standard = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp"]
        for ext in standard:
            if ext in self.format_vars:
                self.format_vars[ext].set(True)

    def select_raw_formats(self):
        """Select only RAW formats."""
        self.deselect_all_formats()
        raw_extensions = [
            ".crw",
            ".cr2",
            ".cr3",  # Canon
            ".nef",
            ".nrw",  # Nikon
            ".arw",
            ".srf",
            ".sr2",  # Sony
            ".raf",
            ".fef",  # Fuji
            ".orf",
            ".ori",  # Olympus
            ".rw2",
            ".raw",  # Panasonic
            ".pef",
            ".ptx",  # Pentax
            ".dng",  # Leica
            ".3fr",
            ".fff",  # Hasselblad
            ".x3f",  # Sigma
            ".iiq",  # Phase One
            ".srw",  # Samsung
            ".kdc",
            ".dcr",  # Kodak
            ".mrw",  # Minolta
            ".erf",  # Epson
            ".mef",  # Mamiya
        ]
        for ext in raw_extensions:
            if ext in self.format_vars:
                self.format_vars[ext].set(True)

    # ============ SCAN METHODS ============
    def start_scan(self):
        """Start the duplicate scan."""
        if not self.selected_paths:
            messagebox.showwarning(
                "No Paths", "Please add at least one drive or folder to scan."
            )
            return

        selected_formats = self.get_selected_formats()
        if not selected_formats:
            messagebox.showwarning(
                "No Formats", "Please select at least one file format to scan."
            )
            return

        # Update scanner with selected formats
        self.scanner.file_extension = set(selected_formats)

        # Clear previous results
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Update UI
        self.scan_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.progress_var.set(0)
        self._set_status(f"Scanning {len(selected_formats)} formats...", "scanning")
        self.file_label.config(text="")

        # Start scan in background thread
        self.scan_thread = threading.Thread(target=self.scan_worker, daemon=True)
        self.scan_thread.start()

    def scan_worker(self):
        """Worker function that runs the scan in a background thread."""
        last_update = 0.0

        def progress_callback(current, total, filepath):
            # Throttle to ~20 updates/sec. Queueing one callback per file would
            # flood the Tk event loop and lock the UI on a large drive.
            nonlocal last_update
            now = time.monotonic()
            if current == total or now - last_update >= 0.05:
                last_update = now
                self.root.after(0, self.update_progress, current, total, filepath)

        try:
            duplicates = self.scanner.scan_drive(self.selected_paths, progress_callback)
            self.root.after(0, self.scan_complete, duplicates)
        except Exception as e:
            # Nothing propagates out of a worker thread, so log here or the
            # traceback is lost and only the dialog text survives.
            logger.exception("Scan failed")
            self.root.after(0, self.scan_error, str(e))

    def update_progress(self, current, total, filepath):
        """Update the progress bar and status text."""
        if total > 0:
            progress = (current / total) * 100
            self.progress_var.set(progress)
            self._set_status(f"Scanning... {current}/{total} files", "scanning")
            # Truncate long paths
            display_path = filepath if len(filepath) <= 80 else "..." + filepath[-77:]
            self.file_label.config(text=display_path)

    def scan_complete(self, duplicates):
        """Handle scan completion."""
        self.scan_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.file_label.config(text="")

        # Partial results are still results, so a cancelled scan lists whatever
        # it confirmed before stopping.
        self.populate_results(duplicates)
        count = len(duplicates)

        if self.scanner.cancel_scan:
            self.progress_var.set(0)
            self._set_status(
                f"Scan cancelled — {count} duplicate groups found so far", "cancelled"
            )
            messagebox.showinfo(
                "Scan Cancelled",
                f"Scan stopped early.\n\nListing {count} duplicate groups found "
                "before you cancelled. Run a full scan to find the rest.",
            )
            return

        self.progress_var.set(100)
        self._set_status(f"Scan complete! Found {count} duplicate groups", "success")

        if duplicates:
            messagebox.showinfo("Scan Complete", f"Found {count} duplicate groups!")
        else:
            messagebox.showinfo("Scan Complete", "No duplicates found!")

    def populate_results(self, duplicates):
        """List each duplicate group in the results tree."""
        for group_idx, file_group in enumerate(duplicates, 1):
            tag = "group-even" if group_idx % 2 == 0 else "group-odd"
            parent = self.tree.insert(
                "",
                "end",
                text=f"Group {group_idx} ({_files(len(file_group))})",
                open=True,
                tags=(tag,),
            )
            for filepath in file_group:
                path = Path(filepath)
                try:
                    size = f"{path.stat().st_size / (1024 * 1024):.2f}"
                except OSError:
                    size = "N/A"
                self.tree.insert(
                    parent,
                    "end",
                    values=(path.name, str(path.parent), size),
                    tags=(tag,),
                )

    def scan_error(self, error_message):
        """Handle scan errors."""
        self.scan_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self._set_status("Error during scan", "error")
        messagebox.showerror(
            "Scan Error", f"An error occurred during scanning:\n\n{error_message}"
        )

    def stop_scan(self):
        """Stop the current scan."""
        self.scanner.stop_scan()
        self._set_status("Stopping scan...", "cancelled")
        self.stop_btn.config(state=tk.DISABLED)

    # ============ RESULT METHODS ============
    def export_results(self):
        """Export scan results to a file."""
        filepath = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[
                ("Text files", "*.txt"),
                ("CSV files", "*.csv"),
                ("All files", "*.*"),
            ],
        )
        if not filepath:
            return

        try:
            if Path(filepath).suffix.lower() == ".csv":
                self._export_csv(filepath)
            else:
                self._export_text(filepath)
            messagebox.showinfo("Export Complete", f"Results exported to {filepath}")
        except OSError as e:
            messagebox.showerror("Export Error", f"Could not export: {e}")

    def _export_text(self, filepath):
        """Write results as a human-readable report."""
        # encoding is explicit: image paths often contain non-ASCII characters,
        # and the platform default (cp1252 on Windows) would raise on them.
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("Duplicate Image Groups\n")
            f.write("=" * 50 + "\n\n")

            for group in self.tree.get_children():
                f.write(f"{self.tree.item(group, 'text')}\n")
                f.write("-" * 30 + "\n")

                for child in self.tree.get_children(group):
                    name, folder, size = self.tree.item(child, "values")
                    f.write(f"  {name}  ({size} MB)\n")
                    f.write(f"      in {folder}\n")
                f.write("\n")

    def _export_csv(self, filepath):
        """Write results as CSV, one row per duplicate file."""
        with open(filepath, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Group", "File Name", "Folder", "Full Path", "Size (MB)"])
            for group_idx, group in enumerate(self.tree.get_children(), 1):
                for child in self.tree.get_children(group):
                    name, folder, size = self.tree.item(child, "values")
                    full = str(Path(folder) / name)
                    writer.writerow([group_idx, name, folder, full, size])


# ============ MAIN ENTRY POINT ============
def main():
    """Main function to start the application."""
    # Create the root window
    root = tk.Tk()

    # Create the application
    DuplicateImageFinderGUI(root)

    # Start the GUI event loop
    root.mainloop()


# This is the entry point - runs when you execute the file directly
if __name__ == "__main__":
    main()
