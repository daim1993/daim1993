#!/usr/bin/env python3
"""
SafeCrypt GUI — simple, secure file & folder encryption with a friendly interface.

• AES‑256‑GCM streaming encryption/decryption (authenticity + confidentiality)
• Password‑based key derivation using scrypt
• Choose a single file OR a whole folder (recursive)
• Option to generate a strong code (password) or type your own
• Optional: delete originals after successful encryption
• Progress log + cancel

Build to Windows .exe (from this same folder):
    pip install cryptography pyinstaller
    pyinstaller --onefile --noconsole --name SafeCryptGUI safecrypt_gui.py

Security notes:
- The “code” is your password. If you lose it, data cannot be recovered.
- Prefer generating and storing it in a password manager.
- Test on sample files before running on important data.
"""
from __future__ import annotations

import os
import queue
import random
import string
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.exceptions import InvalidTag

# ====== crypto constants ======
MAGIC = b"PYENC1"   # 6 bytes magic
VERSION = 1          # 1 byte version
SALT_LEN = 16
NONCE_LEN = 12
TAG_LEN = 16
NAME_LEN_FMT = ">H"  # 2‑byte big‑endian unsigned
CHUNK_SIZE = 1024 * 1024  # 1 MiB chunks

class SafeCryptError(Exception):
    pass

# ====== crypto helpers ======

def derive_key(password: str, salt: bytes, length: int = 32) -> bytes:
    if not isinstance(password, str) or not password:
        raise SafeCryptError("Password/code must be a non‑empty string.")
    kdf = Scrypt(salt=salt, length=length, n=2**14, r=8, p=1, backend=default_backend())
    return kdf.derive(password.encode("utf-8"))

def _build_header(orig_name: str, salt: bytes, nonce: bytes) -> bytes:
    name_bytes = orig_name.encode("utf-8")
    if len(name_bytes) > 65535:
        raise SafeCryptError("Filename too long to store in header.")
    return (
        MAGIC + bytes([VERSION]) + salt + nonce + struct.pack(NAME_LEN_FMT, len(name_bytes)) + name_bytes
    )

def _parse_header(f) -> tuple[str, bytes, bytes, bytes]:
    magic = f.read(len(MAGIC))
    if magic != MAGIC:
        raise SafeCryptError("Not a SafeCrypt file (bad magic).")
    ver_b = f.read(1)
    if len(ver_b) != 1:
        raise SafeCryptError("Truncated header (version).")
    version = ver_b[0]
    if version != VERSION:
        raise SafeCryptError(f"Unsupported version: {version} (expected {VERSION}).")
    salt = f.read(SALT_LEN)
    if len(salt) != SALT_LEN:
        raise SafeCryptError("Truncated header (salt).")
    nonce = f.read(NONCE_LEN)
    if len(nonce) != NONCE_LEN:
        raise SafeCryptError("Truncated header (nonce).")
    name_len_b = f.read(struct.calcsize(NAME_LEN_FMT))
    if len(name_len_b) != struct.calcsize(NAME_LEN_FMT):
        raise SafeCryptError("Truncated header (name length).")
    (name_len,) = struct.unpack(NAME_LEN_FMT, name_len_b)
    name_bytes = f.read(name_len)
    if len(name_bytes) != name_len:
        raise SafeCryptError("Truncated header (name bytes).")
    orig_name = name_bytes.decode("utf-8")
    header = MAGIC + bytes([VERSION]) + salt + nonce + name_len_b + name_bytes
    return orig_name, salt, nonce, header

def encrypt_file(src: Path, dst: Optional[Path], password: str, delete_original: bool = False) -> Path:
    if not src.is_file():
        raise SafeCryptError(f"Source is not a file: {src}")
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    key = derive_key(password, salt)
    if dst is None:
        dst = src.with_suffix(src.suffix + ".enc")
    dst.parent.mkdir(parents=True, exist_ok=True)
    header = _build_header(src.name, salt, nonce)

    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce), backend=default_backend())
    encryptor = cipher.encryptor()
    encryptor.authenticate_additional_data(header)

    with src.open("rb") as fin, dst.open("wb") as fout:
        fout.write(header)
        while True:
            chunk = fin.read(CHUNK_SIZE)
            if not chunk:
                break
            ct = encryptor.update(chunk)
            if ct:
                fout.write(ct)
        encryptor.finalize()
        fout.write(encryptor.tag)

    if delete_original:
        try:
            src.unlink()
        except Exception:
            pass
    return dst

