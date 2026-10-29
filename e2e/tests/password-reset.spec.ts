import fs from "node:fs";
import path from "node:path";
import { expect, test, type Browser, type Page } from "@playwright/test";

// Password reset through the real UI and real email. The API must send mail to the
// development SMTP sink (scripts/dev-services.sh start mail), which saves messages to
// E2E_MAILDIR; these tests read the links from those messages.

const MAILDIR = process.env.E2E_MAILDIR || "";
const stamp = Date.now();
const owner = { name: "Asha Owner", email: `reset-owner-${stamp}@example.com`, password: "Owner-Passw0rd-1", org: "Reset QA" };

test.describe.configure({ mode: "serial" });
test.skip(!MAILDIR, "Set E2E_MAILDIR to the SMTP sink folder to run the email tests");

function decodeQuotedPrintable(raw: string) {
  return raw.replace(/=\r?\n/g, "").replace(/=([0-9A-F]{2})/g, (_, h) => String.fromCharCode(parseInt(h, 16)));
}

async function latestMail(to: string, subject: string, after: number): Promise<string> {
  let found = "";
  await expect.poll(() => {
    const files = fs.readdirSync(MAILDIR).filter((f) => f.endsWith(".eml") && Number(f.slice(0, -4)) / 1e6 >= after).sort();
    for (const f of files.reverse()) {
      const raw = decodeQuotedPrintable(fs.readFileSync(path.join(MAILDIR, f), "utf8"));
      if (raw.includes(`To: ${to}`) && raw.includes(`Subject: ${subject}`)) { found = raw; return true; }
    }
    return false;
  }, { timeout: 15_000, message: `email "${subject}" to ${to}` }).toBe(true);
  return found;
}

function resetLink(mail: string) {
  const m = mail.match(/https?:\/\/[^\s"<]+\/reset-password\?token=[\w-]+/);
  if (!m) throw new Error("no reset link in email");
  const url = new URL(m[0]);
  return url.pathname + url.search; // open it on the server under test
}

async function register(browser: Browser, u: typeof owner): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await page.goto("/register");
  await page.getByLabel("Your name").fill(u.name);
  await page.getByLabel("Work email").fill(u.email);
  await page.getByLabel("Password").fill(u.password);
  await page.getByLabel("Company or team name").fill(u.org);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: new RegExp(`Welcome, ${u.name.split(" ")[0]}`) })).toBeVisible();
  return page;
}

let link = "";

test("forgot password emails a link that sets a new password", async ({ browser, page }) => {
  (await register(browser, owner)).context().close();
  const sentAfter = Date.now();

  await page.goto("/login");
  await page.getByRole("link", { name: "Forgot password?" }).click();
  await page.getByLabel("Email").fill(owner.email);
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
  await expect(page.getByText(owner.email)).toBeVisible();

  const mail = await latestMail(owner.email, "Reset your LorvenLax password", sentAfter);
  link = resetLink(mail);
  await page.goto(link);
  await expect(page.getByRole("heading", { name: "Choose a new password" })).toBeVisible();
  await expect(page.getByText(owner.email)).toBeVisible();

  const rules = page.getByRole("list", { name: "Password requirements" });
  await page.getByLabel("New password", { exact: true }).fill("Fresh-Passw0rd-2");
  await page.getByLabel("Confirm new password").fill("Fresh-Passw0rd-X");
  await expect(rules.getByText("At least 10 characters")).toBeVisible();
  await expect(rules.locator("li", { hasText: "Both passwords match" })).toContainText("(not met)");
  await page.getByRole("button", { name: "Update password" }).click();
  await expect(page.getByText("The passwords do not match.")).toBeVisible();

  await page.getByLabel("Confirm new password").fill("Fresh-Passw0rd-2");
  await expect(rules.locator("li", { hasText: "Both passwords match" })).toContainText("(met)");
  await page.getByRole("button", { name: "Update password" }).click();
  await expect(page).toHaveURL(/\/login\?reset=1/);
  await expect(page.getByText("Your password has been updated.")).toBeVisible();
  await latestMail(owner.email, "Your LorvenLax password was changed", sentAfter);

  await page.getByLabel("Email").fill(owner.email);
  await page.locator("#password").fill(owner.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Email or password is incorrect.")).toBeVisible();
  await page.locator("#password").fill("Fresh-Passw0rd-2");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /Welcome, Asha/ })).toBeVisible();
  owner.password = "Fresh-Passw0rd-2";
});

test("a used reset link shows a clear expired page", async ({ page }) => {
  await page.goto(link);
  await expect(page.getByRole("heading", { name: "This link has expired" })).toBeVisible();
  await page.getByRole("link", { name: "Request a new link" }).click();
  await expect(page.getByRole("heading", { name: "Forgot your password?" })).toBeVisible();
});

test("signed-in users change their password in Settings > Account", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(owner.email);
  await page.locator("#password").fill(owner.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /Welcome, Asha/ })).toBeVisible();
  await page.goto("/settings");
  await page.getByRole("tab", { name: "Account" }).click();
  await page.getByLabel("Current password").fill("wrong-password-1");
  await page.getByLabel("New password", { exact: true }).fill("Third-Passw0rd-3");
  await page.getByLabel("Confirm new password").fill("Third-Passw0rd-3");
  await page.getByRole("button", { name: "Update password" }).click();
  await expect(page.getByText("Your current password is incorrect.")).toBeVisible();
  await page.getByLabel("Current password").fill(owner.password);
  await page.getByRole("button", { name: "Update password" }).click();
  await expect(page.getByText("Your password has been changed.")).toBeVisible();
  await page.reload(); // this session stays signed in
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
});

test("admins send reset links from Settings > Team", async ({ browser, page }) => {
  const teammate = { name: "Ravi Member", email: `reset-member-${stamp}@example.com`, password: "Member-Passw0rd-1", org: "Ravi home" };
  const memberPage = await register(browser, teammate);

  await page.goto("/login");
  await page.getByLabel("Email").fill(owner.email);
  await page.locator("#password").fill("Third-Passw0rd-3");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /Welcome, Asha/ })).toBeVisible();
  await page.goto("/settings");
  await page.getByRole("tab", { name: "Team" }).click();
  const invitedAfter = Date.now();
  await page.getByLabel("Invite by email").fill(teammate.email);
  await page.getByRole("button", { name: "Create invitation" }).click();
  await expect(page.getByText(`We emailed an invitation to ${teammate.email}`)).toBeVisible();
  const invite = await latestMail(teammate.email, "Asha Owner invited you to Reset QA on LorvenLax", invitedAfter);
  const invitePath = new URL(invite.match(/https?:\/\/[^\s"<]+\/invite\/[\w-]+/)![0]).pathname;
  await memberPage.goto(invitePath);
  await memberPage.getByRole("button", { name: "Accept invitation" }).click();
  await expect(memberPage).not.toHaveURL(/\/invite\//);
  await memberPage.context().close();

  await page.reload();
  await page.getByRole("tab", { name: "Team" }).click();
  await page.getByRole("button", { name: `Reset password for ${teammate.email}` }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "Reset password for Ravi Member" })).toBeVisible();
  await dialog.getByRole("button", { name: "Send reset link" }).click();
  // Ravi also owns his own workspace, so an admin here must not be able to take over the account.
  await expect(dialog.getByText(/also belongs to other workspaces/)).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
});
