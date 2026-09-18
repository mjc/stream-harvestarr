"""Compact, temporary on-disk snapshots for arbitrarily large playlists."""

import sqlite3
import weakref


class PlaylistSnapshot:
    """Store matching fields without retaining yt-dlp's metadata in memory.

    An empty SQLite filename creates a private temporary database, deleted when
    the connection closes. A snapshot is only published after extraction ends.
    """

    def __init__(self, entries):
        """Initialize a temporary SQLite snapshot from title and URL pairs."""
        self._connection = sqlite3.connect('')
        self._close = weakref.finalize(self, self._connection.close)
        try:
            self._connection.execute('PRAGMA cache_size = -2048')
            self._connection.execute(
                'CREATE TABLE entries (position INTEGER PRIMARY KEY, title TEXT, url TEXT)')
            with self._connection:
                self._connection.executemany(
                    'INSERT INTO entries (title, url) VALUES (?, ?)', entries)
            self._count = self._connection.execute(
                'SELECT count(*) FROM entries').fetchone()[0]
        except BaseException:
            self._close()
            raise

    def __len__(self):
        return self._count

    def __iter__(self):
        return self._read('ASC')

    def __reversed__(self):
        return self._read('DESC')

    def _read(self, order):
        """Read entries in the requested database order."""
        cursor = self._connection.execute(
            f'SELECT title, url FROM entries ORDER BY position {order}')
        try:
            for title, url in cursor:
                yield {'title': title, 'url': url}
        finally:
            cursor.close()
