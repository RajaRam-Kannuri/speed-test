export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4 py-12">
      <div className="mb-8 flex items-center gap-2.5">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-sm font-bold text-primary-foreground">LL</span>
        <div>
          <p className="text-base font-semibold leading-5">LorvenLax AI Testing</p>
          <p className="text-xs text-muted-foreground">Lorven Lax Tech Labs Pvt. Ltd.</p>
        </div>
      </div>
      <div className="w-full max-w-sm">{children}</div>
    </div>
  );
}
