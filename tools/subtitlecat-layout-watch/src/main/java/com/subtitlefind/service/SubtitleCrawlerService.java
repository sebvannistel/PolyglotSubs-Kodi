package com.subtitlefind.service;

import com.subtitlefind.model.SubtitleInfo;
import okhttp3.Interceptor;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.ResponseBody;
import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.nodes.Element;
import org.jsoup.select.Elements;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Headless crawler extracted from https://github.com/Witten1997/subtitle-find.
 */
public class SubtitleCrawlerService {

    private static final Logger logger = LoggerFactory.getLogger(SubtitleCrawlerService.class);
    private static final String BASE_URL = "https://www.subtitlecat.com";
    private static final String SEARCH_URL = BASE_URL + "/index.php";

    private final OkHttpClient httpClient;
    private final Pattern downloadPattern = Pattern.compile("(\\d+)");
    private final Pattern commentPattern = Pattern.compile("(\\d+)");

    private SearchDiagnostics lastSearchDiagnostics = SearchDiagnostics.empty();
    private String lastResponseBody = "";

    public SubtitleCrawlerService() {
        this.httpClient = new OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .addInterceptor(new UserAgentInterceptor())
            .build();
    }

    public List<SubtitleInfo> searchSubtitles(String keyword) {
        List<SubtitleInfo> subtitles = new ArrayList<>();
        SearchDiagnostics.Builder diagnostics = SearchDiagnostics.builder(keyword);
        lastResponseBody = "";

        try {
            logger.info("Searching subtitlecat for keyword: {}", keyword);
            String encodedKeyword = URLEncoder.encode(keyword, StandardCharsets.UTF_8);
            String searchUrl = SEARCH_URL + "?search=" + encodedKeyword;
            diagnostics.searchUrl(searchUrl);

            Request request = new Request.Builder()
                .url(searchUrl)
                .get()
                .build();

            List<String> attemptedSelectors = new ArrayList<>();
            Elements rows = null;
            String matchedSelector = null;

            try (Response response = httpClient.newCall(request).execute()) {
                diagnostics.statusCode(response.code());
                diagnostics.requestSuccessful(response.isSuccessful());
                if (!response.isSuccessful()) {
                    diagnostics.failureReason("http_" + response.code());
                    logger.error("Search request failed, status code: {}", response.code());
                } else {
                    String responseBody = getResponseBodyWithCorrectEncoding(response);
                    lastResponseBody = responseBody;
                    diagnostics.responseSnippet(responseBody);

                    try {
                        Document doc = Jsoup.parse(responseBody);
                        String[] selectors = {
                            "div.subtitles table tbody tr",
                            ".sub-table tbody tr",
                            "table tbody tr",
                            ".results tbody tr",
                            ".search-results tbody tr",
                            "tbody tr",
                            "tr"
                        };

                        for (String selector : selectors) {
                            attemptedSelectors.add(selector);
                            Elements candidate = doc.select(selector);
                            if (!candidate.isEmpty()) {
                                rows = candidate;
                                matchedSelector = selector;
                                logger.debug("Selector '{}' returned {} rows", selector, candidate.size());
                                break;
                            }
                        }

                        if (rows == null || rows.isEmpty()) {
                            diagnostics.failureReason("no_rows_detected");
                            logger.warn("No rows discovered for keyword: {}", keyword);
                        } else {
                            diagnostics.rowCount(rows.size());

                            for (int i = 0; i < Math.min(rows.size(), 5); i++) {
                                Element row = rows.get(i);
                                SubtitleInfo subtitleInfo = parseSubtitleRow(row);
                                if (subtitleInfo != null && isMatch(subtitleInfo.getTitle(), keyword)) {
                                    subtitles.add(subtitleInfo);
                                }
                            }

                            subtitles.sort((a, b) -> {
                                if (b.getComments() != a.getComments()) {
                                    return Integer.compare(b.getComments(), a.getComments());
                                }
                                return Integer.compare(b.getDownloads(), a.getDownloads());
                            });
                        }
                    } catch (Exception parseError) {
                        diagnostics.failureReason("parse_exception: " + parseError.getClass().getSimpleName());
                        logger.error("Failed to parse search response: {}", parseError.getMessage(), parseError);
                    }
                }
            }
            diagnostics.attemptedSelectors(attemptedSelectors);
            diagnostics.matchedSelector(matchedSelector);
        } catch (IOException e) {
            diagnostics.failureReason("io_exception: " + e.getClass().getSimpleName());
            logger.error("Network error while searching subtitles: {}", e.getMessage(), e);
        } catch (Exception e) {
            diagnostics.failureReason("exception: " + e.getClass().getSimpleName());
            logger.error("Unexpected error while searching subtitles: {}", e.getMessage(), e);
        } finally {
            lastSearchDiagnostics = diagnostics.build();
        }

        logger.info("Search complete, {} candidate subtitles found", subtitles.size());
        return subtitles;
    }

