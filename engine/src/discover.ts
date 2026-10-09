/**
 * Website discovery. Usage: node dist/discover.js <config.json> <out-dir>
 *
 * config: { url, max_pages, max_depth, timeout_ms, browser,
 *           login?: { url, username, password } }
 *
 * Crawls same-origin pages breadth-first, never submits forms (except the
 * optional login form), skips links that look destructive, and writes
 * discovery.json plus one screenshot per page into <out-dir>.
 */
import { chromium, firefox, webkit, type Page } from '@playwright/test';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { checkUrl } from './guard';

type Config = {
  url: string;
  max_pages?: number;
  max_depth?: number;
  timeout_ms?: number;
  browser?: 'chromium' | 'firefox' | 'webkit';
  login?: { url?: string; username: string; password: string };
};

const DESTRUCTIVE = /(log ?out|sign ?out|delete|remove|destroy|unsubscribe|deactivate|cancel account|reset)/i;

async function extract(page: Page) {
  return page.evaluate(() => {
    const visible = (el: Element) => {
      const r = (el as HTMLElement).getBoundingClientRect();
      const s = getComputedStyle(el as HTMLElement);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
    };
    const text = (el: Element | null) => ((el as HTMLElement | null)?.innerText || el?.textContent || '').replace(/\s+/g, ' ').trim();
    const labelFor = (el: Element): string => {
      const input = el as HTMLInputElement;
      if (input.labels && input.labels.length) {
        // Label text without the text of controls nested inside it (e.g. <select> options).
        const clone = input.labels[0].cloneNode(true) as HTMLElement;
        clone.querySelectorAll('select,textarea,input,option').forEach((n) => n.remove());
        return (clone.textContent || '').replace(/\s+/g, ' ').trim();
      }
      const aria = el.getAttribute('aria-label');
      if (aria) return aria;
      const by = el.getAttribute('aria-labelledby');
      if (by) return text(document.getElementById(by));
      return '';
    };
    const implicitRole = (el: Element): string => {
      const tag = el.tagName.toLowerCase();
      const type = (el.getAttribute('type') || '').toLowerCase();
      if (el.getAttribute('role')) return el.getAttribute('role')!;
      if (tag === 'a' && el.hasAttribute('href')) return 'link';
      if (tag === 'button' || (tag === 'input' && ['submit', 'button', 'reset'].includes(type))) return 'button';
      if (tag === 'select') return 'combobox';
      if (tag === 'textarea') return 'textbox';
      if (tag === 'input' && type === 'checkbox') return 'checkbox';
      if (tag === 'input' && type === 'radio') return 'radio';
      if (tag === 'input' && ['', 'text', 'email', 'password', 'search', 'tel', 'url', 'number'].includes(type)) return type === 'number' ? 'spinbutton' : 'textbox';
      if (/^h[1-6]$/.test(tag)) return 'heading';
      return '';
    };
    // Locator candidates, best first. Values are resolved by the runtime.
    const locators = (el: Element) => {
      const out: Array<Record<string, string>> = [];
      const testid = el.getAttribute('data-testid');
      if (testid) out.push({ strategy: 'testid', value: testid });
      const role = implicitRole(el);
      const tag = el.tagName.toLowerCase();
      const isField = ['input', 'select', 'textarea'].includes(tag) && !['submit', 'button'].includes((el.getAttribute('type') || '').toLowerCase());
      const label = isField ? labelFor(el) : '';
      if (label) out.push({ strategy: 'label', value: label });
      const name = isField ? label : (el.getAttribute('aria-label') || text(el) || (el as HTMLInputElement).value || '');
      if (role && name && name.length <= 80) out.push({ strategy: 'role', value: role, name });
      const ph = el.getAttribute('placeholder');
      if (ph) out.push({ strategy: 'placeholder', value: ph });
      if (el.id && /^[A-Za-z][\w-]*$/.test(el.id)) out.push({ strategy: 'css', value: `#${el.id}` });
      else if (el.getAttribute('name')) out.push({ strategy: 'css', value: `${tag}[name="${el.getAttribute('name')}"]` });
      return out;
    };

    const fieldInfo = (el: Element) => {
      const i = el as HTMLInputElement;
      return {
        tag: el.tagName.toLowerCase(),
        type: (el.getAttribute('type') || (el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea' : 'text')).toLowerCase(),
        name: el.getAttribute('name') || '',
        label: labelFor(el),
        placeholder: el.getAttribute('placeholder') || '',
        required: i.required || el.getAttribute('aria-required') === 'true',
        min: el.getAttribute('min'), max: el.getAttribute('max'),
        minlength: el.getAttribute('minlength'), maxlength: el.getAttribute('maxlength'),
        pattern: el.getAttribute('pattern'),
        options: el.tagName === 'SELECT' ? Array.from((el as HTMLSelectElement).options).map((o) => o.label || o.value).slice(0, 30) : [],
        locators: locators(el),
      };
    };

    const forms = Array.from(document.querySelectorAll('form')).filter(visible).map((f, idx) => {
      const fields = Array.from(f.querySelectorAll('input,select,textarea'))
        .filter((el) => !['hidden', 'submit', 'button', 'reset', 'image'].includes((el.getAttribute('type') || '').toLowerCase()))
        .filter(visible)
        .map(fieldInfo);
      const submitEl = f.querySelector('button[type=submit],input[type=submit],button:not([type])');
      const heading = f.closest('section,main,div')?.querySelector('h1,h2,h3') ?? null;
      return {
        index: idx,
        id: f.id || '',
        name: f.getAttribute('name') || f.getAttribute('aria-label') || text(heading) || `Form ${idx + 1}`,
        method: (f.getAttribute('method') || 'get').toLowerCase(),
        action: f.getAttribute('action') || '',
        fields,
        submit: submitEl ? { text: text(submitEl) || (submitEl as HTMLInputElement).value || 'Submit', locators: locators(submitEl) } : null,
        has_password: fields.some((x) => x.type === 'password'),
      };
    });

    const links = Array.from(document.querySelectorAll('a[href]')).filter(visible).map((a) => ({
      text: text(a).slice(0, 100),
      href: (a as HTMLAnchorElement).href,
      in_nav: !!a.closest('nav,header,[role=navigation]'),
      locators: locators(a),
    })).filter((l) => l.text);

    const buttons = Array.from(document.querySelectorAll('button,[role=button],input[type=button],input[type=submit]'))
      .filter(visible)
      .filter((b) => !b.closest('form'))
      .map((b) => ({ text: (text(b) || (b as HTMLInputElement).value || b.getAttribute('aria-label') || '').slice(0, 100), locators: locators(b) }))
      .filter((b) => b.text);

    const tables = Array.from(document.querySelectorAll('table')).filter(visible).map((t) => ({
      caption: text(t.querySelector('caption')),
      headers: Array.from(t.querySelectorAll('thead th, tr:first-child th')).map((th) => text(th)).slice(0, 20),
      row_count: t.querySelectorAll('tbody tr').length,
      testid: t.getAttribute('data-testid') || '',
    }));

    const headings = Array.from(document.querySelectorAll('h1,h2,h3')).filter(visible).map((h) => ({ level: Number(h.tagName[1]), text: text(h).slice(0, 150) })).filter((h) => h.text);

    return { title: document.title, headings, forms, links, buttons, tables, text_sample: text(document.body).slice(0, 1500) };
  });
}

async function main() {
  const [configPath, outDir] = process.argv.slice(2);
  const config: Config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  fs.mkdirSync(outDir, { recursive: true });
  const maxPages = Math.min(config.max_pages ?? 15, 50);
  const maxDepth = Math.min(config.max_depth ?? 2, 5);
  const timeout = config.timeout_ms ?? 15000;
  const start = new URL(config.url);
  const origin = start.origin;

  const blocked = await checkUrl(start.toString());
  if (blocked) throw new Error(`Target blocked by network policy: ${blocked}`);

  const browserType = { chromium, firefox, webkit }[config.browser || 'chromium'];
  const browser = await browserType.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  context.setDefaultTimeout(timeout);
  await context.route('**/*', async (route) => {
    const reason = await checkUrl(route.request().url());
    if (reason) await route.abort('blockedbyclient'); else await route.fallback();
  });
  const page = await context.newPage();
  const result: any = { start_url: start.toString(), origin, pages: [], skipped: [], login: null, errors: [] };

  if (config.login) {
    const loginUrl = new URL(config.login.url || start.toString(), start).toString();
    try {
      await page.goto(loginUrl, { waitUntil: 'domcontentloaded' });
      const pwd = page.locator('input[type=password]').first();
      await pwd.waitFor({ timeout });
      // Record the sign-in form now: once signed in, many apps never show this page again,
      // and later pages (e.g. change-password) also contain password fields.
      const before = await extract(page);
      const signInForm = before.forms.find((f: any) => f.fields.filter((x: any) => x.type === 'password').length === 1
        && f.fields.some((x: any) => ['text', 'email', 'tel'].includes(x.type))) || null;
      const signInPage = page.url();
      const formEl = page.locator('form', { has: pwd });
      const scope = (await formEl.count()) ? formEl.first() : page.locator('body');
      const user = scope.locator('input[type=email],input[type=text],input[type=tel],input:not([type])').first();
      await user.fill(config.login.username);
      await pwd.fill(config.login.password);
      // Prefer a button that says sign in / log in, so a "Show password" toggle is never clicked.
      const named = scope.getByRole('button', { name: /sign ?in|log ?in|login|submit|continue/i });
      const submit = (await named.count()) ? named.first() : scope.locator('button[type=submit],input[type=submit]').first();
      await Promise.all([page.waitForLoadState('domcontentloaded'), submit.click()]);
      await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => undefined);
      const stillLogin = await page.locator('input[type=password]').count();
      result.login = { url: loginUrl, page_url: signInPage, success: stillLogin === 0, landed_on: page.url(), form: signInForm };
    } catch (err: any) {
      result.login = { url: loginUrl, success: false, error: String(err.message || err).slice(0, 300) };
    }
  }

  const queue: Array<{ url: string; depth: number; via: string | null }> = [{ url: start.toString(), depth: 0, via: null }];
  if (result.login?.success && result.login.landed_on) queue.unshift({ url: result.login.landed_on, depth: 0, via: 'login' });
  const seen = new Set<string>();
  const norm = (u: string) => { const x = new URL(u); x.hash = ''; return x.toString(); };

  while (queue.length && result.pages.length < maxPages) {
    const item = queue.shift()!;
    const key = norm(item.url);
    if (seen.has(key)) continue;
    seen.add(key);
    try {
      const response = await page.goto(key, { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('networkidle', { timeout: 3000 }).catch(() => undefined);
      const finalUrl = norm(page.url());
      if (new URL(finalUrl).origin !== origin) { result.skipped.push({ url: key, reason: 'redirected off-site' }); continue; }
      if (finalUrl !== key && seen.has(finalUrl) && item.depth > 0) continue;
      seen.add(finalUrl);
      const info = await extract(page);
      const shot = `page-${result.pages.length + 1}.png`;
      await page.screenshot({ path: path.join(outDir, shot) });
      result.pages.push({ url: finalUrl, requested_url: key, status: response?.status() ?? null, depth: item.depth, via: item.via, screenshot: shot, ...info });
      if (item.depth < maxDepth) {
        for (const link of info.links) {
          let u: URL;
          try { u = new URL(link.href); } catch { continue; }
          if (u.origin !== origin) continue;
          if (DESTRUCTIVE.test(link.text) || DESTRUCTIVE.test(u.pathname)) {
            if (!result.skipped.some((x: any) => x.url === u.toString())) result.skipped.push({ url: u.toString(), reason: `destructive-looking link "${link.text}"` });
            continue;
          }
          if (/\.(pdf|zip|png|jpe?g|gif|svg|css|js|xml)$/i.test(u.pathname)) continue;
          u.hash = '';
          if (!seen.has(u.toString())) queue.push({ url: u.toString(), depth: item.depth + 1, via: finalUrl });
        }
      }
    } catch (err: any) {
      result.errors.push({ url: key, error: String(err.message || err).slice(0, 300) });
    }
  }
  // Which pages need a session? Re-open each page in a fresh, anonymous context.
  if (result.login?.success) {
    const anon = await browser.newContext();
    anon.setDefaultTimeout(timeout);
    await anon.route('**/*', async (route) => {
      const reason = await checkUrl(route.request().url());
      if (reason) await route.abort('blockedbyclient'); else await route.fallback();
    });
    const p2 = await anon.newPage();
    for (const pg of result.pages) {
      try {
        await p2.goto(pg.url, { waitUntil: 'domcontentloaded' });
        // Signed-out visitors either get redirected to a sign-in page or (common in single-page
        // apps) see a sign-in form at the same address. Either way, a password field that was not
        // on the signed-in version of the page means the page needs a session.
        await p2.waitForLoadState('networkidle', { timeout: 3000 }).catch(() => undefined);
        const showsPassword = (await p2.locator('input[type=password]').count()) > 0;
        const hadPassword = pg.forms.some((f: any) => f.has_password);
        const redirectedAway = norm(p2.url()) !== pg.url;
        // Either a sign-in form appears in place (single-page apps), or the visit is redirected
        // to a page with a password field (covers pages that have password fields themselves).
        pg.requires_login = showsPassword && (!hadPassword || redirectedAway);
      } catch {
        pg.requires_login = false;
      }
    }
    await anon.close();
  }
  await browser.close();
  fs.writeFileSync(path.join(outDir, 'discovery.json'), JSON.stringify(result, null, 2));
}

main().catch((err) => {
  console.error(String(err?.stack || err));
  process.exit(1);
});
