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
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 字幕网站爬取服务
 * 从 subtitlecat.com 网站爬取字幕信息
 */
public class SubtitleCrawlerService {

    private static final Logger logger = LoggerFactory.getLogger(SubtitleCrawlerService.class);
    private static final String BASE_URL = "https://subtitlecat.com";
    private static final String SEARCH_URL = BASE_URL + "/index.php";

    private final OkHttpClient httpClient;
    private final Pattern downloadPattern = Pattern.compile("(\\d+)");
    private final Pattern commentPattern = Pattern.compile("(\\d+)");

    public SubtitleCrawlerService() {
        this.httpClient = new OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .addInterceptor(new UserAgentInterceptor())
            .build();
    }

    /**
     * 根据关键词搜索字幕
     *
     * @param keyword 搜索关键词（视频文件名）
     * @return 字幕信息列表
     */
    public List<SubtitleInfo> searchSubtitles(String keyword) {
        return searchSubtitlesWithDebug(keyword).getSubtitles();
    }

    /**
     * 根据关键词搜索字幕并返回调试信息
     *
     * @param keyword 搜索关键词
     * @return 调试结果
     */
    public SearchDebugResult searchSubtitlesWithDebug(String keyword) {
        SearchDebugResult debugResult = new SearchDebugResult(keyword);
        List<SubtitleInfo> subtitles = new ArrayList<>();

        try {
            logger.info("开始搜索字幕，关键词: {}", keyword);
            String encodedKeyword = java.net.URLEncoder.encode(keyword, StandardCharsets.UTF_8);
            String searchUrl = SEARCH_URL + "?search=" + encodedKeyword;
            debugResult.setSearchUrl(searchUrl);

            Request request = new Request.Builder()
                .url(searchUrl)
                .get()
                .build();

            try (Response response = httpClient.newCall(request).execute()) {
                debugResult.setHttpStatus(response.code());
                if (!response.isSuccessful()) {
                    logger.error("搜索请求失败，状态码: {}", response.code());
                    debugResult.addError("HTTP_" + response.code());
                    return debugResult;
                }

                String responseBody = getResponseBodyWithCorrectEncoding(response);
                debugResult.setResponseBody(responseBody);
                logger.debug("响应体前100个字符: {}", responseBody.length() > 100 ? responseBody.substring(0, 100) : responseBody);

                subtitles = parseSearchResults(responseBody, keyword, debugResult);
            }
        } catch (IOException e) {
            logger.error("搜索字幕时发生网络错误: {}", e.getMessage(), e);
            debugResult.addError("IO_ERROR: " + e.getMessage());
        } catch (Exception e) {
            logger.error("搜索字幕时发生未知错误: {}", e.getMessage(), e);
            debugResult.addError("UNEXPECTED_ERROR: " + e.getMessage());
        }

        logger.info("搜索完成，找到 {} 个相关字幕", subtitles.size());
        debugResult.setSubtitles(subtitles);
        return debugResult;
    }

    /**
     * 解析搜索结果页面
     *
     * @param html HTML内容
     * @param keyword 搜索关键词
     * @param debug 调试结果
     * @return 字幕信息列表
     */
    private List<SubtitleInfo> parseSearchResults(String html, String keyword, SearchDebugResult debug) {
        List<SubtitleInfo> subtitles = new ArrayList<>();

        try {
            Document doc = Jsoup.parse(html);

            Elements rows = null;
            String[] selectors = {
                ".sub-table tbody tr",
                "table tbody tr",
                ".results tbody tr",
                ".search-results tbody tr",
                "tbody tr",
                "tr"
            };

            for (String selector : selectors) {
                debug.addSelectorTried(selector);
                rows = doc.select(selector);
                if (!rows.isEmpty()) {
                    debug.setMatchedSelector(selector);
                    logger.debug("使用选择器 '{}' 找到 {} 行数据", selector, rows.size());
                    break;
                }
            }

            if (rows == null || rows.isEmpty()) {
                logger.warn("未找到任何表格行数据");
                logger.debug("HTML响应前500字符: {}", html.length() > 500 ? html.substring(0, 500) : html);
                debug.addError("NO_ROWS_FOUND");
                return subtitles;
            }

            for (int i = 0; i < Math.min(rows.size(), 5); i++) {
                Element row = rows.get(i);
                SubtitleInfo subtitleInfo = parseSubtitleRow(row);

                if (subtitleInfo != null) {
                    if (isMatch(subtitleInfo.getTitle(), keyword)) {
                        logger.debug("找到匹配的字幕: {}", subtitleInfo.getTitle());
                        subtitles.add(subtitleInfo);
                    } else {
                        logger.debug("字幕标题不匹配: {}", subtitleInfo.getTitle());
                    }
                }
            }

            subtitles.sort((a, b) -> {
                if (b.getComments() != a.getComments()) {
                    return Integer.compare(b.getComments(), a.getComments());
                }
                return Integer.compare(b.getDownloads(), a.getDownloads());
            });

        } catch (Exception e) {
            logger.error("解析搜索结果时发生错误: {}", e.getMessage(), e);
            debug.addError("PARSE_ERROR: " + e.getMessage());
        }

        return subtitles;
    }

