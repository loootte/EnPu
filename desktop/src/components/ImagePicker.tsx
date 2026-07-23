import { useCallback, useRef, useState, type DragEvent } from "react";
import { isAllowedImageFile } from "../lib/api";

interface ImagePickerProps {
  disabled?: boolean;
  onFile: (file: File) => void;
  onError: (message: string) => void;
}

export function ImagePicker({ disabled, onFile, onError }: ImagePickerProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const acceptFile = useCallback(
    (file: File | undefined | null) => {
      if (!file) return;
      if (!isAllowedImageFile(file)) {
        onError("仅支持 png / jpg / jpeg 图片文件。");
        return;
      }
      onFile(file);
    },
    [onError, onFile],
  );

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
    if (disabled) return;
    const file = e.dataTransfer.files?.[0];
    acceptFile(file);
  };

  return (
    <div
      className={[
        "rounded-xl border-2 border-dashed px-4 py-8 text-center transition",
        dragging
          ? "border-indigo-400 bg-indigo-500/10"
          : "border-white/15 bg-slate-950/40 hover:border-white/30",
        disabled ? "pointer-events-none opacity-50" : "cursor-pointer",
      ].join(" ")}
      onDragEnter={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        setDragging(false);
      }}
      onDrop={onDrop}
      onClick={() => inputRef.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          inputRef.current?.click();
        }
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,.png,.jpg,.jpeg"
        className="hidden"
        disabled={disabled}
        onChange={(e) => {
          acceptFile(e.target.files?.[0]);
          // allow re-selecting the same file
          e.target.value = "";
        }}
      />
      <p className="text-sm font-medium text-white">
        点击选择或拖入简谱图片
      </p>
      <p className="mt-1 text-xs text-slate-400">支持 PNG / JPG</p>
    </div>
  );
}
