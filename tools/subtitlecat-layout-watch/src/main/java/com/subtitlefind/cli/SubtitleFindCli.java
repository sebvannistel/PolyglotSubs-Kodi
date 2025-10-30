package com.subtitlefind.cli;

import com.subtitlefind.model.SubtitleInfo;
import com.subtitlefind.service.SubtitleCrawlerService;
import com.subtitlefind.service.SubtitleCrawlerService.SearchDiagnostics;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Lightweight CLI to exercise the subtitle-find crawler without the interactive shell.
 */
public final class SubtitleFindCli {

    private static final Logger logger = LoggerFactory.getLogger(SubtitleFindCli.class);

    private SubtitleFindCli() {
    }

    public static void main(String[] args) {
        Map<String, String> options = new HashMap<>();
        List<String> queries = new ArrayList<>();

        for (int i = 0; i < args.length; i++) {
            String arg = args[i];
            if ("--help".equals(arg) || "-h".equals(arg)) {
                printUsage();
                return;
            }
            if ("--snapshot-dir".equals(arg)) {
                if (i + 1 >= args.length) {
                    System.err.println("Missing value for --snapshot-dir");
                    System.exit(64);
                }
                options.put("snapshotDir", args[++i]);
            } else {
                queries.add(arg);
            }
        }

        if (queries.isEmpty()) {
            printUsage();
            System.exit(64);
        }

        File snapshotDir = null;
        if (options.containsKey("snapshotDir")) {
            snapshotDir = new File(options.get("snapshotDir"));
            if (!snapshotDir.exists() && !snapshotDir.mkdirs()) {
                System.err.println("Unable to create snapshot directory: " + snapshotDir);
                System.exit(1);
            }
        }

        SubtitleCrawlerService crawlerService = new SubtitleCrawlerService();
        List<QueryReport> reports = new ArrayList<>();

        for (String query : queries) {
            Instant start = Instant.now();
            List<SubtitleInfo> results = crawlerService.searchSubtitles(query);
            SearchDiagnostics diagnostics = crawlerService.getLastSearchDiagnostics();
            String snapshotPath = null;
            if (snapshotDir != null) {
                snapshotPath = writeSnapshot(snapshotDir, query, crawlerService.getLastResponseBody());
            }
            Duration duration = Duration.between(start, Instant.now());
            reports.add(new QueryReport(query, diagnostics, results, snapshotPath, duration.toMillis()));
        }

        crawlerService.close();
        System.out.println(toJson(reports));
    }

    private static void printUsage() {
        System.err.println("Usage: java -jar subtitlecat-layout-watch.jar [--snapshot-dir <dir>] <query> [<query>...]");
    }

    private static String writeSnapshot(File directory, String keyword, String responseBody) {
        if (responseBody == null || responseBody.isEmpty()) {
            return null;
        }
        String slug = slugify(keyword);
        File target = new File(directory, slug + ".html");
        try (PrintWriter writer = new PrintWriter(new OutputStreamWriter(new FileOutputStream(target), StandardCharsets.UTF_8))) {
            writer.write(responseBody);
            logger.debug("Wrote snapshot for '{}' to {}", keyword, target.getAbsolutePath());
            return target.getAbsolutePath();
        } catch (IOException e) {
            logger.warn("Unable to write snapshot for '{}': {}", keyword, e.getMessage());
            return null;
        }
    }

    private static String slugify(String value) {
        String lower = value.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", "-").replaceAll("-+", "-");
        lower = lower.replaceAll("^-|-$", "");
        return lower.isEmpty() ? "query" : lower;
    }

    private static String toJson(List<QueryReport> reports) {
        StringBuilder builder = new StringBuilder();
        builder.append('{').append("\"queries\":");
        builder.append('[');
        for (int i = 0; i < reports.size(); i++) {
            QueryReport report = reports.get(i);
            if (i > 0) {
                builder.append(',');
            }
            builder.append(report.toJson());
        }
        builder.append(']');
        builder.append('}');
        return builder.toString();
    }

