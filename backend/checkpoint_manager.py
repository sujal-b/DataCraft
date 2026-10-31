"""
Checkpoint Manager: file-based snapshot system for dataset rollback.
P1-3: stores copies under backend/data/checkpoints/{dataset_name}/ — OUTSIDE the
statically served public/ root, so pre-cleaning snapshots are not publicly
downloadable. Pool cap: 500 MB total. Pruning is surfaced to the caller.
"""
import os
import shutil
import json
from datetime import datetime, timezone
from typing import List, Dict, Optional

import config

CHECKPOINTS_ROOT = config.CHECKPOINTS_DIR
MAX_POOL_MB = 500
MAX_FILE_MB = 100  # individual dataset file must be < 100 MB to checkpoint


def _checkpoint_dir(dataset_name: str) -> str:
    return os.path.join(CHECKPOINTS_ROOT, dataset_name)


def _meta_path(dataset_name: str) -> str:
    return os.path.join(_checkpoint_dir(dataset_name), '_meta.json')


def _load_meta(dataset_name: str) -> List[Dict]:
    path = _meta_path(dataset_name)
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return []


def _save_meta(dataset_name: str, entries: List[Dict]):
    path = _meta_path(dataset_name)
    os.makedirs(_checkpoint_dir(dataset_name), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(entries, f, indent=2)


def get_pool_size_mb() -> float:
    """Total MB used by all checkpoints across all datasets."""
    total = 0
    if not os.path.exists(CHECKPOINTS_ROOT):
        return 0.0
    for root, _, files in os.walk(CHECKPOINTS_ROOT):
        for fname in files:
            if fname == '_meta.json':
                continue
            try:
                total += os.path.getsize(os.path.join(root, fname))
            except OSError:
                pass
    return total / (1024 * 1024)


def create_checkpoint(dataset_name: str, file_path: str, batch_label: str = '') -> Optional[Dict]:
    """
    Copy file_path into checkpoints/{dataset_name}/{checkpoint_id}.csv.
    Returns checkpoint metadata dict, or None if file too large / pool full.
    """
    if not os.path.exists(file_path):
        return None

    file_mb = os.path.getsize(file_path) / (1024 * 1024)
    if file_mb > MAX_FILE_MB:
        return {'error': f'File too large ({file_mb:.1f} MB > {MAX_FILE_MB} MB limit). Checkpoint skipped.'}

    pool_mb = get_pool_size_mb()
    if pool_mb + file_mb > MAX_POOL_MB:
        return {'error': f'Checkpoint pool full ({pool_mb:.1f} MB used). Delete old checkpoints first.', 'pool_mb': pool_mb}

    os.makedirs(_checkpoint_dir(dataset_name), exist_ok=True)
    checkpoint_id = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')[:22]
    dest = os.path.join(_checkpoint_dir(dataset_name), f'{checkpoint_id}.csv')
    shutil.copy2(file_path, dest)

    entry = {
        'checkpoint_id': checkpoint_id,
        'dataset_name': dataset_name,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'file_size_mb': round(file_mb, 3),
        'batch_label': batch_label or f'Batch {checkpoint_id}',
        'file_path': dest,
    }
    meta = _load_meta(dataset_name)
    meta.append(entry)
    _save_meta(dataset_name, meta)
    return entry


def list_checkpoints(dataset_name: str) -> List[Dict]:
    """Return all checkpoints for a dataset, newest first."""
    meta = _load_meta(dataset_name)
    # Verify files still exist
    valid = [e for e in meta if os.path.exists(e.get('file_path', ''))]
    if len(valid) != len(meta):
        _save_meta(dataset_name, valid)
    return list(reversed(valid))


def restore_checkpoint(dataset_name: str, checkpoint_id: str, dest_path: str) -> Dict:
    """Copy checkpoint file back to dest_path (the live dataset path)."""
    meta = _load_meta(dataset_name)
    entry = next((e for e in meta if e['checkpoint_id'] == checkpoint_id), None)
    if not entry:
        return {'success': False, 'error': 'Checkpoint not found.'}
    if not os.path.exists(entry['file_path']):
        return {'success': False, 'error': 'Checkpoint file missing from disk.'}
    shutil.copy2(entry['file_path'], dest_path)
    return {'success': True, 'checkpoint_id': checkpoint_id, 'restored_to': dest_path}


def delete_checkpoint(dataset_name: str, checkpoint_id: str) -> Dict:
    """Delete a single checkpoint file and remove from metadata."""
    meta = _load_meta(dataset_name)
    entry = next((e for e in meta if e['checkpoint_id'] == checkpoint_id), None)
    if not entry:
        return {'success': False, 'error': 'Checkpoint not found.'}
    try:
        if os.path.exists(entry['file_path']):
            os.remove(entry['file_path'])
        updated = [e for e in meta if e['checkpoint_id'] != checkpoint_id]
        _save_meta(dataset_name, updated)
        return {'success': True, 'deleted': checkpoint_id}
    except Exception as ex:
        return {'success': False, 'error': str(ex)}


def delete_all_checkpoints(dataset_name: str) -> Dict:
    """Wipe entire checkpoint dir for a dataset."""
    cdir = _checkpoint_dir(dataset_name)
    if os.path.exists(cdir):
        shutil.rmtree(cdir)
    return {'success': True, 'dataset': dataset_name}
