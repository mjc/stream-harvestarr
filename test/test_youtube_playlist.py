"""Keep upstream entries and pagination while eliminating repeated page scans."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import yt_dlp
from youtube_playlist import BaseYoutubeTabIE, YoutubeTabIE


class YoutubePlaylistTests(unittest.TestCase):
    def test_rich_grid_preserves_entries_and_continuation(self):
        page = {'contents': [
            {'richItemRenderer': {'content': {'videoRenderer': {
                'videoId': f'{index:011d}',
                'title': {'runs': [{'text': f'Episode {index}'}]},
                'lengthText': {'simpleText': '10:00'},
            }}}}
            for index in range(30)
        ] + [{'continuationItemRenderer': {'continuationEndpoint': {
            'continuationCommand': {'token': 'next-page'},
            'clickTrackingParams': 'tracking',
        }}}]}
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            baseline = BaseYoutubeTabIE(ydl)
            optimized = YoutubeTabIE(ydl)
            old_token, new_token = [None], [None]
            expected = list(baseline._extract_entries(page, old_token))
            with patch.object(optimized, '_extract_continuation',
                              wraps=optimized._extract_continuation) as lookup:
                actual = list(optimized._extract_entries(page, new_token))
            self.assertEqual(actual, expected)
            self.assertEqual(len(actual), 30)
            self.assertEqual(new_token, old_token)
            self.assertEqual(new_token[0]['continuation'], 'next-page')
            lookup.assert_called_once_with(page)

    def test_other_page_layouts_use_upstream(self):
        extractor = YoutubeTabIE()
        for page in ({}, {'contents': []}, {'contents': [
            {'richItemRenderer': {}}, {'itemSectionRenderer': {}}
        ]}):
            with self.subTest(page=page), patch.object(
                BaseYoutubeTabIE, '_extract_entries',
                return_value=iter([{'url': 'https://youtu.be/example'}]),
            ) as fallback:
                continuation = [None]
                self.assertEqual(list(extractor._extract_entries(page, continuation)),
                                 [{'url': 'https://youtu.be/example'}])
                fallback.assert_called_once_with(page, continuation)

    def test_registered_under_upstream_key(self):
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            extractor = YoutubeTabIE()
            ydl.add_info_extractor(extractor)
            self.assertIs(ydl.get_info_extractor('YoutubeTab'), extractor)
