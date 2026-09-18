"""
Regression tests for the error paths in ``download()``.

``for e, eps in enumerate(episodes)`` uses ``e`` as the episode index in every
log line in the loop. The exception handler caught ``as e``, rebinding it to
the exception object, so the moment any download failed the handler's own
``e + 1`` raised::

    TypeError: unsupported operand type(s) for +: 'DownloadError' and 'int'

That escaped ``main()`` and killed the process, so the container restart-looped
for as long as downloads kept failing. Worse, the rate-limit branch logs
*before* it sleeps, so the exponential backoff the config carefully configures
could never run — the one situation it exists for was the one that crashed.

Same shape as issue #150: an unhandled TypeError in the scan takes the whole
container down rather than skipping one episode.
"""
import os
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)

os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr  # noqa: E402

SERIES = [{
    'id': 1, 'title': "Epicly Later'd", 'url': 'https://www.youtube.com/@VICE/search?query=x',
    'playlistreverse': False, 'path': "/tv/Epicly Later'd",
}]
EPISODES = [{
    'seriesId': 1, 'title': 'Ben Kadow', 'seasonNumber': 5, 'episodeNumber': 8,
}]


class ExplodingYoutubeDL(object):
    """Stands in for yt_dlp.YoutubeDL; download() always fails."""

    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def download(self, urls):
        raise RuntimeError(self.message)


class ScriptedYoutubeDL(object):
    instances = []
    outcomes = []

    def __init__(self, options):
        """Initialize the test fixture."""
        self.options = options

    def __enter__(self):
        """Enter the fake client context."""
        type(self).instances.append(self)
        return self

    def __exit__(self, *exc_info):
        """Exit the fake client context."""
        return False

    def download(self, urls):
        """Record the requested fake download."""
        outcome = type(self).outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome


class DownloadErrorTestCase(unittest.TestCase):

    def setUp(self):
        self._real_ydl = stream_harvestarr.yt_dlp.YoutubeDL
        self._real_sleep = stream_harvestarr.time.sleep
        self.slept = []
        stream_harvestarr.time.sleep = self.slept.append

    def tearDown(self):
        stream_harvestarr.yt_dlp.YoutubeDL = self._real_ydl
        stream_harvestarr.time.sleep = self._real_sleep

    def client(self, message):
        """Provide the test data for this scenario."""
        c = object.__new__(stream_harvestarr.StreamHarvester)
        c.debug = False
        c.ytdl_format = 'best'
        c.ytdl_merge_output_format = 'mkv'
        c.root_folder = ''
        c.season_padding = 0
        c.episode_padding = 0
        c.sleep_requests = 0
        c.download_delay = 0
        c.rate_limit_sleep = 1800
        c.rate_limit_count = 0
        c.current_backoff = 1800
        c.video_403_count = 0
        c.backoff_enabled = True
        c.backoff_multiplier = 1.5
        c.backoff_max = 5400
        c.ytsearch = lambda *a, **kw: 'https://www.youtube.com/watch?v=YrmakZiZTOE'
        c.rescanseries = lambda series_id: None
        stream_harvestarr.yt_dlp.YoutubeDL = lambda opts: ExplodingYoutubeDL(message)
        return c

    def test_generic_download_error_does_not_escape(self):
        """This used to raise TypeError out of main() and kill the process."""
        self.client('boom').download(SERIES, list(EPISODES))

    def test_rate_limit_error_does_not_escape(self):
        self.client("This content isn't available, try again later").download(
            SERIES, list(EPISODES))

    def test_rate_limit_actually_sleeps(self):
        """The crash happened before the sleep, so backoff never ran."""
        c = self.client("This content isn't available, try again later")
        c.download(SERIES, list(EPISODES))
        self.assertEqual(self.slept, [1800])
        self.assertEqual(c.rate_limit_count, 1)

    def test_second_rate_limit_backs_off_further(self):
        """Verify repeated rate limits increase the backoff delay."""
        c = self.client('rate-limited')
        c.download(SERIES, list(EPISODES))
        c.download(SERIES, list(EPISODES))
        self.assertEqual(self.slept, [1800, 2700])
        self.assertEqual(c.rate_limit_count, 2)

    def test_three_video_403s_stop_the_scan(self):
        """Repeated forbidden responses must not hot-loop every episode."""
        c = self.client('HTTP Error 403: Forbidden')
        attempts = []

        def fail(*args, **kwargs):
            """Fail the test if the download callback is not stopped."""
            attempts.append(1)
            raise RuntimeError('HTTP Error 403: Forbidden')

        c.download_video = fail
        episodes = [dict(EPISODES[0], episodeNumber=number) for number in range(1, 5)]
        c.download(SERIES, episodes)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(c.video_403_count, 3)

    def test_subtitle_failure_retries_without_subtitle_options(self):
        """Verify subtitle failure retries without subtitle options."""
        c = self.client('unused')
        ScriptedYoutubeDL.instances = []
        ScriptedYoutubeDL.outcomes = [
            stream_harvestarr.yt_dlp.utils.DownloadError('subtitle HTTP 429'),
            None,
        ]
        stream_harvestarr.yt_dlp.YoutubeDL = ScriptedYoutubeDL
        options = {
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['en'],
            'postprocessors': [
                {'key': 'FFmpegSubtitlesConvertor', 'format': 'srt'},
                {'key': 'FFmpegEmbedSubtitle'},
                {'key': 'Exec'},
            ],
        }

        c.download_video('https://youtu.be/x', options, 'Episode')

        self.assertEqual(len(ScriptedYoutubeDL.instances), 2)
        fallback = ScriptedYoutubeDL.instances[1].options
        self.assertNotIn('writesubtitles', fallback)
        self.assertNotIn('writeautomaticsub', fallback)
        self.assertNotIn('subtitleslangs', fallback)
        self.assertEqual(fallback['postprocessors'], [{'key': 'Exec'}])

    def test_backoff_is_capped(self):
        """Verify exponential backoff stops at its configured maximum."""
        c = self.client('rate limit')
        c.rate_limit_count = 40
        c.download(SERIES, list(EPISODES))
        self.assertEqual(self.slept, [c.backoff_max])

    def test_every_episode_is_attempted_after_a_failure(self):
        """One bad episode must not end the run."""
        c = self.client('boom')
        seen = []
        c.ytsearch = lambda *a, **kw: (seen.append(1), 'https://youtu.be/x')[1]
        episodes = [dict(EPISODES[0], title='One'), dict(EPISODES[0], title='Two')]
        c.download(SERIES, episodes)
        self.assertEqual(len(seen), 2)


if __name__ == '__main__':
    unittest.main()