def decrypt_file(src: Path, dst: Optional[Path], password: str, overwrite: bool = False) -> Path:
    if not src.is_file():
        raise SafeCryptError(f"Source is not a file: {src}")
    filesize = src.stat().st_size
    with src.open("rb") as fin:
        orig_name, salt, nonce, header = _parse_header(fin)
        header_len = len(header)
        ct_len = filesize - header_len - TAG_LEN
        if ct_len < 0:
            raise SafeCryptError("File is too small or corrupted (no ciphertext/tag).")
        fin.seek(filesize - TAG_LEN)
        tag = fin.read(TAG_LEN)
        if len(tag) != TAG_LEN:
            raise SafeCryptError("Truncated file (tag).")
    key = derive_key(password, salt)
    if dst is None:
        out_path = src.with_name(orig_name)
        if out_path.exists():
            out_path = src.with_name(orig_name + ".dec")
    else:
        out_path = dst
    if out_path.exists() and not overwrite:
        raise SafeCryptError(f"Output exists: {out_path}")

    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag), backend=default_backend())
    decryptor = cipher.decryptor()
    decryptor.authenticate_additional_data(header)

    with src.open("rb") as fin, out_path.open("wb") as fout:
        fin.seek(len(header))
        remaining = ct_len
        try:
            while remaining > 0:
                read_len = min(CHUNK_SIZE, remaining)
                chunk = fin.read(read_len)
                if not chunk:
                    raise SafeCryptError("Unexpected EOF while reading ciphertext.")
                pt = decryptor.update(chunk)
                if pt:
                    fout.write(pt)
                remaining -= len(chunk)
            decryptor.finalize()
        except InvalidTag:
            fout.close()
            try:
                out_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise SafeCryptError("Decryption failed: wrong code or file tampered.")
    return out_path

# ====== util ======

def iter_target_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            yield p

