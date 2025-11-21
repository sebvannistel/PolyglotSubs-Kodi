import unittest
from unittest.mock import MagicMock, patch, ANY
import sys
import os
import json
from xml.etree import ElementTree

# Mock modules that are not available in the test environment or rely on Kodi
sys.modules['xbmc'] = MagicMock()
mock_addon = MagicMock()
# Return absolute path to /app
mock_addon.getAddonInfo.return_value = "/app"
sys.modules['xbmcaddon'] = MagicMock()
sys.modules['xbmcaddon'].Addon.return_value = mock_addon

sys.modules['xbmcgui'] = MagicMock()
sys.modules['xbmcplugin'] = MagicMock()
sys.modules['xbmcvfs'] = MagicMock()

# Add the repo root to sys.path so we can import a4kSubtitles
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Ensure a4kSubtitles package is initialized
import a4kSubtitles
a4kSubtitles.initialize()

from a4kSubtitles.services import bsplayer

class TestBSPlayer(unittest.TestCase):
    def setUp(self):
        self.core = MagicMock()
        self.core.datetime = MagicMock()
        self.core.time = MagicMock()
        self.core.kodi = MagicMock()
        self.core.utils = MagicMock()
        self.core.services = {
            "bsplayer": MagicMock(display_name="BSPlayer", context=MagicMock(subdomain=None, token=None))
        }
        self.core.ElementTree = ElementTree

        self.service_name = "bsplayer"
        self.core.kodi.xbmc.ISO_639_1 = "iso639_1"

    def test_get_url_rotation(self):
        self.core.datetime.now.return_value.second = 0
        # Access private function using getattr to avoid name mangling
        get_url = getattr(bsplayer, "__get_url")
        url = get_url(self.core, self.service_name)
        self.assertIn("s1.api.bsplayer-subtitles.com", url)

        # Check context caching
        self.core.datetime.now.return_value.second = 1
        url = get_url(self.core, self.service_name)
        self.assertIn("s1.api.bsplayer-subtitles.com", url)

    def test_build_auth_request(self):
        req = bsplayer.build_auth_request(self.core, self.service_name)

        self.assertEqual(req['method'], 'POST')
        self.assertIn('logIn', req['data'])
        self.assertIn('headers', req)
        self.assertIn('SOAPAction', req['headers'])

    def test_parse_auth_response_success(self):
        response = MagicMock()
        response.status_code = 200
        # Valid SOAP response for login
        response.text = """<?xml version="1.0" encoding="UTF-8"?>
        <SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">
           <SOAP-ENV:Body>
              <ns1:logInResponse xmlns:ns1="http://api.bsplayer-subtitles.com/v1.php">
                 <return>
                    <result>200</result>
                    <data>test_token</data>
                 </return>
              </ns1:logInResponse>
           </SOAP-ENV:Body>
        </SOAP-ENV:Envelope>"""

        bsplayer.parse_auth_response(self.core, self.service_name, response)

        self.assertEqual(self.core.services[self.service_name].context.token, "test_token")

    def test_parse_auth_response_failure(self):
        response = MagicMock()
        response.status_code = 500

        bsplayer.parse_auth_response(self.core, self.service_name, response)

        self.assertIsNone(self.core.services[self.service_name].context.token)

    def test_build_search_requests_no_token(self):
        self.core.services[self.service_name].context.token = None

        reqs = bsplayer.build_search_requests(self.core, self.service_name, MagicMock())

        self.assertEqual(reqs, [])

    def test_build_search_requests(self):
        self.core.services[self.service_name].context.token = "test_token"
        self.core.utils.get_lang_ids.return_value = ["eng"]

        meta = MagicMock()
        meta.filesize = "1024"
        meta.filehash = "hash123"
        meta.languages = ["English"]
        meta.imdb_id = "tt1234567"

        reqs = bsplayer.build_search_requests(self.core, self.service_name, meta)

        self.assertEqual(len(reqs), 1)
        data = reqs[0]['data']
        self.assertIn("<handle>test_token</handle>", data)
        self.assertIn("<movieHash>hash123</movieHash>", data)
        self.assertIn("<imdbId>1234567</imdbId>", data)

    def test_parse_search_response(self):
        meta = MagicMock()
        meta.filehash = "hash123"
        meta.languages = ["English"]

        self.core.services[self.service_name].context.lang_ids = ["eng"]
        self.core.utils.get_lang_id.side_effect = lambda l, f: "en"

        response = MagicMock()
        # Note: ElementTree.find with .//return searches recursively.
        # The XML structure needs to be compatible with how ElementTree parses it.
        # We remove namespaces to simplify for the mock ElementTree if needed,
        # but providing a cleaner XML structure helps.
        response.text = """<?xml version="1.0" encoding="UTF-8"?>
        <Envelope>
           <Body>
              <searchSubtitlesResponse>
                 <return>
                    <result><result>200</result></result>
                    <data>
                        <item>
                            <subName>Test Sub.srt</subName>
                            <subLang>eng</subLang>
                            <subRating>10.0</subRating>
                            <subDownloadLink>http://dl.link</subDownloadLink>
                        </item>
                    </data>
                 </return>
              </searchSubtitlesResponse>
           </Body>
        </Envelope>"""

        results = bsplayer.parse_search_response(self.core, self.service_name, meta, response)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['name'], "Test Sub.srt")
        self.assertEqual(results[0]['rating'], 5)
        self.assertEqual(results[0]['action_args']['url'], "http://dl.link")
        self.assertEqual(results[0]['sync'], "true") # meta.filehash is set

    def test_build_download_request(self):
        args = {"url": "http://dl.link"}
        req = bsplayer.build_download_request(self.core, self.service_name, args)

        self.assertEqual(req['method'], 'GET')
        self.assertEqual(req['url'], "http://dl.link")

if __name__ == '__main__':
    unittest.main()
