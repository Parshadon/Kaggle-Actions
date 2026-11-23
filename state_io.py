"""Encrypted settings/history backup. Media are exported separately, not embedded here."""
import io
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b'PEAKCUT1'


def key(password, salt):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000).derive(password.encode())


def backup(root, destination, password):
    root, destination = Path(root), Path(destination)
    buffer = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for f in root.rglob('*.json'):
            relative = f.relative_to(root)
            if 'tmp' in relative.parts or 'models' in relative.parts or f.is_symlink():
                continue
            total += f.stat().st_size
            if total > 100 * 1024 * 1024:
                raise ValueError('Metadata backup exceeds 100 MB. Download clips and archive your workspace separately.')
            archive.write(f, relative.as_posix())
        database = root / 'peakcut.db'
        if database.exists():
            with tempfile.TemporaryDirectory() as folder:
                snapshot = Path(folder) / 'peakcut.db'
                with sqlite3.connect(database) as source, sqlite3.connect(snapshot) as target:
                    source.backup(target)
                archive.write(snapshot, 'peakcut.db')
    salt, nonce = os.urandom(16), os.urandom(12)
    encrypted = AESGCM(key(password, salt)).encrypt(nonce, buffer.getvalue(), MAGIC)
    destination.write_bytes(MAGIC + salt + nonce + encrypted)


def restore(source, root, password):
    source, root = Path(source), Path(root)
    if (root / 'peakcut.db').exists():
        raise ValueError('Restore requires a fresh workspace. Do not overwrite a running database.')
    payload = source.read_bytes()
    if not payload.startswith(MAGIC):
        raise ValueError('Not a PeakCut encrypted backup')
    plain = AESGCM(key(password, payload[8:24])).decrypt(payload[24:36], payload[36:], MAGIC)
    with zipfile.ZipFile(io.BytesIO(plain)) as archive:
        if sum(i.file_size for i in archive.infolist()) > 120 * 1024 * 1024:
            raise ValueError('Backup is too large')
        for item in archive.infolist():
            target = (root / item.filename).resolve()
            if not target.is_relative_to(root.resolve()) or item.is_dir():
                raise ValueError('Invalid backup path')
            if target.suffix != '.json' and item.filename != 'peakcut.db':
                raise ValueError('Unexpected backup file')
        for item in archive.infolist():
            target = root / item.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(item))


if __name__ == '__main__':
    import sys
    password = os.environ['PEAKCUT_OWNER_PASSWORD']
    if sys.argv[1] == 'backup':
        backup(sys.argv[2], sys.argv[3], password)
    elif sys.argv[1] == 'restore':
        restore(sys.argv[2], sys.argv[3], password)