    public SubtitleInfo getSubtitleDownloadUrl(SubtitleInfo subtitleInfo) {
        try {
            String href = subtitleInfo.getHref();
            if (href == null || href.isEmpty()) {
                return subtitleInfo;
            }
            String normalizedHref = href.startsWith("/") ? href.substring(1) : href;
            String detailUrl = BASE_URL + "/" + normalizedHref;
            logger.debug("Fetching subtitle detail page: {}", detailUrl);

            Request request = new Request.Builder()
                .url(detailUrl)
                .get()
                .build();

            try (Response response = httpClient.newCall(request).execute()) {
                if (!response.isSuccessful()) {
                    logger.error("Detail request failed, status code: {}", response.code());
                    return subtitleInfo;
                }

                String responseBody = getResponseBodyWithCorrectEncoding(response);
                String downloadUrl = parseDownloadUrl(responseBody, subtitleInfo.getLanguage());

                if (downloadUrl != null) {
                    if (!downloadUrl.startsWith("http")) {
                        subtitleInfo.setDownloadUrl(BASE_URL + downloadUrl);
                    } else {
                        subtitleInfo.setDownloadUrl(downloadUrl);
                    }
                    logger.debug("Resolved download URL: {}", subtitleInfo.getDownloadUrl());
                } else {
                    logger.warn("No download link found for subtitle {}", subtitleInfo.getTitle());
                }
            }
        } catch (Exception e) {
            logger.error("Error fetching download URL: {}", e.getMessage(), e);
        }

        return subtitleInfo;
    }

    public SearchDiagnostics getLastSearchDiagnostics() {
        return lastSearchDiagnostics;
    }

    public String getLastResponseBody() {
        return lastResponseBody;
    }

    private SubtitleInfo parseSubtitleRow(Element row) {
        try {
            Elements tds = row.select("td");
            if (tds.size() < 4) {
                return null;
            }

            Element titleCell = tds.get(0);
            Element titleLink = titleCell.selectFirst("a");
            if (titleLink == null) {
                return null;
            }

            String title = titleLink.text().trim();
            String href = titleLink.attr("href");

            Element downloadCell = tds.get(1);
            int downloads = parseNumber(downloadCell.text());

            Element commentCell = tds.get(2);
            int comments = parseNumber(commentCell.text());

            return new SubtitleInfo(title, href, null, downloads, comments, "zh-CN");
        } catch (Exception e) {
            logger.error("Error parsing subtitle row: {}", e.getMessage(), e);
            return null;
        }
    }

    private String parseDownloadUrl(String html, String language) {
        try {
            Document doc = Jsoup.parse(html);

            Element downloadElement = doc.selectFirst("#download_zh-CN, #download_zh, .download-link");
            if (downloadElement != null) {
                String href = downloadElement.attr("href");
                if (href != null && !href.isEmpty()) {
                    return href;
                }
            }

            Elements downloadLinks = doc.select("a[href*='download'], .download");
            for (Element link : downloadLinks) {
                String href = link.attr("href");
                if (href.contains("download") || href.contains(".srt") || href.contains(".ass")) {
                    return href;
                }
            }
        } catch (Exception e) {
            logger.error("Error parsing download link: {}", e.getMessage(), e);
        }

        return null;
    }

    private boolean isMatch(String title, String keyword) {
        if (title == null || keyword == null) {
            return false;
        }

        String lowerTitle = title.toLowerCase();
        String lowerKeyword = keyword.toLowerCase();

        String cleanedTitle = VideoFileScanner.getCleanedFileNameForSearch(lowerTitle);

        if (lowerTitle.contains(lowerKeyword) || lowerKeyword.contains(lowerTitle)) {
            return true;
        }

        if (cleanedTitle.contains(lowerKeyword) || lowerKeyword.contains(cleanedTitle)) {
            return true;
        }

        String cleanedKeyword = VideoFileScanner.getCleanedFileNameForSearch(lowerKeyword);
        return lowerTitle.contains(cleanedKeyword) || cleanedKeyword.contains(lowerTitle);
    }

    private int parseNumber(String text) {
        if (text == null || text.trim().isEmpty()) {
            return 0;
        }

        Matcher matcher = downloadPattern.matcher(text.trim());
        if (matcher.find()) {
            try {
                return Integer.parseInt(matcher.group(1));
            } catch (NumberFormatException e) {
                logger.debug("Unable to parse number from text: {}", text);
            }
        }
        return 0;
    }

