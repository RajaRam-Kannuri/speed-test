/**
 * Render a self-contained HTML report to PDF. Usage: node dist/pdf.js <in.html> <out.pdf>
 * All network access is blocked; the HTML must embed its own images.
 */
import { chromium } from '@playwright/test';
import * as fs from 'node:fs';

async function main() {
  const [input, output] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.route('**/*', (route) => (route.request().url().startsWith('data:') ? route.fallback() : route.abort()));
  await page.setContent(fs.readFileSync(input, 'utf8'), { waitUntil: 'load' });
  await page.pdf({ path: output, format: 'A4', printBackground: true, margin: { top: '14mm', bottom: '14mm', left: '12mm', right: '12mm' } });
  await browser.close();
}

main().catch((err) => {
  console.error(String(err?.stack || err));
  process.exit(1);
});
