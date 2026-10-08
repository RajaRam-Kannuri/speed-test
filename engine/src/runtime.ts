/**
 * LorvenLax test runtime. Generated specs only call into this module with
 * JSON-literal arguments, so test content coming from AI or users is data,
 * never code.
 */
import { test as base, expect, type Locator, type Page, type APIRequestContext, type TestInfo } from '@playwright/test';
import Ajv from 'ajv';
import addFormats from 'ajv-formats';
import { checkUrl } from './guard';

export { expect };

export type Target = {
  strategy: 'role' | 'label' | 'text' | 'placeholder' | 'testid' | 'css' | 'title' | 'alt';
  value: string;
  name?: string;
  exact?: boolean;
  nth?: number;
};

export type ApiSpec = {
  method: string;
  url: string;
  headers?: Record<string, string>;
  query?: Record<string, string | number | boolean>;
  body?: unknown;
  raw_body?: string;
  expect?: {
    status?: number[];
    status_range?: [number, number];
    schema?: Record<string, unknown>;
    json?: Array<{ path: string; equals?: unknown; exists?: boolean }>;
    max_ms?: number;
    header_contains?: Record<string, string>;
  };
  store?: Record<string, string>;
};

const ajv = new Ajv({ allErrors: true, strict: false });
addFormats(ajv);

function readVars(): Record<string, string> {
  try {
    return JSON.parse(process.env.LLX_VARS || '{}');
  } catch {
    return {};
  }
}

function jsonPath(data: unknown, path: string): unknown {
  // Supports "$.a.b[0].c" and "a.b.0.c".
  const parts = path.replace(/^\$\.?/, '').replace(/\[(\d+)\]/g, '.$1').split('.').filter(Boolean);
  let cur: any = data;
  for (const p of parts) {
    if (cur === null || cur === undefined) return undefined;
    cur = cur[p];
  }
  return cur;
}

export class Llx {
  vars: Record<string, string>;
  private baseUrl: string;
  lastTarget: Target | null = null;
  lastAction = '';

  private _page: Page | null;

  constructor(page: Page | null, private request: APIRequestContext, private info: TestInfo) {
    this._page = page;
    this.vars = readVars();
    this.baseUrl = process.env.LLX_BASE_URL || '';
  }

  private get page(): Page {
    if (!this._page) throw new Error('This step needs a browser, but the test only has API steps');
    return this._page;
  }

  /** Resolve {{name}} placeholders from variables. */
  v(template: string): string {
    return String(template).replace(/\{\{\s*([\w.-]+)\s*\}\}/g, (_m, name) => {
      if (name === 'timestamp') return String(Date.now());
      if (name === 'random') return Math.random().toString(36).slice(2, 10);
      if (!(name in this.vars)) throw new Error(`Variable "${name}" is not defined in the environment`);
      return this.vars[name];
    });
  }