    private String getResponseBodyWithCorrectEncoding(Response response) throws IOException {
        ResponseBody body = response.body();
        if (body == null) {
            return "";
        }

        String contentType = response.header("Content-Type");
        Charset charset = StandardCharsets.UTF_8;

        if (contentType != null) {
            String lowered = contentType.toLowerCase();
            if (lowered.contains("charset=")) {
                String[] parts = lowered.split("charset=");
                if (parts.length > 1) {
                    String charsetName = parts[1].split(";")[0].trim();
                    try {
                        charset = Charset.forName(charsetName);
                        logger.debug("Detected response charset: {}", charsetName);
                    } catch (Exception e) {
                        logger.debug("Unsupported charset {}, defaulting to UTF-8", charsetName);
                    }
                }
            }
        }

        byte[] bytes = body.bytes();
        String content = new String(bytes, charset);

        if (charset == StandardCharsets.UTF_8 && containsGarbledText(content)) {
            try {
                String gbkContent = new String(bytes, Charset.forName("GBK"));
                if (!containsGarbledText(gbkContent)) {
                    return gbkContent;
                }
            } catch (Exception ignored) {
            }

            try {
                String isoContent = new String(bytes, StandardCharsets.ISO_8859_1);
                if (!containsGarbledText(isoContent)) {
                    return isoContent;
                }
            } catch (Exception ignored) {
            }
        }

        return content;
    }

    private boolean containsGarbledText(String text) {
        if (text == null || text.isEmpty()) {
            return false;
        }
        long questionMarks = text.chars().filter(ch -> ch == '?' || ch == 65533).count();
        return questionMarks > text.length() * 0.1;
    }

    public void close() {
        httpClient.dispatcher().executorService().shutdown();
        httpClient.connectionPool().evictAll();
    }

    private static class UserAgentInterceptor implements Interceptor {
        @Override
        public Response intercept(Chain chain) throws IOException {
            Request originalRequest = chain.request();
            Request requestWithUserAgent = originalRequest.newBuilder()
                .header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
                .header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8")
                .header("Accept-Language", "en-US,en;q=0.5")
                .header("Connection", "keep-alive")
                .header("Upgrade-Insecure-Requests", "1")
                .build();
            return chain.proceed(requestWithUserAgent);
        }
    }

    public static final class SearchDiagnostics {
        private final String keyword;
        private final String searchUrl;
        private final int statusCode;
        private final String matchedSelector;
        private final List<String> attemptedSelectors;
        private final int rowCount;
        private final String failureReason;
        private final String responseSnippet;
        private final boolean requestSuccessful;

        private SearchDiagnostics(Builder builder) {
            this.keyword = builder.keyword;
            this.searchUrl = builder.searchUrl;
            this.statusCode = builder.statusCode;
            this.matchedSelector = builder.matchedSelector;
            this.attemptedSelectors = List.copyOf(builder.attemptedSelectors);
            this.rowCount = builder.rowCount;
            this.failureReason = builder.failureReason;
            this.responseSnippet = builder.responseSnippet;
            this.requestSuccessful = builder.requestSuccessful;
        }

        public static SearchDiagnostics empty() {
            return builder("").build();
        }

        public static Builder builder(String keyword) {
            return new Builder(keyword);
        }

        public String getKeyword() {
            return keyword;
        }

        public String getSearchUrl() {
            return searchUrl;
        }

        public int getStatusCode() {
            return statusCode;
        }

        public String getMatchedSelector() {
            return matchedSelector;
        }

        public List<String> getAttemptedSelectors() {
            return attemptedSelectors;
        }

        public int getRowCount() {
            return rowCount;
        }

        public String getFailureReason() {
            return failureReason;
        }

        public String getResponseSnippet() {
            return responseSnippet;
        }

        public boolean isRequestSuccessful() {
            return requestSuccessful;
        }

        public static final class Builder {
            private final String keyword;
            private String searchUrl = "";
            private int statusCode = 0;
            private String matchedSelector = null;
            private List<String> attemptedSelectors = new ArrayList<>();
            private int rowCount = 0;
            private String failureReason = null;
            private String responseSnippet = "";
            private boolean requestSuccessful = false;

            private Builder(String keyword) {
                this.keyword = keyword;
            }

            public Builder searchUrl(String searchUrl) {
                this.searchUrl = searchUrl;
                return this;
            }

            public Builder statusCode(int statusCode) {
                this.statusCode = statusCode;
                return this;
            }

            public Builder matchedSelector(String matchedSelector) {
                this.matchedSelector = matchedSelector;
                return this;
            }

            public Builder attemptedSelectors(List<String> attemptedSelectors) {
                this.attemptedSelectors = new ArrayList<>(attemptedSelectors);
                return this;
            }

            public Builder rowCount(int rowCount) {
                this.rowCount = rowCount;
                return this;
            }

            public Builder failureReason(String failureReason) {
                if (failureReason != null && !failureReason.isEmpty() && this.failureReason == null) {
                    this.failureReason = failureReason;
                }
                return this;
            }

            public Builder responseSnippet(String responseBody) {
                this.responseSnippet = trimSnippet(responseBody);
                return this;
            }

            public Builder requestSuccessful(boolean requestSuccessful) {
                this.requestSuccessful = requestSuccessful;
                return this;
            }

            public SearchDiagnostics build() {
                return new SearchDiagnostics(this);
            }

            private static String trimSnippet(String value) {
                if (value == null) {
                    return "";
                }
                int maxLength = 1200;
                String trimmed = value.replaceAll("\\s+", " ").trim();
                if (trimmed.length() <= maxLength) {
                    return trimmed;
                }
                return trimmed.substring(0, maxLength) + "…";
            }
        }
    }
}
