"""Regression tests for the once-per-scan flat playlist extraction."""
import os
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)

os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr  # noqa: E402


class FakeYoutubeDL(object):
    calls = []
    results = []

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        type(self).calls.append(self.opts)
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=False):
        type(self).urls.append(url)
        return type(self).results.pop(0)


class PlaylistCacheTestCase(unittest.TestCase):

    def setUp(self):
        stream_harvestarr.PLAYLIST_CACHE.clear()
        stream_harvestarr.PLAYLIST_REFRESHED.clear()
        self.real_ydl = stream_harvestarr.yt_dlp.YoutubeDL
        FakeYoutubeDL.calls = []
        FakeYoutubeDL.urls = []
        FakeYoutubeDL.results = []
        stream_harvestarr.yt_dlp.YoutubeDL = FakeYoutubeDL

    def tearDown(self):
        stream_harvestarr.yt_dlp.YoutubeDL = self.real_ydl

    def test_bare_channel_uses_videos_tab(self):
        self.assertEqual(
            stream_harvestarr.video_playlist_url('https://www.youtube.com/@VICE'),
            'https://www.youtube.com/@VICE/videos')
        self.assertEqual(
            stream_harvestarr.video_playlist_url('https://www.youtube.com/@VICE/search?query=x'),
            'https://www.youtube.com/@VICE/search?query=x')

    def test_refreshes_once_and_merges_new_entries(self):
        playlist = 'https://www.youtube.com/@VICE'
        opts = {'playlistreverse': False}
        first = {'entries': [{'url': 'https://youtu.be/old', 'title': 'old'}]}
        second = {'entries': [{'url': 'https://youtu.be/new', 'title': 'new'}]}
        FakeYoutubeDL.results = [first, second]

        first_scan = stream_harvestarr.StreamHarvester.cached_playlist_entries(opts, playlist)
        same_scan = stream_harvestarr.StreamHarvester.cached_playlist_entries(opts, playlist)
        self.assertEqual(first_scan, same_scan)
        self.assertEqual(len(FakeYoutubeDL.calls), 1)
        self.assertEqual(FakeYoutubeDL.urls, [playlist + '/videos'])

        stream_harvestarr.PLAYLIST_REFRESHED.clear()
        next_scan = stream_harvestarr.StreamHarvester.cached_playlist_entries(opts, playlist)
        self.assertEqual(
            [entry['url'] for entry in next_scan],
            ['https://youtu.be/old', 'https://youtu.be/new'])
        self.assertEqual(FakeYoutubeDL.calls[1]['playlistend'], 50)


if __name__ == '__main__':
    unittest.main()
