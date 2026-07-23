interface ImagePreviewProps {
  src: string | null;
  filename?: string | null;
}

export function ImagePreview({ src, filename }: ImagePreviewProps) {
  if (!src) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border border-white/10 bg-slate-950/50 text-sm text-slate-500">
        尚未选择图片
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-white/10 bg-slate-950/50">
      <div className="flex items-center justify-between border-b border-white/5 px-3 py-2">
        <span className="truncate text-xs text-slate-400" title={filename ?? ""}>
          {filename || "预览"}
        </span>
      </div>
      <div className="flex max-h-[420px] items-center justify-center overflow-auto p-3">
        <img
          src={src}
          alt={filename ? `预览：${filename}` : "简谱预览"}
          className="max-h-[400px] max-w-full object-contain"
        />
      </div>
    </div>
  );
}
