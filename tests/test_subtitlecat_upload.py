from unittest.mock import MagicMock, patch

from tests.common import api

# Use the API helper to set up mocked Kodi environment
api_instance = api.A4kSubtitlesApi({'kodi': True})
core = api_instance.core
core.settings = MagicMock()

@patch('a4kSubtitles.services.subtitlecat._upload_translation_to_subtitlecat')
@patch('a4kSubtitles.services.subtitlecat._gtranslate_text_chunk')
@patch('a4kSubtitles.services.subtitlecat._protect_subtitle_tags')
@patch('a4kSubtitles.services.subtitlecat._restore_subtitle_tags', side_effect=lambda text, _map: text)
@patch('a4kSubtitles.services.subtitlecat.srt.parse')
@patch('a4kSubtitles.services.subtitlecat.srt.compose', side_effect=lambda items: '1\nBonjour\n')
@patch('a4kSubtitles.services.subtitlecat._get_session')
def test_client_translation_upload(mock_get_session, mock_compose, mock_parse, mock_restore, mock_protect,
                                   mock_gtranslate, mock_upload):
    # Mock HTTP get for original subtitle
    session = MagicMock()
    response = MagicMock()
    response.text = '1\nHello\n'
    response.raise_for_status.return_value = None
    session.get.return_value = response
    mock_get_session.return_value = session

    # Mock subtitle items
    item = MagicMock()
    item.content = 'Hello'
    mock_parse.return_value = [item]
    mock_protect.return_value = ('Hello', {}, False)
    mock_gtranslate.return_value = (['Bonjour'], 'en')
    mock_upload.return_value = 'http://subtitlecat.com/new.srt'

    # Settings enabling upload
    core.settings.get.side_effect = lambda k, d=None: {
        'subtitlecat_upload_translations': True,
        'force_bom': False,
        'http_timeout': 20
    }.get(k, d)

    action_args = {
        'needs_client_side_translation': True,
        'original_srt_url': 'http://example.com/test.srt',
        'target_translation_lang': 'fr',
        'lang_code': 'fr',
        'filename': 'test.srt',
        'detail_url': 'http://example.com/detail'
    }

    result = api_instance.core.services['subtitlecat'].build_download_request(core, 'subtitlecat', action_args)

    assert result['method'] == 'REQUEST_CALLBACK'
    result['save_callback']('/tmp/out.srt')
    mock_upload.assert_called_once()
    session.get.assert_called_with('http://subtitlecat.com/new.srt', timeout=20, stream=True)
    cache_key = (action_args['detail_url'], action_args['lang_code'])
    assert cache_key in api_instance.core.services['subtitlecat']._TRANSLATED_CACHE

@patch('a4kSubtitles.services.subtitlecat._upload_translation_to_subtitlecat')
@patch('a4kSubtitles.services.subtitlecat._gtranslate_text_chunk', return_value=(['Bonjour'], 'en'))
@patch('a4kSubtitles.services.subtitlecat._protect_subtitle_tags', return_value=('Hello', {}, False))
@patch('a4kSubtitles.services.subtitlecat._restore_subtitle_tags', side_effect=lambda text, _map: text)
@patch('a4kSubtitles.services.subtitlecat.srt.parse')
@patch('a4kSubtitles.services.subtitlecat.srt.compose', side_effect=lambda items: '1\nBonjour\n')
@patch('a4kSubtitles.services.subtitlecat._get_session')
def test_client_translation_no_upload(mock_get_session, mock_compose, mock_parse, mock_restore, mock_protect,
                                      mock_gtranslate, mock_upload):
    session = MagicMock()
    response = MagicMock()
    response.text = '1\nHello\n'
    response.raise_for_status.return_value = None
    session.get.return_value = response
    mock_get_session.return_value = session

    item = MagicMock()
    item.content = 'Hello'
    mock_parse.return_value = [item]

    core.settings.get.side_effect = lambda k, d=None: {
        'subtitlecat_upload_translations': False,
        'force_bom': False,
        'http_timeout': 20
    }.get(k, d)

    action_args = {
        'needs_client_side_translation': True,
        'original_srt_url': 'http://example.com/test.srt',
        'target_translation_lang': 'fr',
        'lang_code': 'fr',
        'filename': 'test.srt',
        'detail_url': 'http://example.com/detail'
    }

    result = api_instance.core.services['subtitlecat'].build_download_request(core, 'subtitlecat', action_args)

    assert result['method'] == 'CLIENT_SIDE_TRANSLATED'
    mock_upload.assert_not_called()
