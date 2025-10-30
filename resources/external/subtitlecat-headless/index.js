#!/usr/bin/env node
const https = require('https');
const { URL } = require('url');

const SC_BASE_URL = 'https://www.subtitlecat.com';
const SC_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 a4kSubtitles-SubtitlecatMod/1.0.1';
const DEFAULT_TIMEOUT = 30000;

function fetchText(targetUrl, { timeout = DEFAULT_TIMEOUT } = {}) {
  const urlObj = new URL(targetUrl.startsWith('http') ? targetUrl : SC_BASE_URL + targetUrl);
  return new Promise((resolve, reject) => {
    const request = https.request(
      {
        hostname: urlObj.hostname,
        path: urlObj.pathname + (urlObj.search || ''),
        protocol: urlObj.protocol,
        headers: {
          'User-Agent': SC_USER_AGENT,
          'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
          'Accept-Language': 'en-US,en;q=0.9',
          'Cache-Control': 'no-cache',
        },
        timeout,
      },
      (res) => {
        if (res.statusCode && res.statusCode >= 400) {
          reject(new Error(`HTTP ${res.statusCode} for ${urlObj.href}`));
          res.resume();
          return;
        }
        const chunks = [];
        res.on('data', (chunk) => chunks.push(chunk));
        res.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
      }
    );
    request.on('error', (err) => reject(err));
    request.on('timeout', () => {
      request.destroy(new Error(`Timeout fetching ${urlObj.href}`));
    });
    request.end();
  });
}

function fetchBuffer(targetUrl, { timeout = DEFAULT_TIMEOUT } = {}) {
  const urlObj = new URL(targetUrl.startsWith('http') ? targetUrl : SC_BASE_URL + targetUrl);
  return new Promise((resolve, reject) => {
    const request = https.request(
      {
        hostname: urlObj.hostname,
        path: urlObj.pathname + (urlObj.search || ''),
        protocol: urlObj.protocol,
        headers: {
          'User-Agent': SC_USER_AGENT,
          'Accept': 'application/octet-stream,application/x-subrip,*/*',
          'Accept-Language': 'en-US,en;q=0.9',
          'Cache-Control': 'no-cache',
        },
        timeout,
      },
      (res) => {
        if (res.statusCode && res.statusCode >= 400) {
          reject(new Error(`HTTP ${res.statusCode} for ${urlObj.href}`));
          res.resume();
          return;
        }
        const chunks = [];
        res.on('data', (chunk) => chunks.push(chunk));
        res.on('end', () => resolve(Buffer.concat(chunks)));
      }
    );
    request.on('error', (err) => reject(err));
    request.on('timeout', () => {
      request.destroy(new Error(`Timeout fetching ${urlObj.href}`));
    });
    request.end();
  });
}

function stripTags(html) {
  return html.replace(/<[^>]*>/g, ' ');
}

function decodeHtml(html) {
  if (!html) {
    return '';
  }
  return html
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&#x2F;/g, '/');
}

function absoluteUrl(href) {
  if (!href) {
    return '';
  }
  if (/^https?:/i.test(href)) {
    return href;
  }
  if (!href.startsWith('/')) {
    href = '/' + href;
  }
  return SC_BASE_URL + href;
}

function parseSearchRows(html) {
  const tableMatch = html.match(/<table class="table sub-table">([\s\S]*?)<\/table>/i);
  if (!tableMatch) {
    return [];
  }
  const tbodyMatch = tableMatch[1].match(/<tbody>([\s\S]*?)<\/tbody>/i);
  const tbody = tbodyMatch ? tbodyMatch[1] : tableMatch[1];
  const rows = [];
  const rowRegex = /<tr>([\s\S]*?)<\/tr>/gi;
  let rowMatch;
  while ((rowMatch = rowRegex.exec(tbody)) !== null) {
    const rowHtml = rowMatch[1];
    const linkMatch = rowHtml.match(/<td>\s*<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>\s*(?:\(([^)]*)\))?/i);
    if (!linkMatch) {
      continue;
    }
    const href = linkMatch[1];
    const title = decodeHtml(stripTags(linkMatch[2])).trim();
    const translatedFrom = decodeHtml((linkMatch[3] || '').trim());
    rows.push({
      href,
      title,
      translatedFrom,
      detailUrl: absoluteUrl(href),
    });
  }
  return rows;
}

