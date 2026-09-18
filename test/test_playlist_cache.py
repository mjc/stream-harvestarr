"""Regression tests for the once-per-scan flat playlist extraction."""
import os
import sys
import unittest
from unittest.mock import Mock

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
        self.cache = stream_harvestarr.PlaylistCache()
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
        self.assertEqual(
            stream_harvestarr.video_playlist_url('https://www.youtube.com/@VICE/videos'),
            'https://www.youtube.com/@VICE/videos')
        self.assertEqual(
            stream_harvestarr.video_playlist_url('https://example.com/@VICE'),
            'https://example.com/@VICE')
        self.assertEqual(
            stream_harvestarr.video_search_url(
                'https://www.youtube.com/@VICE/videos', 'Episode 1'),
            'https://www.youtube.com/@VICE/search?query=Episode+1')
        self.assertIsNone(
            stream_harvestarr.video_search_url(
                'https://example.com/@VICE', 'Episode 1'))

    def test_refreshes_once_and_replaces_entries(self):
        playlist = 'https://www.youtube.com/@VICE'
        opts = {'playlistreverse': False}
        first = {'entries': [{'url': 'https://youtu.be/old', 'title': 'old'}]}
        second = {'entries': [{'url': 'https://youtu.be/new', 'title': 'new'}]}
        FakeYoutubeDL.results = [first, second]

        first_scan = self.cache.get(opts, playlist)
        same_scan = self.cache.get(opts, playlist)
        self.assertEqual(first_scan, same_scan)
        self.assertEqual(len(FakeYoutubeDL.calls), 1)
        self.assertEqual(FakeYoutubeDL.urls, [playlist + '/videos'])

        self.cache.begin_scan()
        next_scan = self.cache.get(opts, playlist)
        self.assertEqual(
            [entry['url'] for entry in next_scan],
            ['https://youtu.be/new'])
        self.assertNotIn('playlistend', FakeYoutubeDL.calls[1])

    def test_failed_refresh_keeps_last_good_entries(self):
        playlist = 'https://www.youtube.com/@VICE'
        opts = {'playlistreverse': False}
        FakeYoutubeDL.results = [
            {'entries': [{'url': 'https://youtu.be/old', 'title': 'old'}]},
            None,
        ]

        self.assertEqual(len(self.cache.get(opts, playlist)), 1)
        self.cache.begin_scan()
        self.assertEqual(
            [entry['url'] for entry in self.cache.get(opts, playlist)],
            ['https://youtu.be/old'])

    def test_playlist_reverse_is_applied_without_duplicate_extraction(self):
        playlist = 'https://www.youtube.com/playlist?list=TEST'
        FakeYoutubeDL.results = [{'entries': [
            {'url': 'https://youtu.be/one', 'title': 'one'},
            {'url': 'https://youtu.be/two', 'title': 'two'},
        ]}]

        self.assertEqual(
            [entry['url'] for entry in self.cache.get(
                {'playlistreverse': False}, playlist)],
            ['https://youtu.be/one', 'https://youtu.be/two'])
        self.assertEqual(
            [entry['url'] for entry in self.cache.get(
                {'playlistreverse': True}, playlist)],
            ['https://youtu.be/two', 'https://youtu.be/one'])
        self.assertEqual(len(FakeYoutubeDL.calls), 1)

    def test_begin_scan_prunes_removed_sources(self):
        first = 'https://www.youtube.com/playlist?list=FIRST'
        second = 'https://www.youtube.com/playlist?list=SECOND'
        FakeYoutubeDL.results = [
            {'entries': [{'url': 'https://youtu.be/one'}]},
            {'entries': [{'url': 'https://youtu.be/two'}]},
        ]
        self.cache.get({}, first)
        self.cache.get({}, second)

        self.cache.begin_scan({first})
        self.assertEqual(len(self.cache.entries), 1)
        self.assertEqual(len(FakeYoutubeDL.calls), 2)


class EpisodeSearchTestCase(unittest.TestCase):

    def test_channel_search_is_bounded_before_full_scan(self):
        client = object.__new__(stream_harvestarr.StreamHarvester)
        client.ytdl_eps_search_opts = Mock(return_value={'playlistreverse': False})
        client.ytsearch = Mock(side_effect=[None, 'https://youtu.be/full-scan'])
        series = {
            'url': 'https://www.youtube.com/@VICE/videos',
            'playlistreverse': False,
        }
        episode = {'title': 'Episode 1'}

        result = client.find_episode(series, episode)

        self.assertEqual(result, 'https://youtu.be/full-scan')
        first_options = client.ytsearch.call_args_list[0].args[0]
        self.assertEqual(first_options['playlistend'], 20)
        self.assertTrue(first_options['lazy_playlist'])
        self.assertEqual(
            client.ytsearch.call_args_list[0].args[1],
            'https://www.youtube.com/@VICE/search?query=Episode+1')
        self.assertEqual(
            client.ytsearch.call_args_list[1].args[1],
            'https://www.youtube.com/@VICE/videos')


if __name__ == '__main__':
    unittest.main()