  url(path: string): string {
    const resolved = this.v(path);
    if (/^https?:\/\//i.test(resolved)) return resolved;
    if (!this.baseUrl) throw new Error(`Relative URL "${resolved}" needs a base URL`);
    return new URL(resolved, this.baseUrl).toString();
  }

  locate(t: Target): Locator {
    this.lastTarget = t;
    const exact = t.exact ?? false;
    let loc: Locator;
    switch (t.strategy) {
      case 'role':
        loc = this.page.getByRole(t.value as any, t.name ? { name: t.name, exact } : undefined);
        break;
      case 'label': loc = this.page.getByLabel(t.value, { exact }); break;
      case 'text': loc = this.page.getByText(t.value, { exact }); break;
      case 'placeholder': loc = this.page.getByPlaceholder(t.value, { exact }); break;
      case 'testid': loc = this.page.getByTestId(t.value); break;
      case 'title': loc = this.page.getByTitle(t.value, { exact }); break;
      case 'alt': loc = this.page.getByAltText(t.value, { exact }); break;
      case 'css': loc = this.page.locator(t.value); break;
      default: throw new Error(`Unknown locator strategy ${(t as Target).strategy}`);
    }
    return t.nth !== undefined ? loc.nth(t.nth) : loc.first();
  }

  async navigate(path: string) {
    this.lastAction = 'navigate';
    this.lastTarget = null;
    const target = this.url(path);
    const blocked = await checkUrl(target);
    if (blocked) throw new Error(`Navigation blocked by network policy: ${blocked}`);
    const response = await this.page.goto(target, { waitUntil: 'domcontentloaded' });
    if (response && response.status() >= 400) {
      throw new Error(`Navigation to ${target} returned HTTP ${response.status()}`);
    }
  }

  async click(t: Target) { this.lastAction = 'click'; await this.locate(t).click(); }
  async fill(t: Target, value: string) { this.lastAction = 'fill'; await this.locate(t).fill(this.v(value)); }
  async select(t: Target, value: string) { this.lastAction = 'select'; await this.locate(t).selectOption({ label: this.v(value) }).catch(async () => this.locate(t).selectOption(this.v(value))); }
  async check(t: Target) { this.lastAction = 'check'; await this.locate(t).check(); }
  async uncheck(t: Target) { this.lastAction = 'uncheck'; await this.locate(t).uncheck(); }
  async press(t: Target | null, key: string) {
    this.lastAction = 'press';
    if (t) await this.locate(t).press(key); else await this.page.keyboard.press(key);
  }
  async waitFor(t: Target, state: 'visible' | 'hidden' = 'visible') { this.lastAction = 'wait_for'; await this.locate(t).waitFor({ state }); }
  async waitMs(ms: number) { await this.page.waitForTimeout(Math.min(ms, 30_000)); }

  async expectVisible(t: Target) { this.lastAction = 'assert_visible'; await expect(this.locate(t)).toBeVisible(); }
  async expectHidden(t: Target) { this.lastAction = 'assert_hidden'; await expect(this.locate(t)).toBeHidden(); }
  async expectText(t: Target | null, text: string) {
    this.lastAction = 'assert_text';
    if (t) await expect(this.locate(t)).toContainText(this.v(text));
    else await expect(this.page.locator('body')).toContainText(this.v(text));
  }
  async expectNoText(text: string) {
    this.lastAction = 'assert_no_text';
    await expect(this.page.locator('body')).not.toContainText(this.v(text));
  }
  async expectValue(t: Target, value: string) { this.lastAction = 'assert_value'; await expect(this.locate(t)).toHaveValue(this.v(value)); }
  async expectCount(t: Target, count: number) {
    this.lastAction = 'assert_count';
    this.lastTarget = t;
    // locate() narrows to .first(); count the full match set instead.
    await expect(this.allMatches(t)).toHaveCount(count);
  }
  private allMatches(t: Target): Locator {
    const exact = t.exact ?? false;
    switch (t.strategy) {
      case 'role': return this.page.getByRole(t.value as any, t.name ? { name: t.name, exact } : undefined);
      case 'label': return this.page.getByLabel(t.value, { exact });
      case 'text': return this.page.getByText(t.value, { exact });
      case 'placeholder': return this.page.getByPlaceholder(t.value, { exact });
      case 'testid': return this.page.getByTestId(t.value);
      case 'title': return this.page.getByTitle(t.value, { exact });
      case 'alt': return this.page.getByAltText(t.value, { exact });
      default: return this.page.locator(t.value);
    }
  }
  async expectUrl(fragment: string) {
    this.lastAction = 'assert_url';
    const want = this.v(fragment);
    await expect(this.page).toHaveURL(new RegExp(want.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  async expectUrlNot(fragment: string) {
    this.lastAction = 'assert_url_not';
    const want = this.v(fragment);
    await expect(this.page).not.toHaveURL(new RegExp(want.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  async expectTitle(text: string) {
    this.lastAction = 'assert_title';
    const want = this.v(text);
    await expect(this.page).toHaveTitle(new RegExp(want.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'));
  }

  async storeText(t: Target, name: string) { this.vars[name] = (await this.locate(t).innerText()).trim(); }
  setVar(name: string, value: string) { this.vars[name] = this.v(value); }

  async screenshot(name: string) {
    const body = await this.page.screenshot({ fullPage: true });
    await this.info.attach(name || 'screenshot', { body, contentType: 'image/png' });
  }

  async api(spec: ApiSpec) {
    this.lastAction = 'api_request';
    this.lastTarget = null;
    const url = this.url(spec.url);
    const blocked = await checkUrl(url);
    if (blocked) throw new Error(`Request blocked by network policy: ${blocked}`);
    const headers: Record<string, string> = {};
    for (const [k, val] of Object.entries(spec.headers || {})) headers[k] = this.v(val);
    const params: Record<string, string> = {};
    for (const [k, val] of Object.entries(spec.query || {})) params[k] = this.v(String(val));
    const resolveBody = (b: unknown): unknown => {
      if (typeof b === 'string') return this.v(b);
      if (Array.isArray(b)) return b.map(resolveBody);
      if (b && typeof b === 'object') return Object.fromEntries(Object.entries(b).map(([k, x]) => [k, resolveBody(x)]));
      return b;
    };
    const started = Date.now();
    const options: Parameters<APIRequestContext['fetch']>[1] = { method: spec.method.toUpperCase(), headers, params, failOnStatusCode: false };
    if (spec.raw_body !== undefined) {
      options.data = this.v(spec.raw_body);
      headers['content-type'] = headers['content-type'] || 'application/json';
    } else if (spec.body !== undefined) {
      options.data = resolveBody(spec.body) as any;
    }
    const response = await this.request.fetch(url, options);
    const elapsed = Date.now() - started;
    const text = await response.text();
    let json: unknown = undefined;
    try { json = text ? JSON.parse(text) : undefined; } catch { /* not JSON */ }

    await this.info.attach(`api ${spec.method.toUpperCase()} ${spec.url}`, {
      contentType: 'application/json',
      body: JSON.stringify({
        request: { method: spec.method.toUpperCase(), url, query: params, body: options.data ?? null },
        response: { status: response.status(), elapsed_ms: elapsed, headers: response.headers(), body: text.slice(0, 4000) },
      }, null, 2),
    });

    const e = spec.expect || {};
    if (e.status && e.status.length) {
      expect(e.status, `HTTP status ${response.status()} for ${spec.method.toUpperCase()} ${spec.url}; body: ${text.slice(0, 300)}`).toContain(response.status());
    }
    if (e.status_range) {
      const [lo, hi] = e.status_range;
      expect(response.status() >= lo && response.status() <= hi,
        `HTTP status ${response.status()} outside expected range ${lo}-${hi}; body: ${text.slice(0, 300)}`).toBe(true);
    }
    if (e.max_ms) expect(elapsed, `response time ${elapsed}ms exceeds ${e.max_ms}ms`).toBeLessThanOrEqual(e.max_ms);
    if (e.header_contains) {
      for (const [h, want] of Object.entries(e.header_contains)) {
        expect(response.headers()[h.toLowerCase()] || '', `header ${h}`).toContain(want);
      }
    }
    if (e.schema) {
      expect(json, 'response body is not JSON but a schema was expected').not.toBeUndefined();
      const validate = ajv.compile(e.schema);
      const ok = validate(json);
      expect(ok, `response does not match schema: ${ajv.errorsText(validate.errors)}`).toBe(true);
    }
    for (const check of e.json || []) {
      const value = jsonPath(json, check.path);
      if (check.exists !== undefined) expect(value !== undefined, `JSON path ${check.path} exists`).toBe(check.exists);
      if ('equals' in check) expect(value, `JSON path ${check.path}`).toEqual(resolveBody(check.equals));
    }
    for (const [name, path] of Object.entries(spec.store || {})) {
      const value = jsonPath(json, path);
      if (value === undefined) throw new Error(`Cannot store "${name}": JSON path ${path} not found in response`);
      this.vars[name] = String(value);
    }
    return { status: response.status(), json };
  }
}

type Fixtures = { llx: Llx; llxApi: Llx };

export const test = base.extend<Fixtures>({
  // API-only tests: no browser page is created.
  llxApi: async ({ request }, use, testInfo) => {
    await use(new Llx(null, request, testInfo));
  },
  // Every browser request passes the network guard.
  context: async ({ context }, use) => {
    await context.route('**/*', async (route) => {
      const reason = await checkUrl(route.request().url());
      if (reason) {
        console.warn(`[llx-guard] blocked ${route.request().url()}: ${reason}`);
        await route.abort('blockedbyclient');
      } else {
        await route.fallback();
      }
    });
    await use(context);
  },
  llx: async ({ page, request }, use, testInfo) => {
    const llx = new Llx(page, request, testInfo);
    const consoleErrors: string[] = [];
    page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 500)); });
    const failedRequests: string[] = [];
    page.on('requestfailed', (req) => failedRequests.push(`${req.method()} ${req.url()} ${req.failure()?.errorText || ''}`.slice(0, 500)));
    await use(llx);
    if (testInfo.status !== testInfo.expectedStatus) {
      // Evidence for failure analysis and self-healing.
      let candidates: unknown[] = [];
      let pageUrl = '';
      try {
        pageUrl = page.url();
        if (pageUrl && pageUrl !== 'about:blank') {
          candidates = await page.evaluate(() => {
            const out: any[] = [];
            const els = document.querySelectorAll('a,button,input,select,textarea,[role],h1,h2,h3,label,[data-testid]');
            for (const el of Array.from(els).slice(0, 300)) {
              const h = el as HTMLElement;
              const r = h.getBoundingClientRect();
              out.push({
                tag: h.tagName.toLowerCase(),
                role: h.getAttribute('role') || '',
                text: (h.innerText || '').trim().slice(0, 120),
                id: h.id || '',
                name: h.getAttribute('name') || '',
                type: h.getAttribute('type') || '',
                placeholder: h.getAttribute('placeholder') || '',
                aria_label: h.getAttribute('aria-label') || '',
                testid: h.getAttribute('data-testid') || '',
                label: (h as HTMLInputElement).labels?.[0]?.innerText?.trim() || '',
                visible: r.width > 0 && r.height > 0,
              });
            }
            return out;
          });
        }
      } catch { /* page may be closed */ }
      await testInfo.attach('lorvenlax-failure.json', {
        contentType: 'application/json',
        body: JSON.stringify({
          last_action: llx.lastAction, last_target: llx.lastTarget, page_url: pageUrl,
          console_errors: consoleErrors.slice(-20), failed_requests: failedRequests.slice(-20), candidates,
        }),
      });
    }
  },
});
