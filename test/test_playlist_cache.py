"""Regression tests for the once-per-scan flat playlist extraction."""
import os
import sys
import unittest
from unittest.mock import Mock, patch

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
        """Initialize the test fixture."""
        self.opts = opts

    def __enter__(self):
        """Enter the fake client context."""
        type(self).calls.append(self.opts)
        return self

    def __exit__(self, *exc_info):
        """Exit the fake client context."""
        return False

    def add_info_extractor(self, extractor):
        """Record the extractor registered by the fake client."""
        self.extractor = extractor

    def extract_info(self, url, download=False, process=True):
        """Return the configured fake extraction result."""
        type(self).urls.append(url)
        self.opts['process'] = process
        return type(self).results.pop(0)

    def process_ie_result(self, result, download=False):
        """Return the configured fake processed result."""
        return type(self).results.pop(0)


class PlaylistCacheTestCase(unittest.TestCase):

    def setUp(self):
        """Set up fixtures for this test case."""
        self.cache = stream_harvestarr.PlaylistCache()
        self.real_ydl = stream_harvestarr.yt_dlp.YoutubeDL
        FakeYoutubeDL.calls = []
        FakeYoutubeDL.urls = []
        FakeYoutubeDL.results = []
        stream_harvestarr.yt_dlp.YoutubeDL = FakeYoutubeDL

    def tearDown(self):
        """Release fixtures created by this test case."""
        stream_harvestarr.yt_dlp.YoutubeDL = self.real_ydl

    def test_bare_channel_uses_videos_tab(self):
        """Verify bare channel uses videos tab."""
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
        """Verify refreshes once and replaces entries."""
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
        """Verify failed refresh keeps last good entries."""
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

    def test_extractor_api_failure_is_diagnosed_and_preserves_snapshot(self):
        """Private API drift must be visible with and without a cached snapshot."""
        url = 'https://www.youtube.com/@VICE/videos'
        FakeYoutubeDL.results = [{'entries': [{'url': 'https://youtu.be/old'}]}]
        previous = self.cache.get({}, url)
        for cache, diagnostic in ((self.cache, 'previous complete snapshot'),
                                  (stream_harvestarr.PlaylistCache(), 'no snapshot is available')):
            cache.begin_scan()
            with patch.object(FakeYoutubeDL, 'extract_info', side_effect=AttributeError('missing _rich_entries')):
                with self.assertLogs(stream_harvestarr.logger, level='WARNING') as logs:
                    result = cache.get({}, url)
            self.assertIn('missing _rich_entries', '\n'.join(logs.output))
            self.assertIn(diagnostic, '\n'.join(logs.output))
            if cache is self.cache:
                self.assertIs(result, previous)
            else:
                self.assertEqual(list(result), [])

    def test_playlist_reverse_is_applied_without_duplicate_extraction(self):
        """Verify playlist reverse is applied without duplicate extraction."""
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
        """Verify begin scan prunes removed sources."""
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

    def test_later_page_failure_preserves_complete_snapshot(self):
        """Verify later page failure preserves complete snapshot."""
        def broken_pages():
            """Provide a partial page followed by an extraction failure."""
            yield {'url': 'https://youtu.be/partial', 'title': 'Partial'}
            raise RuntimeError('second page failed')

        url = 'https://www.youtube.com/@VICE/videos'
        FakeYoutubeDL.results = [
            {'entries': [{'url': 'https://youtu.be/old', 'title': 'Old'}]},
            {'entries': broken_pages()},
        ]
        previous = self.cache.get({}, url)
        self.cache.begin_scan()
        with self.assertLogs(stream_harvestarr.logger, level='ERROR'):
            current = self.cache.get({}, url)
        self.assertIs(current, previous)
        self.assertEqual(list(current), [{'url': 'https://youtu.be/old', 'title': 'Old'}])

    def test_raw_search_limit_does_not_truncate_full_enumeration(self):
        """Verify raw search limit does not truncate full enumeration."""
        seen = []

        def pages():
            """Provide a repeatable stream of fake playlist entries."""
            for number in range(25):
                seen.append(number)
                yield {'url': f'https://youtu.be/{number}', 'title': str(number)}

        url = 'https://www.youtube.com/@VICE/search?query=Episode'
        FakeYoutubeDL.results = [{'entries': pages()}, {'entries': pages()}]
        bounded = self.cache.get({'playlistend': 20}, url)
        self.assertEqual(len(bounded), 20)
        self.assertEqual(seen, list(range(20)))
        full = self.cache.get({}, url)
        self.assertEqual(len(full), 25)
        self.assertEqual(next(reversed(full))['title'], '24')
        self.assertFalse(FakeYoutubeDL.calls[0]['process'])

    def test_non_youtube_sources_keep_normal_processing(self):
        """Verify non youtube sources keep normal processing."""
        FakeYoutubeDL.results = [{'entries': [{'url': 'https://example.com/video'}]}]
        self.cache.get({}, 'https://example.com/playlist')
        self.assertTrue(FakeYoutubeDL.calls[0]['process'])

    def test_raw_tab_redirect_is_resolved_before_caching(self):
        """Verify raw tab redirect is resolved before caching."""
        FakeYoutubeDL.results = [
            {'_type': 'url', 'url': 'https://www.youtube.com/playlist?list=redirect'},
            {'entries': [{'url': 'https://youtu.be/episode', 'title': 'Episode'}]},
        ]
        snapshot = self.cache.get({}, 'https://www.youtube.com/@VICE/videos')
        self.assertEqual(list(snapshot), [
            {'url': 'https://youtu.be/episode', 'title': 'Episode'},
        ])


class EpisodeSearchTestCase(unittest.TestCase):

    def test_channel_search_is_bounded_before_full_scan(self):
        """Verify channel search is bounded before full scan."""
        client = object.__new__(stream_harvestarr.StreamHarvester)
        client.playlist_cache = stream_harvestarr.PlaylistCache()
        client.ytdl_eps_search_opts = Mock(return_value={'playlistreverse': False})
        options_seen = []
        urls_seen = []
        results = iter((None, None, 'https://youtu.be/full-scan'))

        def ytsearch(options, url, *args):
            """Return the next staged channel-search result."""
            options_seen.append(dict(options))
            urls_seen.append(url)
            return next(results)

        client.ytsearch = Mock(side_effect=ytsearch)
        series = {
            'channel_search': True,
            'url': 'https://www.youtube.com/@VICE/videos',
            'playlistreverse': False,
        }
        episode = {'title': 'Episode 1'}

        result = client.find_episode(series, episode)

        self.assertEqual(result, 'https://youtu.be/full-scan')
        first_options = options_seen[0]
        self.assertEqual(first_options['playlistend'], 20)
        self.assertTrue(first_options['lazy_playlist'])
        self.assertEqual(
            urls_seen[0],
            'https://www.youtube.com/@VICE/search?query=Episode+1')
        second_options = options_seen[1]
        self.assertNotIn('playlistend', second_options)
        self.assertEqual(
            urls_seen[1],
            'https://www.youtube.com/@VICE/search?query=Episode+1')
        self.assertEqual(
            urls_seen[2],
            'https://www.youtube.com/@VICE/videos')


if __name__ == '__main__':
    unittest.main()
