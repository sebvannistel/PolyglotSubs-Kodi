package com.subtitlefind.cli;

import com.subtitlefind.model.SubtitleInfo;
import com.subtitlefind.service.SubtitleCrawlerService;
import com.subtitlefind.service.SubtitleCrawlerService.DownloadDebugResult;
import com.subtitlefind.service.SubtitleCrawlerService.SearchDebugResult;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class LayoutWatchCli {

    public static void main(String[] args) {
        Map<String, String> options = parseArgs(args);
        if (!options.containsKey("query")) {
            System.err.println("Missing required --query argument");
            System.exit(2);
        }

        String query = options.get("query");
        boolean checkDownload = options.containsKey("check-download");
        int maxResults = 5;
        if (options.containsKey("max-results")) {
            try {
                maxResults = Integer.parseInt(options.get("max-results"));
            } catch (NumberFormatException ex) {
                System.err.println("Invalid integer for --max-results: " + options.get("max-results"));
                System.exit(2);
            }
        }

        SubtitleCrawlerService service = new SubtitleCrawlerService();
        SearchDebugResult searchDebug = service.searchSubtitlesWithDebug(query);
        List<SubtitleInfo> subtitles = new ArrayList<>(searchDebug.getSubtitles());
        if (maxResults > 0 && subtitles.size() > maxResults) {
            subtitles = subtitles.subList(0, maxResults);
        }

        DownloadDebugResult downloadDebug = null;
        if (checkDownload && !subtitles.isEmpty()) {
            downloadDebug = service.getSubtitleDownloadUrlWithDebug(subtitles.get(0));
        }

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("query", query);
        payload.put("status", determineSearchStatus(searchDebug, subtitles));
        payload.put("http_status", searchDebug.getHttpStatus());
        payload.put("search_url", searchDebug.getSearchUrl());
        payload.put("selectors_tried", new ArrayList<>(searchDebug.getSelectorsTried()));
        payload.put("matched_selector", searchDebug.getMatchedSelector());
        payload.put("errors", new ArrayList<>(searchDebug.getErrors()));
        payload.put("result_count", subtitles.size());
        payload.put("search_html_base64", encodeToBase64(searchDebug.getResponseBody()));

        if (!subtitles.isEmpty()) {
            SubtitleInfo top = subtitles.get(0);
            Map<String, Object> topResult = new HashMap<>();
            topResult.put("title", top.getTitle());
            topResult.put("href", top.getHref());
            topResult.put("downloads", top.getDownloads());
            topResult.put("comments", top.getComments());
            payload.put("top_result", topResult);
        } else {
            payload.put("top_result", null);
        }

        if (downloadDebug != null) {
            Map<String, Object> downloadInfo = new LinkedHashMap<>();
            downloadInfo.put("status", determineDownloadStatus(downloadDebug));
            downloadInfo.put("detail_url", downloadDebug.getDetailUrl());
            downloadInfo.put("http_status", downloadDebug.getHttpStatus());
            downloadInfo.put("selectors_tried", new ArrayList<>(downloadDebug.getSelectorsTried()));
            downloadInfo.put("matched_selector", downloadDebug.getMatchedSelector());
            downloadInfo.put("errors", new ArrayList<>(downloadDebug.getErrors()));
            downloadInfo.put("download_url", downloadDebug.getResolvedDownloadUrl());
            downloadInfo.put("detail_html_base64", encodeToBase64(downloadDebug.getResponseBody()));
            payload.put("download", downloadInfo);
        } else {
            payload.put("download", null);
        }

        System.out.println(toJson(payload));
    }

    private static Map<String, String> parseArgs(String[] args) {
        Map<String, String> options = new HashMap<>();
        for (int i = 0; i < args.length; i++) {
            String arg = args[i];
            if (!arg.startsWith("--")) {
                continue;
            }
            String key = arg.substring(2);
            if (key.isEmpty()) {
                continue;
            }
            if ((i + 1) < args.length && !args[i + 1].startsWith("--")) {
                options.put(key, args[++i]);
            } else {
                options.put(key, "true");
            }
        }
        return options;
    }

    private static String determineSearchStatus(SearchDebugResult debug, List<SubtitleInfo> subtitles) {
        if (!debug.getErrors().isEmpty()) {
            return "error";
        }
        if (subtitles.isEmpty()) {
            return "no_results";
        }
        if (debug.getMatchedSelector() == null || debug.getMatchedSelector().isEmpty()) {
            return "selector_fallback";
        }
        return "ok";
    }

    private static String determineDownloadStatus(DownloadDebugResult debug) {
        if (!debug.getErrors().isEmpty()) {
            return "error";
        }
        if (debug.getResolvedDownloadUrl() == null || debug.getResolvedDownloadUrl().isEmpty()) {
            return "no_download";
        }
        if (debug.getMatchedSelector() == null || debug.getMatchedSelector().isEmpty()) {
            return "selector_fallback";
        }
        return "ok";
    }

    private static String encodeToBase64(String value) {
        if (value == null) {
            return null;
        }
        return Base64.getEncoder().encodeToString(value.getBytes(StandardCharsets.UTF_8));
    }

    private static String toJson(Map<String, Object> payload) {
        StringBuilder sb = new StringBuilder();
        sb.append("{");
        boolean first = true;
        for (Map.Entry<String, Object> entry : payload.entrySet()) {
            if (!first) {
                sb.append(",");
            }
            first = false;
            sb.append('"').append(jsonEscape(entry.getKey())).append('"').append(":");
            appendValue(sb, entry.getValue());
        }
        sb.append("}");
        return sb.toString();
    }

    private static void appendValue(StringBuilder sb, Object value) {
        if (value == null) {
            sb.append("null");
        } else if (value instanceof String) {
            sb.append('"').append(jsonEscape((String) value)).append('"');
        } else if (value instanceof Number || value instanceof Boolean) {
            sb.append(value.toString());
        } else if (value instanceof Map) {
            @SuppressWarnings("unchecked")
            Map<String, Object> map = (Map<String, Object>) value;
            sb.append("{");
            boolean first = true;
            for (Map.Entry<String, Object> entry : map.entrySet()) {
                if (!first) {
                    sb.append(",");
                }
                first = false;
                sb.append('"').append(jsonEscape(entry.getKey())).append('"').append(":");
                appendValue(sb, entry.getValue());
            }
            sb.append("}");
        } else if (value instanceof List) {
            @SuppressWarnings("unchecked")
            List<Object> list = (List<Object>) value;
            sb.append("[");
            for (int i = 0; i < list.size(); i++) {
                if (i > 0) {
                    sb.append(",");
                }
                appendValue(sb, list.get(i));
            }
            sb.append("]");
        } else {
            sb.append('"').append(jsonEscape(value.toString())).append('"');
        }
    }

    private static String jsonEscape(String value) {
        StringBuilder escaped = new StringBuilder();
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '\\':
                    escaped.append("\\\\");
                    break;
                case '"':
                    escaped.append("\\\"");
                    break;
                case '\n':
                    escaped.append("\\n");
                    break;
                case '\r':
                    escaped.append("\\r");
                    break;
                case '\t':
                    escaped.append("\\t");
                    break;
                default:
                    if (c < 0x20) {
                        escaped.append(String.format("\\u%04x", (int) c));
                    } else {
                        escaped.append(c);
                    }
                    break;
            }
        }
        return escaped.toString();
    }
}