    /**
     * 解析单行字幕信息
     *
     * @param row 表格行元素
     * @return 字幕信息
     */
    private SubtitleInfo parseSubtitleRow(Element row) {
        try {
            Elements tds = row.select("td");
            if (tds.size() < 4) {
                return null;
            }

            Element titleCell = tds.get(0);
            Element titleLink = titleCell.select("a").first();
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
            logger.error("解析字幕行信息时发生错误: {}", e.getMessage(), e);
            return null;
        }
    }

    /**
     * 获取字幕下载链接
     *
     * @param subtitleInfo 字幕信息
     * @return 更新了下载链接的字幕信息
     */
    public SubtitleInfo getSubtitleDownloadUrl(SubtitleInfo subtitleInfo) {
        return getSubtitleDownloadUrlWithDebug(subtitleInfo).getSubtitleInfo();
    }

    /**
     * 获取字幕下载链接并返回调试信息
     *
     * @param subtitleInfo 字幕信息
     * @return 调试结果
     */
    public DownloadDebugResult getSubtitleDownloadUrlWithDebug(SubtitleInfo subtitleInfo) {
        DownloadDebugResult debugResult = new DownloadDebugResult(subtitleInfo);

        try {
            String detailUrl = BASE_URL + "/" + subtitleInfo.getHref();
            debugResult.setDetailUrl(detailUrl);
            logger.debug("获取字幕详情页: {}", detailUrl);

            Request request = new Request.Builder()
                .url(detailUrl)
                .get()
                .build();

            try (Response response = httpClient.newCall(request).execute()) {
                debugResult.setHttpStatus(response.code());
                if (!response.isSuccessful()) {
                    logger.error("获取字幕详情页失败，状态码: {}", response.code());
                    debugResult.addError("HTTP_" + response.code());
                    return debugResult;
                }

                String responseBody = getResponseBodyWithCorrectEncoding(response);
                debugResult.setResponseBody(responseBody);
                String downloadUrl = parseDownloadUrlWithDebug(responseBody, subtitleInfo.getLanguage(), debugResult);

                if (downloadUrl != null) {
                    subtitleInfo.setDownloadUrl(BASE_URL + downloadUrl);
                    debugResult.setResolvedDownloadUrl(subtitleInfo.getDownloadUrl());
                    logger.debug("成功获取下载链接: {}", subtitleInfo.getDownloadUrl());
                } else {
                    logger.warn("未找到中文字幕下载链接");
                    debugResult.addError("NO_DOWNLOAD_LINK");
                }
            }
        } catch (Exception e) {
            logger.error("获取字幕下载链接时发生错误: {}", e.getMessage(), e);
            debugResult.addError("UNEXPECTED_ERROR: " + e.getMessage());
        }

        return debugResult;
    }

