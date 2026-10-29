import { expect, test, type Page } from "@playwright/test";

// Playwright presses the CapsLock key but does not emulate the lock state, so send the
// keyboard event a real keyboard produces: one whose modifier state says Caps Lock is on/off.
async function typeKey(page: Page, capsLock: boolean) {
  await page.locator("#password").evaluate((el, on) => {
    el.dispatchEvent(new KeyboardEvent("keydown", { key: on ? "A" : "a", bubbles: true, modifierCapsLock: on } as KeyboardEventInit));
  }, capsLock);
}

test("sign-in page warns about Caps Lock, can show the password, and links to password reset", async ({ page }) => {
  await page.goto("/login");
  const password = page.locator("#password");
  await password.click();
  await expect(page.getByText("Caps Lock is on")).toBeHidden();

  await typeKey(page, true);
  await expect(page.getByText("Caps Lock is on")).toBeVisible();
  await expect(password).toHaveAttribute("aria-describedby", "password-capslock");
  await page.getByLabel("Email").focus(); // only shown while the password field has focus
  await expect(page.getByText("Caps Lock is on")).toBeHidden();
  await password.focus();
  await expect(page.getByText("Caps Lock is on")).toBeVisible();
  await typeKey(page, false);
  await expect(page.getByText("Caps Lock is on")).toBeHidden();

  await password.fill("Secret123x");
  await expect(password).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "Show password" }).click();
  await expect(password).toHaveAttribute("type", "text");
  await page.getByRole("button", { name: "Hide password" }).click();
  await expect(password).toHaveAttribute("type", "password");

  await page.getByRole("link", { name: "Forgot password?" }).click();
  await expect(page.getByRole("heading", { name: "Forgot your password?" })).toBeVisible();
  await expect(page.getByText("docker compose")).toHaveCount(0); // no server commands for end users
});
