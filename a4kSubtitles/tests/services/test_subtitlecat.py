import unittest
from unittest.mock import MagicMock, patch, call
import html
import os
import json
import sys
import pytest

pytest.skip("Outdated provider tests", allow_module_level=True)

# Ensure the repository root is on sys.path so 'a4kSubtitles' can be imported
current_dir = os.path.dirname(__file__)
repo_root = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
sys.path.append(repo_root)

# Ensure the Subtitlecat service loads with mocked Kodi modules
os.environ["A4KSUBTITLES_API_MODE"] = json.dumps({"kodi": True})

from a4kSubtitles.services import subtitlecat as subtitlecat_module

_CHUNK_SEP = "|||SGMNTBRK|||" 
# subtitlecat_module.block_size_chars (1500) is a local const within build_download_request.
# Tests manage chunking by controlling the length of 'protected_text' from _protect_subtitle_tags mock.

class TestSubtitlecatBuildDownloadRequestClientTranslation(unittest.TestCase):
    def setUp(self):
        self.core_mock = MagicMock()
        self.core_mock.logger = MagicMock()
        # Mock for core.settings.get used by _get_setting helper in subtitlecat.py
        # Default behavior: 'force_bom' is False, 'http_timeout' is 20.
        self.core_mock.settings.get.side_effect = lambda key, default: False if key == 'force_bom' else (default if default is not None else 20)
        
        self.service_name = "subtitlecat_test_service"
        # Base action_args for client translation, matching what build_download_request expects
        self.base_action_args = {
            'needs_client_side_translation': True,
            'original_srt_url': 'http://example.com/orig.srt',
            'target_translation_lang': 'fr', # Corresponds to 'target_lang_code' in prompt
            'filename': 'test.srt',
            # 'original_lang_code' from prompt is not used by this part of build_download_request
        }
        # This list will be populated by the mock for srt.parse and is used for assertions
        self.parsed_subs_list_reference = []

    def _create_mock_sub_item(self, content=""):
        item = MagicMock(spec=['content']) 
        item.content = content
        return item

    # Helper to create the tuple structure that _protect_subtitle_tags is expected to return
    def _create_protect_output(self, protected_text, tag_map=None, is_all_tag_line=False):
        if tag_map is None:
            tag_map = {}
        return (protected_text, tag_map, is_all_tag_line)

    # Helper to setup mocks that lead to internal creation of parsed_subs and translatable_items_info
    def _setup_internal_states_mocks(self, mock_get_session, mock_srt_parse, mock_protect_tags,
                                     original_srt_text, parsed_subs_contents, protect_tags_outputs):
        mock_session = MagicMock()
        mock_session_response = MagicMock()
        mock_session_response.text = original_srt_text
        mock_session_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_session_response
        mock_get_session.return_value = mock_session

        self.parsed_subs_list_reference = [self._create_mock_sub_item(c) for c in parsed_subs_contents]
        mock_srt_parse.return_value = self.parsed_subs_list_reference
        
        mock_protect_tags.side_effect = protect_tags_outputs

    # --- Test Scenarios ---

    @patch('a4kSubtitles.services.subtitlecat.time.sleep')
    @patch('a4kSubtitles.services.subtitlecat.srt.compose', side_effect=lambda x: "composed_srt_content")
    @patch('a4kSubtitles.services.subtitlecat.html.unescape', side_effect=lambda x: x) 
    @patch('a4kSubtitles.services.subtitlecat._restore_subtitle_tags', side_effect=lambda text, tag_map: text) 
    @patch('a4kSubtitles.services.subtitlecat._gtranslate_text_chunk')
    @patch('a4kSubtitles.services.subtitlecat._protect_subtitle_tags')
    @patch('a4kSubtitles.services.subtitlecat.srt.parse')
    @patch('a4kSubtitles.services.subtitlecat._get_session')
    def test_1_1_perfect_match_single_chunk(self, mock_get_session, mock_srt_parse, mock_protect_tags, 
                                           mock_gtranslate, mock_restore_tags, mock_html_unescape, 
                                           mock_srt_compose, mock_time_sleep):
        self._setup_internal_states_mocks(
            mock_get_session, mock_srt_parse, mock_protect_tags,
            original_srt_text="1\nS1 content\n\n2\nS2 content\n", # Original subtitle text
            parsed_subs_contents=["S1 content", "S2 content"],    # Content of items after srt.parse
            protect_tags_outputs=[self._create_protect_output("S1p"), self._create_protect_output("S2p")] # Output of _protect_subtitle_tags for each item
        )
        
        expected_chunk_to_gtranslate = f"S1p{_CHUNK_SEP}S2p"
        mock_gtranslate.return_value = f"T1{_CHUNK_SEP}T2" 
        
        result = subtitlecat_module.build_download_request(self.core_mock, self.service_name, self.base_action_args)

        self.assertEqual(self.parsed_subs_list_reference[0].content, "T1")
        self.assertEqual(self.parsed_subs_list_reference[1].content, "T2")
        mock_gtranslate.assert_called_once_with(expected_chunk_to_gtranslate, 'fr', self.core_mock, self.service_name)
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Final TII pointer (2) matches total translatable items (2). All items processed/attempted.")
        # Ensure no mismatch or discard logs
        log_calls_str = " ".join([c[0][0] for c in self.core_mock.logger.debug.call_args_list])
        self.assertNotIn("Segment count mismatch", log_calls_str)
        self.assertNotIn("discarded", log_calls_str)

        with patch('io.open', MagicMock()) as mock_io_open:
            self.assertTrue(result['save_callback']("/fake/path.srt"))
            mock_io_open.assert_called_once_with("/fake/path.srt", 'w', encoding='utf-8')


    @patch('a4kSubtitles.services.subtitlecat.time.sleep')
    @patch('a4kSubtitles.services.subtitlecat.srt.compose', side_effect=lambda x: "composed_srt_content")
    @patch('a4kSubtitles.services.subtitlecat.html.unescape', side_effect=lambda x: x)
    @patch('a4kSubtitles.services.subtitlecat._restore_subtitle_tags', side_effect=lambda text, tag_map: text)
    @patch('a4kSubtitles.services.subtitlecat._gtranslate_text_chunk')
    @patch('a4kSubtitles.services.subtitlecat._protect_subtitle_tags')
    @patch('a4kSubtitles.services.subtitlecat.srt.parse')
    @patch('a4kSubtitles.services.subtitlecat._get_session')
    def test_1_2_perfect_match_multi_chunk(self, mock_get_session, mock_srt_parse, mock_protect_tags,
                                          mock_gtranslate, mock_restore_tags, mock_html_unescape,
                                          mock_srt_compose, mock_time_sleep):
        # Force chunking by making protected_text long enough (block_size_chars is 1500)
        s1p_long = "S1p_long_" + "A" * 1400 
        s2p_long = "S2p_long_" + "B" * 1400 
        s3p = "S3p_short"                 

        self._setup_internal_states_mocks(
            mock_get_session, mock_srt_parse, mock_protect_tags,
            original_srt_text=f"1\nS1\n\n2\nS2\n\n3\nS3\n",
            parsed_subs_contents=["S1", "S2", "S3"],
            protect_tags_outputs=[
                self._create_protect_output(s1p_long), 
                self._create_protect_output(s2p_long), 
                self._create_protect_output(s3p)
            ]
        )
        mock_gtranslate.side_effect = ["T1_long", "T2_long", "T3_short"] 
        
        subtitlecat_module.build_download_request(self.core_mock, self.service_name, self.base_action_args)

        self.assertEqual(self.parsed_subs_list_reference[0].content, "T1_long")
        self.assertEqual(self.parsed_subs_list_reference[1].content, "T2_long")
        self.assertEqual(self.parsed_subs_list_reference[2].content, "T3_short")
        
        mock_gtranslate.assert_has_calls([
            call(s1p_long, 'fr', self.core_mock, self.service_name),
            call(s2p_long, 'fr', self.core_mock, self.service_name),
            call(s3p, 'fr', self.core_mock, self.service_name)
        ])
        self.assertEqual(mock_gtranslate.call_count, 3)
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Final TII pointer (3) matches total translatable items (3). All items processed/attempted.")
        log_calls_str = " ".join([c[0][0] for c in self.core_mock.logger.debug.call_args_list])
        self.assertNotIn("Segment count mismatch", log_calls_str)
        self.assertNotIn("discarded", log_calls_str)

    @patch('a4kSubtitles.services.subtitlecat.time.sleep')
    @patch('a4kSubtitles.services.subtitlecat.srt.compose', side_effect=lambda x: "composed_srt_content")
    @patch('a4kSubtitles.services.subtitlecat.html.unescape', side_effect=lambda x: x)
    @patch('a4kSubtitles.services.subtitlecat._restore_subtitle_tags', side_effect=lambda text, tag_map: text)
    @patch('a4kSubtitles.services.subtitlecat._gtranslate_text_chunk')
    @patch('a4kSubtitles.services.subtitlecat._protect_subtitle_tags')
    @patch('a4kSubtitles.services.subtitlecat.srt.parse')
    @patch('a4kSubtitles.services.subtitlecat._get_session')
    def test_2_1_fewer_segments_returned_single_chunk(self, mock_get_session, mock_srt_parse, mock_protect_tags,
                                                     mock_gtranslate, mock_restore_tags, mock_html_unescape,
                                                     mock_srt_compose, mock_time_sleep):
        self._setup_internal_states_mocks(
            mock_get_session, mock_srt_parse, mock_protect_tags,
            original_srt_text="1\nS1\n\n2\nS2\n\n3\nS3\n",
            parsed_subs_contents=["S1", "S2", "S3"],
            protect_tags_outputs=[self._create_protect_output("S1p"), self._create_protect_output("S2p"), self._create_protect_output("S3p")]
        )
        expected_chunk = f"S1p{_CHUNK_SEP}S2p{_CHUNK_SEP}S3p" 
        mock_gtranslate.return_value = "T1" # Returns 1 segment for a 3-segment chunk

        subtitlecat_module.build_download_request(self.core_mock, self.service_name, self.base_action_args)

        self.assertEqual(self.parsed_subs_list_reference[0].content, "T1")
        self.assertEqual(self.parsed_subs_list_reference[1].content, "S2") 
        self.assertEqual(self.parsed_subs_list_reference[2].content, "S3") 
        mock_gtranslate.assert_called_once_with(expected_chunk, 'fr', self.core_mock, self.service_name)
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Segment count mismatch for chunk 1. Expected 3, got 1. Processing min of the two.")
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Final TII pointer (3) matches total translatable items (3). All items processed/attempted.")
        # The "Segment count mismatch" log indicates some items might not have received translations.

    @patch('a4kSubtitles.services.subtitlecat.time.sleep')
    @patch('a4kSubtitles.services.subtitlecat.srt.compose', side_effect=lambda x: "composed_srt_content")
    @patch('a4kSubtitles.services.subtitlecat.html.unescape', side_effect=lambda x: x)
    @patch('a4kSubtitles.services.subtitlecat._restore_subtitle_tags', side_effect=lambda text, tag_map: text)
    @patch('a4kSubtitles.services.subtitlecat._gtranslate_text_chunk')
    @patch('a4kSubtitles.services.subtitlecat._protect_subtitle_tags')
    @patch('a4kSubtitles.services.subtitlecat.srt.parse')
    @patch('a4kSubtitles.services.subtitlecat._get_session')
    def test_2_2_fewer_segments_returned_multi_chunk(self, mock_get_session, mock_srt_parse, mock_protect_tags,
                                                    mock_gtranslate, mock_restore_tags, mock_html_unescape,
                                                    mock_srt_compose, mock_time_sleep):
        s1p_long = "S1p_long_" + "A" * 1400
        s2p = "S2p_item2"
        s3p = "S3p_item3"
        # Chunking: [s1p_long], [s2p_item2_CHUNK_SEP_s3p_item3]
        self._setup_internal_states_mocks(
            mock_get_session, mock_srt_parse, mock_protect_tags,
            original_srt_text=f"1\nS1\n\n2\nS2\n\n3\nS3\n",
            parsed_subs_contents=["S1", "S2", "S3"],
            protect_tags_outputs=[self._create_protect_output(s1p_long), self._create_protect_output(s2p), self._create_protect_output(s3p)]
        )
        
        mock_gtranslate.side_effect = [ "T1_long", "T2_item2" ]
        
        subtitlecat_module.build_download_request(self.core_mock, self.service_name, self.base_action_args)

        self.assertEqual(self.parsed_subs_list_reference[0].content, "T1_long")
        self.assertEqual(self.parsed_subs_list_reference[1].content, "T2_item2") 
        self.assertEqual(self.parsed_subs_list_reference[2].content, "S3")      
        
        mock_gtranslate.assert_has_calls([
            call(s1p_long, 'fr', self.core_mock, self.service_name),
            call(f"{s2p}{_CHUNK_SEP}{s3p}", 'fr', self.core_mock, self.service_name)
        ])
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Segment count mismatch for chunk 2. Expected 2, got 1. Processing min of the two.")
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Final TII pointer (3) matches total translatable items (3). All items processed/attempted.")

    @patch('a4kSubtitles.services.subtitlecat.time.sleep')
    @patch('a4kSubtitles.services.subtitlecat.srt.compose', side_effect=lambda x: "composed_srt_content")
    @patch('a4kSubtitles.services.subtitlecat.html.unescape', side_effect=lambda x: x)
    @patch('a4kSubtitles.services.subtitlecat._restore_subtitle_tags', side_effect=lambda text, tag_map: text)
    @patch('a4kSubtitles.services.subtitlecat._gtranslate_text_chunk')
    @patch('a4kSubtitles.services.subtitlecat._protect_subtitle_tags')
    @patch('a4kSubtitles.services.subtitlecat.srt.parse')
    @patch('a4kSubtitles.services.subtitlecat._get_session')
    def test_3_1_more_segments_returned_single_chunk(self, mock_get_session, mock_srt_parse, mock_protect_tags,
                                                   mock_gtranslate, mock_restore_tags, mock_html_unescape,
                                                   mock_srt_compose, mock_time_sleep):
        self._setup_internal_states_mocks(
            mock_get_session, mock_srt_parse, mock_protect_tags,
            original_srt_text="1\nS1\n\n2\nS2\n",
            parsed_subs_contents=["S1", "S2"],
            protect_tags_outputs=[self._create_protect_output("S1p"), self._create_protect_output("S2p")]
        )
        expected_chunk = f"S1p{_CHUNK_SEP}S2p" 
        mock_gtranslate.return_value = f"T1{_CHUNK_SEP}T2{_CHUNK_SEP}ExtraT3" 

        subtitlecat_module.build_download_request(self.core_mock, self.service_name, self.base_action_args)

        self.assertEqual(self.parsed_subs_list_reference[0].content, "T1")
        self.assertEqual(self.parsed_subs_list_reference[1].content, "T2") 
        mock_gtranslate.assert_called_once_with(expected_chunk, 'fr', self.core_mock, self.service_name)
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Segment count mismatch for chunk 1. Expected 2, got 3. Processing min of the two.")
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Chunk 1: Received 3 segments, but only processed 2 based on original chunking. 1 translated segments were discarded.")
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Final TII pointer (2) matches total translatable items (2). All items processed/attempted.")

    @patch('a4kSubtitles.services.subtitlecat.time.sleep')
    @patch('a4kSubtitles.services.subtitlecat.srt.compose', side_effect=lambda x: "composed_srt_content")
    @patch('a4kSubtitles.services.subtitlecat.html.unescape', side_effect=lambda x: x)
    @patch('a4kSubtitles.services.subtitlecat._restore_subtitle_tags', side_effect=lambda text, tag_map: text)
    @patch('a4kSubtitles.services.subtitlecat._gtranslate_text_chunk')
    @patch('a4kSubtitles.services.subtitlecat._protect_subtitle_tags')
    @patch('a4kSubtitles.services.subtitlecat.srt.parse')
    @patch('a4kSubtitles.services.subtitlecat._get_session')
    def test_3_2_more_segments_returned_multi_chunk(self, mock_get_session, mock_srt_parse, mock_protect_tags,
                                                    mock_gtranslate, mock_restore_tags, mock_html_unescape,
                                                    mock_srt_compose, mock_time_sleep):
        s1p_long = "S1p_long_" + "A" * 1400
        s2p = "S2p_item2"
        # Chunking: [s1p_long], [s2p_item2]
        self._setup_internal_states_mocks(
            mock_get_session, mock_srt_parse, mock_protect_tags,
            original_srt_text=f"1\nS1\n\n2\nS2\n",
            parsed_subs_contents=["S1", "S2"],
            protect_tags_outputs=[self._create_protect_output(s1p_long), self._create_protect_output(s2p)]
        )
        
        mock_gtranslate.side_effect = [ f"T1_long{_CHUNK_SEP}ExtraT1",  f"T2_item2{_CHUNK_SEP}ExtraT2" ]
        
        subtitlecat_module.build_download_request(self.core_mock, self.service_name, self.base_action_args)

        self.assertEqual(self.parsed_subs_list_reference[0].content, "T1_long")
        self.assertEqual(self.parsed_subs_list_reference[1].content, "T2_item2")
        
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Segment count mismatch for chunk 1. Expected 1, got 2. Processing min of the two.")
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Chunk 1: Received 2 segments, but only processed 1 based on original chunking. 1 translated segments were discarded.")
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Segment count mismatch for chunk 2. Expected 1, got 2. Processing min of the two.")
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Chunk 2: Received 2 segments, but only processed 1 based on original chunking. 1 translated segments were discarded.")
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Final TII pointer (2) matches total translatable items (2). All items processed/attempted.")

    @patch('a4kSubtitles.services.subtitlecat.time.sleep')
    @patch('a4kSubtitles.services.subtitlecat.srt.compose', side_effect=lambda x: "composed_srt_content")
    @patch('a4kSubtitles.services.subtitlecat.html.unescape', side_effect=lambda x: x)
    @patch('a4kSubtitles.services.subtitlecat._restore_subtitle_tags', side_effect=lambda text, tag_map: text)
    @patch('a4kSubtitles.services.subtitlecat._gtranslate_text_chunk')
    @patch('a4kSubtitles.services.subtitlecat._protect_subtitle_tags')
    @patch('a4kSubtitles.services.subtitlecat.srt.parse')
    @patch('a4kSubtitles.services.subtitlecat._get_session')
    def test_4_chunk_sep_usage_and_trailing_segment_handling(self, mock_get_session, mock_srt_parse, mock_protect_tags,
                                                              mock_gtranslate, mock_restore_tags, mock_html_unescape,
                                                              mock_srt_compose, mock_time_sleep):
        self._setup_internal_states_mocks(
            mock_get_session, mock_srt_parse, mock_protect_tags,
            original_srt_text="1\nS1\n\n2\nS2\n",
            parsed_subs_contents=["S1", "S2"],
            protect_tags_outputs=[self._create_protect_output("S1p"), self._create_protect_output("S2p")]
        )
        expected_chunk = f"S1p{_CHUNK_SEP}S2p"
        mock_gtranslate.return_value = f"T1{_CHUNK_SEP}T2{_CHUNK_SEP}" # Trailing separator

        subtitlecat_module.build_download_request(self.core_mock, self.service_name, self.base_action_args)
        
        self.assertEqual(self.parsed_subs_list_reference[0].content, "T1")
        self.assertEqual(self.parsed_subs_list_reference[1].content, "T2")
        mock_gtranslate.assert_called_once_with(expected_chunk, 'fr', self.core_mock, self.service_name)
        log_calls_str = " ".join([c[0][0] for c in self.core_mock.logger.debug.call_args_list])
        self.assertNotIn("Segment count mismatch", log_calls_str) # Trailing sep is popped, so counts match
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Final TII pointer (2) matches total translatable items (2). All items processed/attempted.")

    @patch('a4kSubtitles.services.subtitlecat.time.sleep')
    @patch('a4kSubtitles.services.subtitlecat.srt.compose') 
    @patch('a4kSubtitles.services.subtitlecat._gtranslate_text_chunk')
    @patch('a4kSubtitles.services.subtitlecat._protect_subtitle_tags')
    @patch('a4kSubtitles.services.subtitlecat.srt.parse')
    @patch('a4kSubtitles.services.subtitlecat._get_session')
    def test_5_empty_translatable_items_info(self, mock_get_session, mock_srt_parse, mock_protect_tags,
                                             mock_gtranslate, mock_srt_compose_call, mock_time_sleep):
        self._setup_internal_states_mocks(
            mock_get_session, mock_srt_parse, mock_protect_tags,
            original_srt_text="1\n<i>empty</i>\n", 
            parsed_subs_contents=["<i>empty</i>"],    
            protect_tags_outputs=[self._create_protect_output("<i>empty</i>", {}, True)] 
        )
        
        result = subtitlecat_module.build_download_request(self.core_mock, self.service_name, self.base_action_args)

        mock_gtranslate.assert_not_called()
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Identified 0 translatable subtitle items (excluding all-tag lines).")
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Split translatable items into 0 chunks for translation.")
        mock_srt_compose_call.assert_called_once_with(self.parsed_subs_list_reference)
        with patch('io.open', MagicMock()) as mock_io_open: # save_callback should still work
            self.assertTrue(result['save_callback']("/fake/path.srt"))

    @patch('a4kSubtitles.services.subtitlecat.time.sleep')
    @patch('a4kSubtitles.services.subtitlecat.srt.compose', side_effect=lambda x: "composed_srt_content")
    @patch('a4kSubtitles.services.subtitlecat.html.unescape', side_effect=lambda x: x)
    @patch('a4kSubtitles.services.subtitlecat._restore_subtitle_tags', side_effect=lambda text, tag_map: text)
    @patch('a4kSubtitles.services.subtitlecat._gtranslate_text_chunk')
    @patch('a4kSubtitles.services.subtitlecat._protect_subtitle_tags')
    @patch('a4kSubtitles.services.subtitlecat.srt.parse')
    @patch('a4kSubtitles.services.subtitlecat._get_session')
    def test_6_single_segment_variations(self, mock_get_session, mock_srt_parse, mock_protect_tags, 
                                         mock_gtranslate, mock_restore_tags, mock_html_unescape, 
                                         mock_srt_compose, mock_time_sleep):
        # Test 6.1: Single Segment - Perfect Match
        self.core_mock.logger.reset_mock(); mock_gtranslate.reset_mock(); mock_protect_tags.reset_mock(); mock_srt_parse.reset_mock(); # Clean slate
        self._setup_internal_states_mocks(
            mock_get_session, mock_srt_parse, mock_protect_tags,
            original_srt_text="1\nS1\n", parsed_subs_contents=["S1"],
            protect_tags_outputs=[self._create_protect_output("S1p")]
        )
        mock_gtranslate.return_value = "T1" 
        subtitlecat_module.build_download_request(self.core_mock, self.service_name, self.base_action_args)
        self.assertEqual(self.parsed_subs_list_reference[0].content, "T1")
        mock_gtranslate.assert_called_with("S1p", 'fr', self.core_mock, self.service_name) 
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Final TII pointer (1) matches total translatable items (1). All items processed/attempted.")
        self.assertFalse(any("Segment count mismatch" in c[0][0] for c in self.core_mock.logger.debug.call_args_list))

        # Test 6.2: Single Segment - Fewer Returned
        self.core_mock.logger.reset_mock(); mock_gtranslate.reset_mock(); mock_protect_tags.reset_mock(); mock_srt_parse.reset_mock();
        self._setup_internal_states_mocks(
            mock_get_session, mock_srt_parse, mock_protect_tags,
            original_srt_text="1\nS1\n", parsed_subs_contents=["S1"],
            protect_tags_outputs=[self._create_protect_output("S1p")]
        )
        mock_gtranslate.return_value = "" 
        subtitlecat_module.build_download_request(self.core_mock, self.service_name, self.base_action_args)
        self.assertEqual(self.parsed_subs_list_reference[0].content, "S1") 
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Segment count mismatch for chunk 1. Expected 1, got 0. Processing min of the two.")
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Final TII pointer (1) matches total translatable items (1). All items processed/attempted.")

        # Test 6.3: Single Segment - More Returned
        self.core_mock.logger.reset_mock(); mock_gtranslate.reset_mock(); mock_protect_tags.reset_mock(); mock_srt_parse.reset_mock();
        self._setup_internal_states_mocks(
            mock_get_session, mock_srt_parse, mock_protect_tags,
            original_srt_text="1\nS1\n", parsed_subs_contents=["S1"],
            protect_tags_outputs=[self._create_protect_output("S1p")]
        )
        mock_gtranslate.return_value = f"T1{_CHUNK_SEP}ExtraT" 
        subtitlecat_module.build_download_request(self.core_mock, self.service_name, self.base_action_args)
        self.assertEqual(self.parsed_subs_list_reference[0].content, "T1") 
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Segment count mismatch for chunk 1. Expected 1, got 2. Processing min of the two.")
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Chunk 1: Received 2 segments, but only processed 1 based on original chunking. 1 translated segments were discarded.")
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Final TII pointer (1) matches total translatable items (1). All items processed/attempted.")


    @patch('a4kSubtitles.services.subtitlecat.time.sleep')
    @patch('a4kSubtitles.services.subtitlecat.srt.compose', side_effect=lambda x: "composed_srt_content")
    @patch('a4kSubtitles.services.subtitlecat.html.unescape', side_effect=lambda x: x)
    @patch('a4kSubtitles.services.subtitlecat._restore_subtitle_tags', side_effect=lambda text, tag_map: text)
    @patch('a4kSubtitles.services.subtitlecat._gtranslate_text_chunk')
    @patch('a4kSubtitles.services.subtitlecat._protect_subtitle_tags')
    @patch('a4kSubtitles.services.subtitlecat.srt.parse')
    @patch('a4kSubtitles.services.subtitlecat._get_session')
    def test_7_pointer_advancement_and_break_logic(self, mock_get_session, mock_srt_parse, mock_protect_tags,
                                                   mock_gtranslate, mock_restore_tags, mock_html_unescape,
                                                   mock_srt_compose, mock_time_sleep):
        # Scenario for the log: "All translatable item slots processed...subsequent chunks (if any) will be skipped."
        # This requires: current_TII_pointer >= len(tii) AND i < len(chunks) - 1.
        # (TII exhausted, but more chunks were scheduled).
        # This implies an inconsistency where sum(original_segments_for_chunks_count) (which should be len(tii))
        # is less than what len(chunks) implies, or chunking produced "empty" tailing chunks.
        # Current chunking logic makes sum(original_segments_for_chunks_count) == len(tii).
        # And current_TII_pointer advances by expected_segments_this_chunk.
        # So pointer should be len(tii) when all items are processed.
        # The loop `for i, text_chunk_to_translate in enumerate(chunks):` will then terminate.
        # If `i` was less than `len(chunks)-1` at that point, the log would trigger.
        # This means the number of chunks generated was more than needed for the TII items.
        # Example: TII has 1 item. Chunking (due to extreme length of this 1 item's protected text,
        # exceeding block_size_chars multiple times) results in, say, 2 chunks being *formed* by the
        # chunking loop, but original_segments_for_chunks_count is [1, 0] effectively.
        # This is not how current chunking works. One TII item becomes one segment in a chunk.
        # A TII item's protected_text isn't split by the client code *before* going to gtranslate.

        # The most straightforward way to test the break and the "all slots processed" log
        # is to have TII items finish processing before all *potential* chunks (if chunking was weird) are done.
        # But with current logic, the number of chunks is directly tied to processing TII items.
        
        # Test general break logic:
        # TII has 2 items, forming 2 chunks.
        s1p_long = "S1p_long_" + "A" * 1400
        s2p = "S2p_item2"
        self._setup_internal_states_mocks(
            mock_get_session, mock_srt_parse, mock_protect_tags,
            original_srt_text=f"1\nS1\n\n2\nS2\n",
            parsed_subs_contents=["S1", "S2"],
            protect_tags_outputs=[self._create_protect_output(s1p_long), self._create_protect_output(s2p)]
        )
        mock_gtranslate.side_effect = ["T1_long", "T2_item2"]
        
        subtitlecat_module.build_download_request(self.core_mock, self.service_name, self.base_action_args)
        
        # After chunk 1 (i=0): pointer = 1. len(tii) = 2. No break.
        # After chunk 2 (i=1): pointer = 2. len(tii) = 2. Break condition (2>=2) met.
        # Since i (1) is NOT < len(chunks)-1 (which is 2-1=1), the specific log isn't hit.
        # This is normal termination.
        self.core_mock.logger.debug.assert_any_call(f"[{self.service_name}] Final TII pointer (2) matches total translatable items (2). All items processed/attempted.")
        self.core_mock.logger.info("Test 7: Specific log for 'subsequent chunks skipped' is hard to trigger with current deterministic chunking. General break logic (terminating after all items processed) is covered.")


    def test_8_target_tii_index_out_of_bounds_log_unreachable(self):
        # This documents the analysis that the error log:
        #   core.logger.error(f"[{service_name}] Error: target_tii_index ({target_tii_index}) out of bounds...")
        # is likely unreachable due to the surrounding logic:
        # 1. `segments_to_process_for_this_chunk = min(expected_segments_this_chunk, received_segments_this_chunk)`.
        # 2. Loop for `k_segment_in_chunk` is `range(segments_to_process_for_this_chunk)`.
        # 3. `target_tii_index = current_TII_pointer + k_segment_in_chunk`.
        # 4. `current_TII_pointer` is the start of TII items for this chunk.
        # 5. `expected_segments_this_chunk` = number of TII items in this chunk.
        # Thus, `current_TII_pointer + k_segment_in_chunk` should always be a valid index within the TII items
        # allocated for this chunk because `k_segment_in_chunk < expected_segments_this_chunk`.
        # The main loop's break condition (`current_TII_pointer >= len(tii)`) also protects this.
        self.core_mock.logger.info("Test 8: Analysis suggests 'target_tii_index_out_of_bounds' log is unreachable with current logic.")
        pass

if __name__ == '__main__':
    unittest.main()
