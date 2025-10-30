package com.subtitlefind.model;

/**
 * Minimal data container describing a subtitle search result.
 */
public class SubtitleInfo {
    private String title;
    private String downloadUrl;
    private String href;
    private int downloads;
    private int comments;
    private String language;

    public SubtitleInfo() {
    }

    public SubtitleInfo(String title, String href, String downloadUrl, int downloads, int comments, String language) {
        this.title = title;
        this.href = href;
        this.downloadUrl = downloadUrl;
        this.downloads = downloads;
        this.comments = comments;
        this.language = language;
    }

    public String getTitle() {
        return title;
    }

    public void setTitle(String title) {
        this.title = title;
    }

    public String getDownloadUrl() {
        return downloadUrl;
    }

    public void setDownloadUrl(String downloadUrl) {
        this.downloadUrl = downloadUrl;
    }

    public String getHref() {
        return href;
    }

    public void setHref(String href) {
        this.href = href;
    }

    public int getDownloads() {
        return downloads;
    }

    public void setDownloads(int downloads) {
        this.downloads = downloads;
    }

    public int getComments() {
        return comments;
    }

    public void setComments(int comments) {
        this.comments = comments;
    }

    public String getLanguage() {
        return language;
    }

    public void setLanguage(String language) {
        this.language = language;
    }

    @Override
    public String toString() {
        return "SubtitleInfo{" +
            "title='" + title + '\'' +
            ", downloads=" + downloads +
            ", comments=" + comments +
            ", language='" + language + '\'' +
            '}';
    }
}
