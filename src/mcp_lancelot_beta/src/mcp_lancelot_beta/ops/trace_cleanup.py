"""Trace retention cleanup for mcp-lancelot-beta (decision Q7: keep 30 days).

Deletes day folders whose date is older than the retention window from
<volume>/runs/ (server traces) and <volume>/client-runs/ (lancelot-client
results; client decision D11). Runs as a scheduled Databricks job
("mcp-lancelot-beta trace cleanup"); see ARCHITECTURE.md section 11.

Safety rules:
  * Only touches <volume>/<subdir>/<YYYY-MM-DD>/ folders, where <subdir> is
    one of ALLOWED_SUBDIRS. Anything else (latest/, client-runs/latest/,
    files, folders with other names) is left alone and reported.
  * A missing <subdir> is reported and skipped, not an error.
  * The day folder's date (from its name) must be strictly older than
    today - keep_days (UTC). Today's and recent folders are never deleted.
  * --dry-run lists what would be deleted without deleting anything.

Usage (job parameters):
  trace_cleanup.py [--volume /Volumes/users/tom_jacobson/lancelot_traces]
                   [--keep-days 30] [--subdir runs --subdir client-runs]
                   [--dry-run]
  Default subdirs: runs and client-runs.
"""
import argparse
import datetime as dt
import re
import sys

DEFAULT_VOLUME = "/Volumes/users/tom_jacobson/lancelot_traces"
DEFAULT_KEEP_DAYS = 30
# Only these top-level folders may ever be cleaned. latest/ is never cleaned.
ALLOWED_SUBDIRS = ("runs", "client-runs")
DAY_FOLDER = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def select_expired(names, today, keep_days):
    """Split folder names under runs/ into (expired, kept, ignored).

    expired: valid YYYY-MM-DD names strictly older than today - keep_days
    kept:    valid day names inside the retention window
    ignored: names that are not a valid day folder (never deleted)
    """
    if keep_days < 1:
        raise ValueError("keep_days must be at least 1")
    cutoff = today - dt.timedelta(days=keep_days)
    expired, kept, ignored = [], [], []
    for name in sorted(names):
        if not DAY_FOLDER.match(name):
            ignored.append(name)
            continue
        try:
            day = dt.date.fromisoformat(name)
        except ValueError:
            ignored.append(name)
            continue
        (expired if day < cutoff else kept).append(name)
    return expired, kept, ignored


def _children(w, path):
    return list(w.files.list_directory_contents(path))


def _delete_tree(w, path):
    """Delete a volume directory and everything under it. Returns file count."""
    count = 0
    for entry in _children(w, path):
        child = entry.path.rstrip("/")
        if entry.is_directory:
            count += _delete_tree(w, child)
        else:
            w.files.delete(child)
            count += 1
    w.files.delete_directory(path)
    return count


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--volume", default=DEFAULT_VOLUME)
    parser.add_argument("--keep-days", type=int, default=DEFAULT_KEEP_DAYS)
    parser.add_argument("--subdir", action="append", choices=ALLOWED_SUBDIRS,
                        help="folder to clean (repeatable); default: all of " + ", ".join(ALLOWED_SUBDIRS))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    volume = args.volume.rstrip("/")
    if not volume.startswith("/Volumes/"):
        sys.exit(f"refusing to run: --volume must be a /Volumes path, got {volume!r}")
    subdirs = list(dict.fromkeys(args.subdir or ALLOWED_SUBDIRS))

    from databricks.sdk import WorkspaceClient  # available on serverless job compute

    w = WorkspaceClient()
    today = dt.datetime.now(dt.timezone.utc).date()
    mode = "DRY RUN" if args.dry_run else "DELETE"
    print(f"[trace-cleanup] {mode} volume={volume} subdirs={subdirs} today={today} keep_days={args.keep_days} cutoff<{today - dt.timedelta(days=args.keep_days)}")
    total_days = total_files = 0
    for subdir in subdirs:
        days, files = _clean_subdir(w, f"{volume}/{subdir}", subdir, today, args.keep_days, args.dry_run)
        total_days += days
        total_files += files
    print(f"[trace-cleanup] done: {total_days} day folder(s) deleted, {total_files} file(s)")


def _clean_subdir(w, runs, subdir, today, keep_days, dry_run):
    """Clean one allowed top-level folder. Returns (day folders deleted, files deleted)."""
    from databricks.sdk.errors import NotFound

    try:
        entries = _children(w, runs)
    except NotFound:
        print(f"[trace-cleanup] {subdir}/: not present, skipped")
        return 0, 0
    dirs = [e.path.rstrip("/").split("/")[-1] for e in entries if e.is_directory]
    stray_files = [e.path.rstrip("/").split("/")[-1] for e in entries if not e.is_directory]
    expired, kept, ignored = select_expired(dirs, today, keep_days)

    print(f"[trace-cleanup] {subdir}/: {len(dirs)} day folder(s) total, {len(expired)} expired, {len(kept)} kept")
    if ignored or stray_files:
        print(f"[trace-cleanup] {subdir}/: left alone (not day folders): {ignored + stray_files}")

    deleted_files = 0
    for name in expired:
        path = f"{runs}/{name}"
        if dry_run:
            runs_inside = len(_children(w, path))
            print(f"[trace-cleanup] would delete {path} ({runs_inside} run folder(s))")
            continue
        n = _delete_tree(w, path)
        deleted_files += n
        print(f"[trace-cleanup] deleted {path} ({n} file(s))")
    return (0 if dry_run else len(expired)), deleted_files


if __name__ == "__main__":
    main()
