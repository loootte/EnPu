interface StatusBannerProps {
  kind: "error" | "info" | "success";
  message: string;
  onDismiss?: () => void;
}

const styles: Record<StatusBannerProps["kind"], string> = {
  error: "border-rose-500/40 bg-rose-500/10 text-rose-100",
  info: "border-sky-500/40 bg-sky-500/10 text-sky-100",
  success: "border-emerald-500/40 bg-emerald-500/10 text-emerald-100",
};

export function StatusBanner({ kind, message, onDismiss }: StatusBannerProps) {
  return (
    <div
      className={`flex items-start gap-3 rounded-lg border px-3 py-2 text-sm ${styles[kind]}`}
      role={kind === "error" ? "alert" : "status"}
    >
      <p className="flex-1 whitespace-pre-wrap">{message}</p>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 text-xs opacity-70 hover:opacity-100"
        >
          关闭
        </button>
      ) : null}
    </div>
  );
}
