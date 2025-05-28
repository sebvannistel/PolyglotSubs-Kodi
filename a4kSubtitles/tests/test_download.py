import unittest
from unittest.mock import MagicMock, patch, call

# Assuming download function is in a4kSubtitles.download
from a4kSubtitles.download import download

class TestDownloadFunction(unittest.TestCase):

    @patch('a4kSubtitles.download.__copy_sub_local') # Patching this as it's not relevant to the core logic
    @patch('a4kSubtitles.download.__postprocess')
    @patch('a4kSubtitles.download.__extract_zip')
    @patch('a4kSubtitles.download.__extract_gzip')
    @patch('a4kSubtitles.download.__download')
    # Keep filename simple for __insert_lang_code_in_filename, it returns filename.lang_code by default
    # Let's mock it to return a predictable filename, e.g., original_filename.lang_code
    @patch('a4kSubtitles.download.__insert_lang_code_in_filename', side_effect=lambda core, filename, lang_code: f"{filename.rsplit('.', 1)[0]}.{lang_code}.{filename.rsplit('.', 1)[1]}" if '.' in filename else f"{filename}.{lang_code}")
    def test_download_with_save_callback(self, mock_insert_fn, mock_download_internal, mock_extract_gzip, mock_extract_zip, mock_postprocess, mock_copy_sub_local):
        core_mock = MagicMock()
        core_mock.utils.temp_dir = '/tmp/temp_subtitles'
        core_mock.utils.slugify_filename.side_effect = lambda x: x # Keep filename as is
        core_mock.utils.get_lang_id.return_value = 'eng' # For 'en' language
        core_mock.os.path.join.side_effect = lambda *args: '/'.join(args) # Simple path join mock
        
        # Mocks for initial setup functions
        core_mock.shutil.rmtree = MagicMock()
        core_mock.kodi.xbmcvfs.mkdirs = MagicMock()
        core_mock.api_mode_enabled = False # Assuming it's not API mode for this test

        mock_save_callback = MagicMock(return_value=True)
        
        mock_service_instance = MagicMock()
        # The request built by build_download_request should contain the save_callback
        mock_service_instance.build_download_request.return_value = {
            'save_callback': mock_save_callback,
            # other request parts if necessary for the download function to proceed
            'url': 'http://dummyurl.com/sub.zip' # A dummy URL, though not used by save_callback path
        }
        
        core_mock.services = {'test_service': mock_service_instance}

        params = {
            'service_name': 'test_service',
            'action_args': {
                'lang': 'en', # This will be processed by get_lang_id to 'eng'
                'filename': 'My.Movie.Title.srt',
                # Any other args needed by build_download_request or download function
            }
        }

        # Call the actual download function
        download(core_mock, params)

        # Assertions
        mock_save_callback.assert_called_once()
        
        # Determine the expected filename after __insert_lang_code_in_filename and slugify
        # Based on mocked __insert_lang_code_in_filename: "My.Movie.Title.eng.srt"
        # Based on mocked slugify_filename: "My.Movie.Title.eng.srt" (no change)
        expected_processed_filename = "My.Movie.Title.eng.srt"
        expected_srt_path = '/tmp/temp_subtitles/' + expected_processed_filename
        
        args, _ = mock_save_callback.call_args
        self.assertEqual(args[0], expected_srt_path)

        mock_download_internal.assert_not_called()
        mock_extract_gzip.assert_not_called()
        mock_extract_zip.assert_not_called()
        
        # Check that __postprocess was called with the srt_path and lang_code ('eng')
        mock_postprocess.assert_called_once_with(core_mock, expected_srt_path, 'eng')
        mock_copy_sub_local.assert_not_called() # Should not be called if api_mode_enabled is False

if __name__ == '__main__':
    unittest.main()
