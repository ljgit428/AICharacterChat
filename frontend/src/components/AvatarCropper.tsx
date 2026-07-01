'use client';

import { useCallback, useEffect, useState } from 'react';
import Cropper, { type Area } from 'react-easy-crop';
import { Check, Loader2, X, ZoomIn, ZoomOut } from 'lucide-react';

export interface AvatarCropperCopy {
  title: string;
  hint: string;
  zoomLabel: string;
  cancel: string;
  apply: string;
  invalidImage: string;
}

interface AvatarCropperProps {
  imageSrc: string;
  copy: AvatarCropperCopy;
  onCancel: () => void;
  onApply: (blob: Blob) => void | Promise<void>;
  aspect?: number;
  shape?: 'rect' | 'round';
  outputSize?: number;
  minZoom?: number;
  maxZoom?: number;
}

const DEFAULT_OUTPUT_SIZE = 512;
const JPEG_QUALITY = 0.92;

function createImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new window.Image();
    image.crossOrigin = 'anonymous';
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('Failed to load image'));
    image.src = src;
  });
}

async function extractCroppedBlob(
  imageSrc: string,
  pixelCrop: Area,
  outputSize: number,
): Promise<Blob> {
  const image = await createImage(imageSrc);
  const canvas = document.createElement('canvas');
  canvas.width = outputSize;
  canvas.height = outputSize;
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    throw new Error('Canvas 2d context not available');
  }
  // White background so transparent PNGs do not become black when JPEGed.
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, outputSize, outputSize);
  ctx.drawImage(
    image,
    pixelCrop.x,
    pixelCrop.y,
    pixelCrop.width,
    pixelCrop.height,
    0,
    0,
    outputSize,
    outputSize,
  );
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          reject(new Error('Canvas toBlob returned null'));
          return;
        }
        resolve(blob);
      },
      'image/jpeg',
      JPEG_QUALITY,
    );
  });
}

export default function AvatarCropper({
  imageSrc,
  copy,
  onCancel,
  onApply,
  aspect = 1,
  shape = 'rect',
  outputSize = DEFAULT_OUTPUT_SIZE,
  minZoom = 1,
  maxZoom = 4,
}: AvatarCropperProps) {
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [croppedAreaPixels, setCroppedAreaPixels] = useState<Area | null>(null);
  const [isApplying, setIsApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onCropComplete = useCallback((_area: Area, pixels: Area) => {
    setCroppedAreaPixels(pixels);
  }, []);

  const handleApply = useCallback(async () => {
    if (!croppedAreaPixels) {
      return;
    }
    setIsApplying(true);
    setError(null);
    try {
      const blob = await extractCroppedBlob(imageSrc, croppedAreaPixels, outputSize);
      await onApply(blob);
    } catch (err) {
      console.error('AvatarCropper apply failed', err);
      setError(copy.invalidImage);
      setIsApplying(false);
    }
  }, [croppedAreaPixels, imageSrc, outputSize, onApply, copy.invalidImage]);

  // ESC closes the cropper unless the apply is in flight.
  useEffect(() => {
    if (isApplying) {
      return;
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onCancel();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isApplying, onCancel]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={copy.title}
    >
      <div className="w-full max-w-md overflow-hidden rounded-3xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <h2 className="text-lg font-semibold text-slate-900">{copy.title}</h2>
          <button
            type="button"
            onClick={onCancel}
            disabled={isApplying}
            className="rounded-full p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
            aria-label={copy.cancel}
          >
            <X size={20} />
          </button>
        </div>

        <div className="relative h-72 w-full bg-slate-900 sm:h-80">
          <Cropper
            image={imageSrc}
            crop={crop}
            zoom={zoom}
            aspect={aspect}
            cropShape={shape}
            showGrid={false}
            objectFit="contain"
            onCropChange={setCrop}
            onZoomChange={setZoom}
            onCropComplete={onCropComplete}
            minZoom={minZoom}
            maxZoom={maxZoom}
            zoomSpeed={0.5}
          />
        </div>

        <div className="space-y-4 px-6 py-5">
          <p className="text-center text-xs text-slate-500">{copy.hint}</p>

          {error && (
            <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-center text-xs text-red-700">
              {error}
            </p>
          )}

          <div className="flex items-center gap-3">
            <ZoomOut size={16} className="shrink-0 text-slate-500" />
            <input
              type="range"
              min={minZoom}
              max={maxZoom}
              step={0.05}
              value={zoom}
              onChange={(event) => setZoom(parseFloat(event.target.value))}
              aria-label={copy.zoomLabel}
              className="h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-slate-200 accent-blue-600"
            />
            <ZoomIn size={16} className="shrink-0 text-slate-500" />
          </div>

          <div className="flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={onCancel}
              disabled={isApplying}
              className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-50"
            >
              {copy.cancel}
            </button>
            <button
              type="button"
              onClick={handleApply}
              disabled={isApplying || !croppedAreaPixels}
              className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isApplying ? <Loader2 className="animate-spin" size={16} /> : <Check size={16} />}
              <span>{copy.apply}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