    private static final class QueryReport {
        private final String keyword;
        private final SearchDiagnostics diagnostics;
        private final List<SubtitleInfo> results;
        private final String snapshotPath;
        private final long durationMillis;

        private QueryReport(String keyword, SearchDiagnostics diagnostics, List<SubtitleInfo> results,
                            String snapshotPath, long durationMillis) {
            this.keyword = keyword;
            this.diagnostics = diagnostics;
            this.results = results;
            this.snapshotPath = snapshotPath;
            this.durationMillis = durationMillis;
        }

        private String toJson() {
            StringBuilder builder = new StringBuilder();
            builder.append('{');
            builder.append("\"keyword\":").append(jsonString(keyword)).append(',');
            builder.append("\"http_status\":").append(diagnostics.getStatusCode()).append(',');
            builder.append("\"request_successful\":").append(diagnostics.isRequestSuccessful()).append(',');
            builder.append("\"row_count\":").append(diagnostics.getRowCount()).append(',');
            builder.append("\"matched_selector\":").append(jsonStringOrNull(diagnostics.getMatchedSelector())).append(',');
            builder.append("\"failure_reason\":").append(jsonStringOrNull(diagnostics.getFailureReason())).append(',');
            builder.append("\"attempted_selectors\":").append(jsonStringArray(diagnostics.getAttemptedSelectors())).append(',');
            builder.append("\"response_snippet\":").append(jsonString(diagnostics.getResponseSnippet())).append(',');
            builder.append("\"snapshot_path\":").append(jsonStringOrNull(snapshotPath)).append(',');
            builder.append("\"duration_ms\":").append(durationMillis).append(',');
            builder.append("\"results\":");
            builder.append('[');
            for (int i = 0; i < results.size(); i++) {
                SubtitleInfo info = results.get(i);
                if (i > 0) {
                    builder.append(',');
                }
                builder.append('{')
                    .append("\"title\":").append(jsonString(info.getTitle())).append(',')
                    .append("\"href\":").append(jsonStringOrNull(info.getHref())).append(',')
                    .append("\"downloads\":").append(info.getDownloads()).append(',')
                    .append("\"comments\":").append(info.getComments()).append(',')
                    .append("\"language\":").append(jsonStringOrNull(info.getLanguage()))
                    .append('}');
            }
            builder.append(']');
            builder.append('}');
            return builder.toString();
        }

        private static String jsonString(String value) {
            if (value == null) {
                return "\"\"";
            }
            return '"' + escape(value) + '"';
        }

        private static String jsonStringOrNull(String value) {
            if (value == null || value.isEmpty()) {
                return "null";
            }
            return jsonString(value);
        }

        private static String jsonStringArray(List<String> values) {
            StringBuilder builder = new StringBuilder();
            builder.append('[');
            for (int i = 0; i < values.size(); i++) {
                if (i > 0) {
                    builder.append(',');
                }
                builder.append(jsonString(values.get(i)));
            }
            builder.append(']');
            return builder.toString();
        }

        private static String escape(String value) {
            StringBuilder builder = new StringBuilder();
            for (char ch : value.toCharArray()) {
                switch (ch) {
                    case '\"':
                        builder.append("\\\"");
                        break;
                    case '\\':
                        builder.append("\\\\");
                        break;
                    case '\n':
                        builder.append("\\n");
                        break;
                    case '\r':
                        builder.append("\\r");
                        break;
                    case '\t':
                        builder.append("\\t");
                        break;
                    default:
                        if (ch < 0x20 || ch == 0x2028 || ch == 0x2029) {
                            builder.append(String.format("\\u%04x", (int) ch));
                        } else {
                            builder.append(ch);
                        }
                        break;
                }
            }
            return builder.toString();
        }
    }
}