def generate_code(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{}"  # exclude quotes/spaces
    rng = random.SystemRandom()
    return ''.join(rng.choice(alphabet) for _ in range(length))

@dataclass
class Job:
    mode: str  # 'encrypt' or 'decrypt'
    path: Path
    is_dir: bool
    code: str
    delete_original: bool

# ====== GUI ======
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SafeCrypt GUI — AES‑GCM")
        self.geometry("680x480")
        self.minsize(640, 420)

        self.path_var = tk.StringVar()
        self.code_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="encrypt")
        self.target_kind = tk.StringVar(value="file")  # 'file' or 'folder'
        self.delete_var = tk.BooleanVar(value=False)

        self._build_ui()
        self.job_thread: Optional[threading.Thread] = None
        self.cancel_flag = threading.Event()
        self.log_q: queue.Queue[str] = queue.Queue()
        self.after(100, self._drain_log)

    # --- UI layout ---
    def _build_ui(self):
        pad = 10
        # Mode
        mode_frame = ttk.LabelFrame(self, text="Mode")
        mode_frame.pack(fill="x", padx=pad, pady=(pad, 5))
        ttk.Radiobutton(mode_frame, text="Encrypt", value="encrypt", variable=self.mode_var).pack(side="left", padx=8, pady=6)
        ttk.Radiobutton(mode_frame, text="Decrypt", value="decrypt", variable=self.mode_var).pack(side="left", padx=8, pady=6)

        # Target selector
        tgt_frame = ttk.LabelFrame(self, text="Target")
        tgt_frame.pack(fill="x", padx=pad, pady=5)
        row1 = ttk.Frame(tgt_frame)
        row1.pack(fill="x", padx=8, pady=6)
        ttk.Radiobutton(row1, text="File", value="file", variable=self.target_kind).pack(side="left")
        ttk.Radiobutton(row1, text="Folder", value="folder", variable=self.target_kind).pack(side="left", padx=(12,0))
        ttk.Entry(row1, textvariable=self.path_var).pack(side="left", fill="x", expand=True, padx=(12, 8))
        ttk.Button(row1, text="Browse…", command=self.on_browse).pack(side="left")

        # Code (password)
        code_frame = ttk.LabelFrame(self, text="Encryption code (password)")
        code_frame.pack(fill="x", padx=pad, pady=5)
        row2 = ttk.Frame(code_frame)
        row2.pack(fill="x", padx=8, pady=6)
        ttk.Entry(row2, textvariable=self.code_var, show="•").pack(side="left", fill="x", expand=True)
        ttk.Button(row2, text="Show", command=self.toggle_show).pack(side="left", padx=(8,0))
        ttk.Button(row2, text="Generate", command=self.on_generate).pack(side="left", padx=6)
        ttk.Button(row2, text="Copy", command=self.on_copy).pack(side="left")

        # Options
        opt_frame = ttk.LabelFrame(self, text="Options")
        opt_frame.pack(fill="x", padx=pad, pady=5)
        ttk.Checkbutton(opt_frame, text="Delete originals after successful encryption", variable=self.delete_var).pack(side="left", padx=8, pady=6)

        # Actions
        act = ttk.Frame(self)
        act.pack(fill="x", padx=pad, pady=(5,5))
        ttk.Button(act, text="Start", command=self.on_start).pack(side="left")
        ttk.Button(act, text="Cancel", command=self.on_cancel).pack(side="left", padx=6)

        # Log
        log_frame = ttk.LabelFrame(self, text="Progress / Log")
        log_frame.pack(fill="both", expand=True, padx=pad, pady=(5, pad))
        self.log = tk.Text(log_frame, height=14, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=8, pady=8)

    # --- UI callbacks ---
    def on_browse(self):
        if self.target_kind.get() == "file":
            if self.mode_var.get() == "decrypt":
                p = filedialog.askopenfilename(title="Choose encrypted file (.enc)", filetypes=[["Encrypted files","*.enc"],["All","*"]])
            else:
                p = filedialog.askopenfilename(title="Choose file to encrypt")
        else:
            p = filedialog.askdirectory(title="Choose folder")
        if p:
            self.path_var.set(p)

    def toggle_show(self):
        e = [w for w in self.children.values() if isinstance(w, ttk.Labelframe) and w.cget("text")=="Encryption code (password)"][0].winfo_children()[0].winfo_children()[0]
        # ^ slightly hacky: get the Entry widget
        current = e.cget("show")
        e.config(show="" if current else "•")

    def on_generate(self):
        self.code_var.set(generate_code())
        self.log_write("Generated a strong code. Copy it to your password manager.")

    def on_copy(self):
        code = self.code_var.get().strip()
        if not code:
            messagebox.showwarning("Nothing to copy", "Generate or type a code first.")
            return
        self.clipboard_clear()
        self.clipboard_append(code)
        self.log_write("Code copied to clipboard.")

    def on_start(self):
        path_s = self.path_var.get().strip()
        code = self.code_var.get().strip()
        if not path_s:
            messagebox.showerror("No path", "Choose a file or folder first.")
            return
        if not code:
            messagebox.showerror("No code", "Type a code or click Generate.")
            return
        p = Path(path_s)
        job = Job(
            mode=self.mode_var.get(),
            path=p,
            is_dir=(self.target_kind.get()=="folder"),
            code=code,
            delete_original=self.delete_var.get(),
        )
        if self.job_thread and self.job_thread.is_alive():
            messagebox.showinfo("Busy", "A job is already running. Please wait or cancel.")
            return
        self.cancel_flag.clear()
        self.job_thread = threading.Thread(target=self.run_job, args=(job,), daemon=True)
        self.job_thread.start()

    def on_cancel(self):
        if self.job_thread and self.job_thread.is_alive():
            self.cancel_flag.set()
            self.log_write("Cancel requested… finishing current file.")

    # --- background work ---
    def run_job(self, job: Job):
        try:
            if job.mode == "encrypt":
                if job.is_dir:
                    self._encrypt_dir(job)
                else:
                    out = encrypt_file(job.path, None, job.code, delete_original=job.delete_original)
                    self.log_write(f"[OK] Encrypted: {job.path} -> {out}")
            else:
                if job.is_dir:
                    count = 0
                    for f in list(job.path.rglob("*.enc")):
                        if self.cancel_flag.is_set():
                            break
                        try:
                            out = decrypt_file(f, None, job.code, overwrite=False)
                            self.log_write(f"[OK] Decrypted: {f} -> {out}")
                            count += 1
                        except Exception as e:
                            self.log_write(f"[ERROR] {f}: {e}")
                    self.log_write(f"Done. Decrypted {count} file(s).")
                else:
                    out = decrypt_file(job.path, None, job.code, overwrite=False)
                    self.log_write(f"[OK] Decrypted: {job.path} -> {out}")
        except Exception as e:
            self.log_write(f"[ERROR] {e}")

    def _encrypt_dir(self, job: Job):
        root = job.path
        if not root.is_dir():
            raise SafeCryptError("Selected target is not a folder.")
        count = 0
        for f in iter_target_files(root):
            if self.cancel_flag.is_set():
                self.log_write("Canceled by user.")
                break
            # Skip already‑encrypted files by magic detection or .enc suffix
            try:
                if f.suffix == ".enc":
                    self.log_write(f"[SKIP] {f} already has .enc suffix.")
                    continue
                with f.open("rb") as fin:
                    maybe_magic = fin.read(len(MAGIC))
                if maybe_magic == MAGIC:
                    self.log_write(f"[SKIP] {f} looks like a SafeCrypt file.")
                    continue
            except Exception:
                pass
            try:
                out = encrypt_file(f, None, job.code, delete_original=job.delete_original)
                self.log_write(f"[OK] Encrypted: {f} -> {out}")
                count += 1
            except Exception as e:
                self.log_write(f"[ERROR] {f}: {e}")
        self.log_write(f"Done. Encrypted {count} file(s).")

    # --- logging ---
    def log_write(self, text: str):
        self.log_q.put(text)

    def _drain_log(self):
        try:
            while True:
                line = self.log_q.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", line + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(120, self._drain_log)

# ====== main ======
if __name__ == "__main__":
    app = App()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
