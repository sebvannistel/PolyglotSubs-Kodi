package com.subtitlefind.service;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 * Utility routines copied from subtitle-find to normalise video titles.
 */
public class VideoFileScanner {

    // Supported video file extensions
    private static final List<String> VIDEO_EXTENSIONS = Arrays.asList(
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".3gp", ".ts"
    );

    private static final Pattern QUALITY_SUFFIX_PATTERN = Pattern.compile(
        "(-(?:4k|4K|BD|bd|1080p|720p|2160p|HDR|UHD|REMUX|BluRay|WEB-DL|WEBRip|BDRip))$",
        Pattern.CASE_INSENSITIVE
    );

    private VideoFileScanner() {
    }

    public static String getCleanedFileNameForSearch(String fileName) {
        if (fileName == null || fileName.trim().isEmpty()) {
            return fileName;
        }
        return QUALITY_SUFFIX_PATTERN.matcher(fileName.trim()).replaceAll("");
    }

    // Remaining helpers kept for parity with the upstream project.
    public static List<VideoFileInfo> scanVideoFiles(String directoryPath) {
        List<VideoFileInfo> videoFiles = new ArrayList<>();
        Path rootPath = Paths.get(directoryPath);

        if (!Files.exists(rootPath) || !Files.isDirectory(rootPath)) {
            return videoFiles;
        }

        try (Stream<Path> pathStream = Files.walk(rootPath)) {
            pathStream
                .filter(Files::isRegularFile)
                .filter(VideoFileScanner::isVideoFile)
                .forEach(path -> {
                    VideoFileInfo videoInfo = createVideoFileInfo(path);
                    if (videoInfo != null) {
                        videoFiles.add(videoInfo);
                    }
                });
        } catch (IOException ignored) {
            // The CLI never uses the file scanning branch, but we keep behaviour consistent.
        }

        return videoFiles;
    }

    private static boolean isVideoFile(Path path) {
        String fileName = path.getFileName().toString().toLowerCase();
        return VIDEO_EXTENSIONS.stream().anyMatch(fileName::endsWith);
    }

    private static VideoFileInfo createVideoFileInfo(Path path) {
        try {
            String fullPath = path.toString();
            String fileName = path.getFileName().toString();
            String fileNameWithoutExtension = getFileNameWithoutExtension(fileName);
            String directory = path.getParent().toString();
            long fileSize = Files.size(path);
            return new VideoFileInfo(fullPath, fileName, fileNameWithoutExtension, directory, fileSize);
        } catch (IOException e) {
            return null;
        }
    }

    private static String getFileNameWithoutExtension(String fileName) {
        int lastDotIndex = fileName.lastIndexOf('.');
        if (lastDotIndex > 0) {
            return fileName.substring(0, lastDotIndex);
        }
        return fileName;
    }

    public static class VideoFileInfo {
        private final String fullPath;
        private final String fileName;
        private final String fileNameWithoutExtension;
        private final String directory;
        private final long fileSize;

        public VideoFileInfo(String fullPath, String fileName, String fileNameWithoutExtension,
                             String directory, long fileSize) {
            this.fullPath = fullPath;
            this.fileName = fileName;
            this.fileNameWithoutExtension = fileNameWithoutExtension;
            this.directory = directory;
            this.fileSize = fileSize;
        }

        public String getFullPath() { return fullPath; }
        public String getFileName() { return fileName; }
        public String getFileNameWithoutExtension() { return fileNameWithoutExtension; }
        public String getDirectory() { return directory; }
        public long getFileSize() { return fileSize; }

        @Override
        public String toString() {
            return "VideoFileInfo{" +
                "fileName='" + fileName + '\'' +
                ", directory='" + directory + '\'' +
                ", fileSize=" + fileSize +
                '}';
        }
    }
}
