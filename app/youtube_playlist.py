"""YouTube tab extraction with one continuation lookup per rich-grid page."""

from yt_dlp.extractor.youtube import YoutubeTabIE as BaseYoutubeTabIE


class YoutubeTabIE(BaseYoutubeTabIE):
    # Keep the upstream class name so YoutubeDL registers this under YoutubeTab.
    def _extract_entries(self, parent_renderer, continuation_list):
        contents = parent_renderer.get('contents')
        if not isinstance(contents, list) or not contents or not all(
            isinstance(item, dict)
            and ('richItemRenderer' in item or 'continuationItemRenderer' in item)
            for item in contents
        ):
            yield from super()._extract_entries(parent_renderer, continuation_list)
            return

        # Upstream scans this entire page again after every rich item. The page
        # is unchanged during iteration, so resolve its continuation only once.
        continuation_list[:] = [None]
        for item in contents:
            if item.get('richItemRenderer'):
                yield from self._rich_entries(item['richItemRenderer'])
        continuation_list[:] = [self._extract_continuation(parent_renderer)]
