/**
 * Network guard: blocks requests to private, loopback, link-local and cloud
 * metadata addresses unless the host is explicitly allow-listed through
 * LLX_ALLOWED_HOSTS (comma separated). Mirrors backend/app/security/ssrf.py.
 */
import * as dns from 'node:dns/promises';
import * as net from 'node:net';

const BLOCKED_HOSTNAMES = new Set(['metadata.google.internal', 'metadata', 'instance-data']);

function ipv4ToInt(ip: string): number {
  return ip.split('.').reduce((acc, part) => (acc << 8) + Number(part), 0) >>> 0;
}

const V4_BLOCKS: Array<[string, number]> = [
  ['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10], ['127.0.0.0', 8], ['169.254.0.0', 16],
  ['172.16.0.0', 12], ['192.0.0.0', 24], ['192.168.0.0', 16], ['198.18.0.0', 15], ['224.0.0.0', 4], ['240.0.0.0', 4],
];

export function isBlockedIp(ip: string): boolean {
  if (net.isIPv4(ip)) {
    const value = ipv4ToInt(ip);
    return V4_BLOCKS.some(([base, bits]) => {
      const mask = bits === 0 ? 0 : (~0 << (32 - bits)) >>> 0;
      return (value & mask) === (ipv4ToInt(base) & mask);
    });
  }
  if (net.isIPv6(ip)) {
    const lower = ip.toLowerCase();
    if (lower === '::1' || lower === '::') return true;
    const mapped = lower.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/);
    if (mapped) return isBlockedIp(mapped[1]);
    return /^(fc|fd|fe8|fe9|fea|feb|ff)/.test(lower);
  }
  return true;
}

export function allowedHosts(): Set<string> {
  return new Set(
    (process.env.LLX_ALLOWED_HOSTS || '')
      .split(',')
      .map((h) => h.trim().toLowerCase())
      .filter(Boolean),
  );
}

const cache = new Map<string, Promise<string | null>>();

/** Returns null when the URL may be requested, otherwise the reason it is blocked. */
export function checkUrl(rawUrl: string): Promise<string | null> {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    return Promise.resolve(`invalid URL: ${rawUrl}`);
  }
  if (['data:', 'blob:', 'about:'].includes(url.protocol)) return Promise.resolve(null);
  if (!['http:', 'https:', 'ws:', 'wss:'].includes(url.protocol)) {
    return Promise.resolve(`scheme ${url.protocol} is not allowed`);
  }
  const host = url.hostname.replace(/^\[|\]$/g, '').toLowerCase();
  if (allowedHosts().has(host)) return Promise.resolve(null);
  if (BLOCKED_HOSTNAMES.has(host)) return Promise.resolve(`host ${host} is blocked`);
  if (!cache.has(host)) {
    cache.set(
      host,
      (async () => {
        if (net.isIP(host)) return isBlockedIp(host) ? `address ${host} is in a restricted range` : null;
        try {
          const records = await dns.lookup(host, { all: true });
          const bad = records.find((r) => isBlockedIp(r.address));
          return bad ? `host ${host} resolves to restricted address ${bad.address}` : null;
        } catch {
          return `host ${host} could not be resolved`;
        }
      })(),
    );
  }
  return cache.get(host)!;
}