function parseLanguageBlocks(detailHtml) {
  const blocks = [];
  const blockRegex = /<div class="sub-single">([\s\S]*?)<\/div>/gi;
  let match;
  while ((match = blockRegex.exec(detailHtml)) !== null) {
    const block = match[1];
    const codeMatch = block.match(/<img[^>]+alt="([^"]+)"/i);
    if (!codeMatch) {
      continue;
    }
    const langCode = codeMatch[1];
    const nameMatch = block.match(/<span>([^<]+)<\/span>\s*<span><a|<span>([^<]+)<\/span>\s*<span><button/i);
    let langName = langCode;
    if (nameMatch) {
      const first = nameMatch[1] || nameMatch[2];
      if (first) {
        langName = decodeHtml(first.trim());
      }
    } else {
      const plainNameMatch = block.match(/<span>([^<]+)<\/span>/i);
      if (plainNameMatch) {
        langName = decodeHtml(plainNameMatch[1].trim());
      }
    }
    const downloadMatch = block.match(/<a[^>]+id="download_[^"]*"[^>]*href="([^"]+)"/i);
    const translateMatch = block.match(/translate_from_server_folder\('([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\)/i);
    blocks.push({
      code: langCode,
      name: langName,
      downloadHref: downloadMatch ? downloadMatch[1] : '',
      translateArgs: translateMatch
        ? {
            target: translateMatch[1],
            sourceFile: translateMatch[2],
            folder: translateMatch[3],
          }
        : null,
    });
  }
  return blocks;
}

async function runSearch(query) {
  const searchUrl = `${SC_BASE_URL}/index.php?search=${encodeURIComponent(query)}&d=1`;
  const html = await fetchText(searchUrl);
  if (/cloudflare/i.test(html) && /Just a moment/i.test(html)) {
    throw new Error('Cloudflare challenge detected while fetching search results');
  }
  const rows = parseSearchRows(html);
  const items = [];
  for (const row of rows) {
    try {
      const detailHtml = await fetchText(row.detailUrl);
      const languages = parseLanguageBlocks(detailHtml);
      items.push({
        title: row.title,
        href: row.href,
        detailUrl: row.detailUrl,
        translatedFrom: row.translatedFrom,
        languages,
      });
    } catch (err) {
      items.push({
        title: row.title,
        href: row.href,
        detailUrl: row.detailUrl,
        translatedFrom: row.translatedFrom,
        languages: [],
        warning: err.message,
      });
    }
  }
  return {
    ok: true,
    items,
  };
}

async function runDownload(item, lang) {
  const detailUrl = absoluteUrl(item);
  const detailHtml = await fetchText(detailUrl);
  const languages = parseLanguageBlocks(detailHtml);
  const matched = languages.find((entry) => entry.code.toLowerCase() === lang.toLowerCase());
  if (!matched) {
    throw new Error(`Language ${lang} not available for ${detailUrl}`);
  }
  if (!matched.downloadHref) {
    throw new Error(`Language ${lang} does not expose a direct download link`);
  }
  const downloadUrl = absoluteUrl(matched.downloadHref);
  const buffer = await fetchBuffer(downloadUrl);
  return {
    ok: true,
    filename: downloadUrl.split('/').pop() || 'subtitle.srt',
    data: buffer.toString('base64'),
  };
}

async function main() {
  const [, , command, ...rest] = process.argv;
  if (!command || !['search', 'download'].includes(command)) {
    console.error(
      JSON.stringify({
        ok: false,
        error: 'Unknown or missing command. Expected "search" or "download".',
      })
    );
    process.exit(1);
  }
  try {
    if (command === 'search') {
      const query = rest.join(' ').trim();
      if (!query) {
        throw new Error('Search query is required.');
      }
      const result = await runSearch(query);
      process.stdout.write(JSON.stringify(result));
    } else if (command === 'download') {
      if (rest.length < 2) {
        throw new Error('Download command expects <item> <lang>.');
      }
      const [item, lang] = rest;
      const result = await runDownload(item, lang);
      process.stdout.write(JSON.stringify(result));
    }
  } catch (err) {
    process.stdout.write(
      JSON.stringify({
        ok: false,
        error: err && err.message ? err.message : String(err),
      })
    );
    process.exitCode = 1;
  }
}

main();