    /**
     * 解析下载链接（带调试信息）
     */
    private String parseDownloadUrlWithDebug(String html, String language, DownloadDebugResult debug) {
        try {
            Document doc = Jsoup.parse(html);

            String primarySelector = "#download_zh-CN, #download_zh, .download-link";
            debug.addSelectorTried(primarySelector);
            Element downloadElement = doc.select(primarySelector).first();

            if (downloadElement != null) {
                debug.setMatchedSelector(primarySelector);
                String href = downloadElement.attr("href");
                if (href != null && !href.isEmpty()) {
                    return href;
                }
            }

            Elements downloadLinks = doc.select("a[href*='download']");
            debug.addSelectorTried("a[href*='download']");
            for (Element link : downloadLinks) {
                String href = link.attr("href");
                if (href != null && (href.contains("download") || href.contains(".srt") || href.contains(".ass"))) {
                    debug.setMatchedSelector("a[href*='download']");
                    return href;
                }
            }

            Elements fallbackLinks = doc.select(".download");
            debug.addSelectorTried(".download");
            for (Element link : fallbackLinks) {
                String href = link.attr("href");
                if (href != null && !href.isEmpty()) {
                    debug.setMatchedSelector(".download");
                    return href;
                }
            }

        } catch (Exception e) {
            logger.error("解析下载链接时发生错误: {}", e.getMessage(), e);
            debug.addError("PARSE_ERROR: " + e.getMessage());
        }

        return null;
    }

    /**
     * 检查字幕标题是否匹配关键词
     */
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
        if (lowerTitle.contains(cleanedKeyword) || cleanedKeyword.contains(lowerTitle)) {
            return true;
        }

        return false;
    }

    /**
     * 解析数字字符串
     */
    private int parseNumber(String text) {
        if (text == null || text.trim().isEmpty()) {
            return 0;
        }

        Matcher matcher = downloadPattern.matcher(text.trim());
        if (matcher.find()) {
            try {
                return Integer.parseInt(matcher.group(1));
            } catch (NumberFormatException e) {
                logger.debug("解析数字失败: {}", text);
            }
        }

        return 0;
    }

    /**
     * 获取正确编码的响应体
     */
    private String getResponseBodyWithCorrectEncoding(Response response) throws IOException {
        ResponseBody body = response.body();
        if (body == null) {
            return "";
        }

        String contentType = response.header("Content-Type");
        Charset charset = StandardCharsets.UTF_8;

        if (contentType != null) {
            if (contentType.toLowerCase().contains("charset=")) {
                String[] parts = contentType.toLowerCase().split("charset=");
                if (parts.length > 1) {
                    String charsetName = parts[1].split(";")[0].trim();
                    try {
                        charset = Charset.forName(charsetName);
                        logger.debug("检测到字符编码: {}", charsetName);
                    } catch (Exception e) {
                        logger.debug("不支持的字符编码: {}, 使用UTF-8", charsetName);
                    }
                }
            }
        }

        byte[] bytes = body.bytes();
        String content = new String(bytes, charset);

        if (charset == StandardCharsets.UTF_8 && containsGarbledText(content)) {
            logger.debug("UTF-8解码可能有问题，尝试其他编码");

            try {
                String gbkContent = new String(bytes, Charset.forName("GBK"));
                if (!containsGarbledText(gbkContent)) {
                    logger.debug("使用GBK编码成功");
                    return gbkContent;
                }
            } catch (Exception e) {
                logger.debug("GBK编码失败");
            }

            try {
                String isoContent = new String(bytes, StandardCharsets.ISO_8859_1);
                if (!containsGarbledText(isoContent)) {
                    logger.debug("使用ISO-8859-1编码成功");
                    return isoContent;
                }
            } catch (Exception e) {
                logger.debug("ISO-8859-1编码失败");
            }
        }

        return content;
    }

    private boolean containsGarbledText(String text) {
        if (text == null || text.isEmpty()) {
            return false;
        }
        int garbledCount = 0;
        int totalCount = text.length();

        for (char c : text.toCharArray()) {
            if ((c >= 0xE000 && c <= 0xF8FF) || (c >= 0xFF00 && c <= 0xFFFF)) {
                garbledCount++;
            }
        }

        return garbledCount > totalCount * 0.3;
    }

    private static class UserAgentInterceptor implements Interceptor {
        @Override
        public Response intercept(Chain chain) throws IOException {
            Request originalRequest = chain.request();
            Request requestWithUserAgent = originalRequest.newBuilder()
                .header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36")
                .build();
            return chain.proceed(requestWithUserAgent);
        }
    }

    /**
     * 搜索调试信息
     */
    public static class SearchDebugResult {
        private final String keyword;
        private String searchUrl;
        private int httpStatus = -1;
        private final List<String> selectorsTried = new ArrayList<>();
        private String matchedSelector;
        private final List<String> errors = new ArrayList<>();
        private List<SubtitleInfo> subtitles = new ArrayList<>();
        private String responseBody;

        public SearchDebugResult(String keyword) {
            this.keyword = keyword;
        }

        public String getKeyword() {
            return keyword;
        }

        public void setSearchUrl(String searchUrl) {
            this.searchUrl = searchUrl;
        }

        public String getSearchUrl() {
            return searchUrl;
        }

        public void setHttpStatus(int httpStatus) {
            this.httpStatus = httpStatus;
        }

        public int getHttpStatus() {
            return httpStatus;
        }

        public void addSelectorTried(String selector) {
            if (!selectorsTried.contains(selector)) {
                selectorsTried.add(selector);
            }
        }

        public List<String> getSelectorsTried() {
            return Collections.unmodifiableList(selectorsTried);
        }

        public void setMatchedSelector(String matchedSelector) {
            this.matchedSelector = matchedSelector;
        }

        public String getMatchedSelector() {
            return matchedSelector;
        }

        public void addError(String error) {
            if (error != null && !error.isEmpty()) {
                errors.add(error);
            }
        }

        public List<String> getErrors() {
            return Collections.unmodifiableList(errors);
        }

        public void setSubtitles(List<SubtitleInfo> subtitles) {
            this.subtitles = subtitles != null ? subtitles : new ArrayList<>();
        }

        public List<SubtitleInfo> getSubtitles() {
            return Collections.unmodifiableList(subtitles);
        }

        public void setResponseBody(String responseBody) {
            this.responseBody = responseBody;
        }

        public String getResponseBody() {
            return responseBody;
        }
    }

    /**
     * 下载调试信息
     */
    public static class DownloadDebugResult {
        private final SubtitleInfo subtitleInfo;
        private String detailUrl;
        private int httpStatus = -1;
        private final List<String> selectorsTried = new ArrayList<>();
        private String matchedSelector;
        private final List<String> errors = new ArrayList<>();
        private String responseBody;
        private String resolvedDownloadUrl;

        public DownloadDebugResult(SubtitleInfo subtitleInfo) {
            this.subtitleInfo = subtitleInfo;
        }

        public SubtitleInfo getSubtitleInfo() {
            return subtitleInfo;
        }

        public void setDetailUrl(String detailUrl) {
            this.detailUrl = detailUrl;
        }

        public String getDetailUrl() {
            return detailUrl;
        }

        public void setHttpStatus(int httpStatus) {
            this.httpStatus = httpStatus;
        }

        public int getHttpStatus() {
            return httpStatus;
        }

        public void addSelectorTried(String selector) {
            if (!selectorsTried.contains(selector)) {
                selectorsTried.add(selector);
            }
        }

        public List<String> getSelectorsTried() {
            return Collections.unmodifiableList(selectorsTried);
        }

        public void setMatchedSelector(String matchedSelector) {
            this.matchedSelector = matchedSelector;
        }

        public String getMatchedSelector() {
            return matchedSelector;
        }

        public void addError(String error) {
            if (error != null && !error.isEmpty()) {
                errors.add(error);
            }
        }

        public List<String> getErrors() {
            return Collections.unmodifiableList(errors);
        }

        public void setResponseBody(String responseBody) {
            this.responseBody = responseBody;
        }

        public String getResponseBody() {
            return responseBody;
        }

        public void setResolvedDownloadUrl(String resolvedDownloadUrl) {
            this.resolvedDownloadUrl = resolvedDownloadUrl;
        }

        public String getResolvedDownloadUrl() {
            return resolvedDownloadUrl;
        }
    }
}
